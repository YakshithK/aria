import asyncio
import json
from dataclasses import dataclass

from aria.models import Action, SemanticMap
from aria.planner import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TOOLS,
    SYSTEM_PROMPT,
    OllamaChatClient,
    OllamaPlanner,
    _guard_action_against_task,
    _has_failed_tool_result,
    append_tool_history,
    action_from_tool_call,
    tool_schemas_by_name,
)


def empty_semantic_map_json():
    return SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window=None,
        windows=[],
        elements={},
        clipboard=None,
    ).model_dump_json()


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction


@dataclass
class FakeMessage:
    content: str | None = None
    tool_calls: list[FakeToolCall] | None = None


@dataclass
class FakeChoice:
    finish_reason: str
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list[FakeChoice]


class FakeOllamaClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeConductor:
    def __init__(self):
        self.actions = []

    async def get_current_state(self, scope):
        assert scope == "focused+registry"
        return empty_semantic_map_json()

    async def execute(self, action):
        assert isinstance(action, Action)
        self.actions.append(action)
        return {"ok": True, "action": action.type}


class ChannelMapConductor(FakeConductor):
    async def get_current_state(self, scope):
        assert scope == "focused+registry"
        return SemanticMap(
            timestamp="2026-05-24T20:00:00Z",
            focused_window="cdp:discord:page-1",
            windows=[],
            elements={
                "cdp:page-1:dom_11": {
                    "id": "cdp:page-1:dom_11",
                    "role": "link",
                    "name": "rules (text channel)",
                    "value": "https://discord.com/channels/server/rules",
                    "bounds": [0, 0, 10, 10],
                    "enabled": True,
                    "focused": False,
                    "actions": ["invoke"],
                    "children": [],
                }
            },
            clipboard=None,
        ).model_dump_json()


def tool_call(name, arguments, tool_call_id="call-1"):
    return FakeToolCall(
        id=tool_call_id,
        function=FakeFunction(name=name, arguments=json.dumps(arguments)),
    )


def test_tool_schema_valid():
    tools = tool_schemas_by_name()

    assert set(tools) == {
        "focus_window",
        "observe_window",
        "set_value",
        "type",
        "navigate",
        "invoke",
        "scroll",
        "key_combo",
        "wait_for",
    }
    for schema in OLLAMA_TOOLS:
        assert schema["type"] == "function"
        assert schema["function"]["name"] in tools
        assert schema["function"]["parameters"]["type"] == "object"
        assert "properties" in schema["function"]["parameters"]


def test_history_assistant_and_tool_result_format():
    history = []
    calls = [tool_call("observe_window", {"type": "focus_window", "target_id": "win:1"})]

    append_tool_history(history, FakeMessage(content=None, tool_calls=calls), ["observed"])

    assert history[0] == {
        "role": "assistant",
        "content": None,
        "tool_calls": calls,
    }
    assert history[1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "observed",
    }


def test_end_turn_exits_complete():
    client = FakeOllamaClient(
        [FakeResponse([FakeChoice("stop", FakeMessage(content="Done"))])]
    )
    planner = OllamaPlanner(client=client, conductor=FakeConductor())

    result = asyncio.run(planner.run_task("do it"))

    assert result == {"status": "complete", "turns": 1}
    assert client.calls[0]["model"] == OLLAMA_MODEL
    assert client.calls[0]["tools"] == OLLAMA_TOOLS
    assert client.calls[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert client.calls[0]["messages"][1] == {"role": "user", "content": "do it"}


def test_tool_call_executes_action_and_appends_ollama_tool_history():
    tool = tool_call(
        "set_value",
        {"type": "set_value", "target_id": "cdp:page:nodeId_2", "payload": {"text": "hi"}},
    )
    client = FakeOllamaClient(
        [
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[tool]))]),
            FakeResponse([FakeChoice("stop", FakeMessage(content="Done"))]),
        ]
    )
    conductor = FakeConductor()
    planner = OllamaPlanner(client=client, conductor=conductor)

    result = asyncio.run(planner.run_task("type hi"))

    assert result == {
        "status": "complete",
        "turns": 2,
        "tool_trace": [
            {
                "name": "set_value",
                "action": {
                    "type": "set_value",
                    "target_id": "cdp:page:nodeId_2",
                    "payload": {"text": "hi"},
                },
                "result": "{'ok': True, 'action': 'set_value'}",
            }
        ],
    }
    assert conductor.actions == [
        Action(type="set_value", target_id="cdp:page:nodeId_2", payload={"text": "hi"})
    ]
    second_call_messages = client.calls[1]["messages"]
    assert second_call_messages[2]["role"] == "assistant"
    assert second_call_messages[2]["tool_calls"] == [tool]
    assert second_call_messages[3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "{'ok': True, 'action': 'set_value'}",
    }


def test_action_from_tool_call_infers_type_from_function_name():
    action = action_from_tool_call(
        tool_call("key_combo", {"payload": {"keys": ["Control", "L"]}})
    )

    assert action == Action(type="key_combo", target_id=None, payload={"keys": ["Control", "L"]})


def test_max_turns_guard():
    client = FakeOllamaClient(
        [
            FakeResponse(
                [
                    FakeChoice(
                        "tool_calls",
                        FakeMessage(
                            tool_calls=[
                                tool_call(
                                    "observe_window",
                                    {"type": "observe_window", "target_id": "win:1"},
                                )
                            ]
                        ),
                    )
                ]
            )
            for _ in range(3)
        ]
    )
    planner = OllamaPlanner(client=client, conductor=FakeConductor())

    result = asyncio.run(planner.run_task("loop", max_turns=3))

    assert result["status"] == "max_turns"
    assert result["turns"] == 3
    assert result["tool_trace"][0]["name"] == "observe_window"


def test_timeout_guard_includes_tool_trace_when_actions_ran():
    times = iter([0.0, 0.0, 301.0])
    tool = tool_call(
        "focus_window",
        {"type": "focus_window", "target_id": "cdp:notion:page-2"},
    )
    planner = OllamaPlanner(
        client=FakeOllamaClient(
            [FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[tool]))])]
        ),
        conductor=FakeConductor(),
        monotonic=lambda: next(times),
    )

    result = asyncio.run(planner.run_task("timeout", timeout=300.0))

    assert result["status"] == "timeout"
    assert result["turns"] == 1
    assert result["tool_trace"][0]["name"] == "focus_window"


def test_repeated_observe_without_new_information_stops_with_diagnostic():
    observe = tool_call(
        "observe_window",
        {"type": "observe_window", "target_id": "cdp:chrome:page-1"},
    )
    client = FakeOllamaClient(
        [
            FakeResponse(
                [FakeChoice("tool_calls", FakeMessage(tool_calls=[observe]))]
            )
            for _ in range(4)
        ]
    )
    planner = OllamaPlanner(client=client, conductor=FakeConductor())

    result = asyncio.run(planner.run_task("click a result"))

    assert result["status"] == "stalled"
    assert result["turns"] == 4
    assert result["reason"] == "repeated_observe_without_new_information"
    assert "observe_window" in result["message"]


def test_repeated_action_without_progress_stops_with_diagnostic():
    invoke = tool_call(
        "invoke",
        {"type": "invoke", "target_id": "cdp:page-1:dom_7"},
    )
    client = FakeOllamaClient(
        [
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[invoke]))])
            for _ in range(4)
        ]
    )
    planner = OllamaPlanner(client=client, conductor=FakeConductor())

    result = asyncio.run(planner.run_task("click a channel"))

    assert result["status"] == "stalled"
    assert result["turns"] == 4
    assert result["reason"] == "repeated_action_without_progress"
    assert "cdp:page-1:dom_7" in result["message"]


def test_guard_rejects_wrong_discord_text_channel_before_clicking():
    semantic_map = asyncio.run(ChannelMapConductor().get_current_state("focused+registry"))

    result = _guard_action_against_task(
        "read #announcements",
        semantic_map,
        Action(type="invoke", target_id="cdp:page-1:dom_11"),
    )

    assert result["ok"] is False
    assert result["reason"] == "wrong_discord_channel"
    assert result["requested_channel"] == "announcements"
    assert result["clicked_channel"] == "rules (text channel)"


def test_guard_allows_requested_discord_text_channel():
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:discord:page-1",
        windows=[],
        elements={
            "cdp:page-1:dom_12": {
                "id": "cdp:page-1:dom_12",
                "role": "link",
                "name": "announcements (text channel)",
                "value": "https://discord.com/channels/server/announcements",
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": ["invoke"],
                "children": [],
            }
        },
        clipboard=None,
    ).model_dump_json()

    result = _guard_action_against_task(
        "read #announcements",
        semantic_map,
        Action(type="invoke", target_id="cdp:page-1:dom_12"),
    )

    assert result is None


def test_guard_rejects_navigating_notion_target_to_discord():
    result = _guard_action_against_task(
        "read #announcements and paste into Notion",
        empty_semantic_map_json(),
        Action(
            type="navigate",
            target_id="cdp:notion:page-1",
            payload={"url": "https://discord.com/app"},
        ),
    )

    assert result["ok"] is False
    assert result["reason"] == "wrong_app_navigation"
    assert "Notion" in result["message"]


def test_guard_rejects_login_flow_when_task_does_not_ask_for_login():
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:notion:page-1",
        windows=[],
        elements={
            "cdp:page-1:dom_3": {
                "id": "cdp:page-1:dom_3",
                "role": "button",
                "name": "Log In",
                "value": None,
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": ["invoke"],
                "children": [],
            }
        },
        clipboard=None,
    ).model_dump_json()

    result = _guard_action_against_task(
        "read #announcements and paste into Notion",
        semantic_map,
        Action(type="invoke", target_id="cdp:page-1:dom_3"),
    )

    assert result["ok"] is False
    assert result["reason"] == "unexpected_login_flow"
    assert "unexpected_login_flow" == result["reason"]
    assert "available_windows" in result


def test_guard_rejects_placeholder_credentials():
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:notion:page-1",
        windows=[],
        elements={
            "cdp:page-1:dom_1": {
                "id": "cdp:page-1:dom_1",
                "role": "textbox",
                "name": "Password",
                "value": None,
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": ["set_value"],
                "children": [],
            }
        },
        clipboard=None,
    ).model_dump_json()

    result = _guard_action_against_task(
        "read #announcements and paste into Notion",
        semantic_map,
        Action(type="set_value", target_id="cdp:page-1:dom_1", payload={"text": "USER_PASSWORD"}),
    )

    assert result["ok"] is False
    assert result["reason"] == "placeholder_credentials"


def test_failed_tool_result_detection_handles_structured_failures():
    assert _has_failed_tool_result({"ok": False, "error": "captcha"})
    assert _has_failed_tool_result({"ok": False, "reason": "wrong_discord_channel"})
    assert not _has_failed_tool_result({"ok": True})


def test_timeout_guard():
    times = iter([0.0, 301.0])
    planner = OllamaPlanner(
        client=FakeOllamaClient([]),
        conductor=FakeConductor(),
        monotonic=lambda: next(times),
    )

    result = asyncio.run(planner.run_task("timeout", timeout=300.0))

    assert result == {"status": "timeout", "turns": 0}


def test_ollama_chat_client_uses_local_openai_compatible_endpoint(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            captured["base_url"] = base_url
            captured["api_key"] = api_key

    monkeypatch.setattr("aria.planner.OpenAI", FakeOpenAI)

    client = OllamaChatClient()

    assert client.model == OLLAMA_MODEL
    assert captured == {"base_url": OLLAMA_BASE_URL, "api_key": "ollama"}
