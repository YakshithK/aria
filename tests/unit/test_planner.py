import asyncio
import concurrent.futures
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
    _channels_match,
    _format_state_for_llm,
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


class NeverCompletesExecutor(concurrent.futures.Executor):
    def submit(self, fn, /, *args, **kwargs):
        return concurrent.futures.Future()


class InlineExecutor(concurrent.futures.Executor):
    def submit(self, fn, /, *args, **kwargs):
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


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


class SequencedStateConductor(FakeConductor):
    def __init__(self, states):
        super().__init__()
        self.states = list(states)

    async def get_current_state(self, scope):
        assert scope == "focused+registry"
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


def tool_call(name, arguments, tool_call_id="call-1"):
    return FakeToolCall(
        id=tool_call_id,
        function=FakeFunction(name=name, arguments=json.dumps(arguments)),
    )


def test_tool_schema_valid():
    tools = tool_schemas_by_name()

    assert set(tools) == {
        "focus_window",
        "set_value",
        "type",
        "write_to",
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
    planner = OllamaPlanner(
        client=client,
        conductor=FakeConductor(),
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("do it"))

    assert result["status"] == "complete"
    assert result["turns"] == 1
    assert result["message"] == "Done"
    assert "elapsed_seconds" in result
    assert "total_prompt_tokens" in result
    assert client.calls[0]["model"] == OLLAMA_MODEL
    assert client.calls[0]["tools"] == OLLAMA_TOOLS
    assert client.calls[0]["extra_body"] == {"think": False}
    assert client.calls[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert SYSTEM_PROMPT.startswith("/no_think\n")
    assert client.calls[0]["messages"][1] == {"role": "user", "content": "do it"}


def test_planner_progress_uses_stdout_not_stderr(capsys):
    client = FakeOllamaClient(
        [FakeResponse([FakeChoice("stop", FakeMessage(content="Done"))])]
    )
    planner = OllamaPlanner(
        client=client,
        conductor=FakeConductor(),
        executor=InlineExecutor(),
    )

    asyncio.run(planner.run_task("do it"))

    captured = capsys.readouterr()
    assert "[turn 01 |" in captured.out
    assert "Aria run summary" in captured.out
    captured.out.encode("ascii")
    assert captured.err == ""


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
    planner = OllamaPlanner(
        client=client,
        conductor=conductor,
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("type hi"))

    assert result["status"] == "complete"
    assert result["turns"] == 2
    assert result["message"] == "Done"
    assert result["tool_trace"] == [
        {
            "name": "set_value",
            "action": {
                "type": "set_value",
                "target_id": "cdp:page:nodeId_2",
                "payload": {"text": "hi"},
            },
            "result": "{'ok': True, 'action': 'set_value'}",
        }
    ]
    assert conductor.actions == [
        Action(type="set_value", target_id="cdp:page:nodeId_2", payload={"text": "hi"})
    ]
    second_call_messages = client.calls[1]["messages"]
    # messages: [system, task, state_turn_1, assistant, tool, state_turn_2(current)]
    assert second_call_messages[2]["role"] == "user"  # state persisted from turn 1
    assert second_call_messages[3]["role"] == "assistant"
    assert second_call_messages[3]["tool_calls"] == [tool]
    assert second_call_messages[4] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "{'ok': True, 'action': 'set_value'}",
    }


def test_planner_executes_textual_tool_call_returned_as_stop_content():
    client = FakeOllamaClient(
        [
            FakeResponse(
                [
                    FakeChoice(
                        "stop",
                        FakeMessage(
                            content=json.dumps(
                                {
                                    "name": "focus_window",
                                    "arguments": {
                                        "target_id": "cdp:notion:page-1",
                                    },
                                }
                            )
                        ),
                    )
                ]
            ),
            FakeResponse([FakeChoice("stop", FakeMessage(content="Done"))]),
        ]
    )
    conductor = FakeConductor()
    planner = OllamaPlanner(
        client=client,
        conductor=conductor,
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("switch to Notion"))

    assert result["status"] == "complete"
    assert result["turns"] == 2
    assert conductor.actions == [
        Action(type="focus_window", target_id="cdp:notion:page-1", payload=None)
    ]
    assert result["tool_trace"][0]["name"] == "focus_window"


def test_planner_resolves_compact_target_alias_before_executing_action():
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:notion:UUID-N",
        windows=[
            {
                "id": "cdp:notion:UUID-N",
                "app": "Notion",
                "title": "My page",
                "backend": "cdp",
                "focused": True,
                "minimized": False,
                "bounds": [0, 0, 800, 600],
                "root_elements": ["cdp:UUID-N:dom_58"],
            }
        ],
        elements={
            "cdp:UUID-N:dom_58": {
                "id": "cdp:UUID-N:dom_58",
                "role": "textbox",
                "name": "",
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
    write_tool = tool_call(
        "write_to",
        {
            "type": "write_to",
            "target_id": "notion:box_1",
            "payload": {"text": "Summary\n- Complete result line"},
        },
    )
    client = FakeOllamaClient(
        [
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[write_tool]))]),
            FakeResponse([FakeChoice("stop", FakeMessage(content="Done"))]),
        ]
    )
    conductor = SequencedStateConductor([semantic_map, semantic_map])
    planner = OllamaPlanner(client=client, conductor=conductor, executor=InlineExecutor())

    asyncio.run(planner.run_task("write into Notion"))

    assert conductor.actions == [
        Action(
            type="write_to",
            target_id="cdp:UUID-N:dom_58",
            payload={"text": "Summary\n- Complete result line"},
        )
    ]


def test_planner_fails_if_model_stops_after_partial_write_verification():
    written_text = "Summary of Discord #announcements:\n- Open Campus on May 15\n- Ship It at 3 PM"
    before_write = empty_semantic_map_json()
    after_partial_write = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:notion:page-1",
        windows=[
            {
                "id": "cdp:notion:page-1",
                "app": "Notion",
                "title": "Demo",
                "backend": "cdp",
                "focused": True,
                "minimized": False,
                "bounds": [0, 0, 800, 600],
                "root_elements": ["cdp:page-1:dom_1"],
            }
        ],
        elements={
            "cdp:page-1:dom_1": {
                "id": "cdp:page-1:dom_1",
                "role": "text",
                "name": "Summary of Discord #announcements:",
                "value": None,
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": [],
                "children": [],
            }
        },
        clipboard=None,
    ).model_dump_json()
    type_tool = tool_call(
        "type",
        {
            "type": "type",
            "target_id": "cdp:page-1:dom_58",
            "payload": {"text": written_text},
        },
    )
    client = FakeOllamaClient(
        [
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[type_tool]))]),
            FakeResponse([FakeChoice("stop", FakeMessage(content="done"))]),
        ]
    )
    planner = OllamaPlanner(
        client=client,
        conductor=SequencedStateConductor([before_write, after_partial_write]),
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("write a Discord summary into Notion"))

    assert result["status"] == "failed"
    assert result["reason"] == "write_verification_failed"
    assert result["missing_text_fragments"] == ["Open Campus on May 15", "Ship It at 3 PM"]


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
    planner = OllamaPlanner(
        client=client,
        conductor=FakeConductor(),
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("loop", max_turns=3))

    assert result["status"] == "max_turns"
    assert result["turns"] == 3
    assert result["tool_trace"][0]["name"] == "observe_window"


def test_timeout_guard_includes_tool_trace_when_actions_ran():
    # monotonic call order: start, turn0(timeout_check, llm_start, llm_end), turn1(timeout_check)
    times = iter([0.0, 0.0, 0.0, 0.0, 301.0])
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
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("timeout", timeout=300.0))

    assert result["status"] == "timeout"
    assert result["turns"] == 1
    assert result["tool_trace"][0]["name"] == "focus_window"


def test_timeout_guard_interrupts_stuck_llm_call():
    planner = OllamaPlanner(
        client=FakeOllamaClient([]),
        conductor=FakeConductor(),
        executor=NeverCompletesExecutor(),
    )

    result = asyncio.run(planner.run_task("timeout", timeout=0.01))

    assert result["status"] == "timeout"
    assert result["turns"] == 0


def test_format_state_for_llm_labels_active_and_background():
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:discord:UUID-D",
        windows=[
            {
                "id": "cdp:discord:UUID-D",
                "app": "Discord",
                "title": "#announcements",
                "backend": "cdp",
                "focused": True,
                "minimized": False,
                "bounds": [0, 0, 800, 600],
                "root_elements": ["cdp:UUID-D:dom_1"],
            },
            {
                "id": "cdp:notion:UUID-N",
                "app": "Notion",
                "title": "My page",
                "backend": "cdp",
                "focused": False,
                "minimized": False,
                "bounds": [0, 0, 800, 600],
                "root_elements": [],
            },
        ],
        elements={
            "cdp:UUID-D:dom_1": {
                "id": "cdp:UUID-D:dom_1",
                "role": "link",
                "name": "announcements (text channel)",
                "value": "https://discord.com/channels/s/c",
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": ["invoke"],
                "children": [],
            }
        },
        clipboard=None,
    ).model_dump_json()

    result = _format_state_for_llm(semantic_map)

    assert "=== ACTIVE: Discord ===" in result
    assert "=== BACKGROUND: Notion ===" in result
    assert "[navigation]" in result
    assert "discord:ch_1" in result
    assert "cdp:UUID-D:dom_1" not in result
    assert "invoke to navigate" in result
    # Background section should NOT list elements
    assert "cdp:UUID-N:" not in result
    # Background section should include focus hint
    assert 'focus_window("cdp:notion:UUID-N")' in result


def test_format_state_for_llm_groups_content_and_toolbar_regions():
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:notion:UUID-N",
        windows=[
            {
                "id": "cdp:notion:UUID-N",
                "app": "Notion",
                "title": "My page",
                "backend": "cdp",
                "focused": True,
                "minimized": False,
                "bounds": [0, 0, 800, 600],
                "root_elements": [],
            }
        ],
        elements={
            "cdp:UUID-N:dom_1": {
                "id": "cdp:UUID-N:dom_1",
                "role": "button",
                "name": "Share",
                "value": None,
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": ["invoke"],
                "children": [],
            },
            "cdp:UUID-N:dom_2": {
                "id": "cdp:UUID-N:dom_2",
                "role": "text",
                "name": "Existing page body",
                "value": None,
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": [],
                "children": [],
            },
            "cdp:UUID-N:dom_3": {
                "id": "cdp:UUID-N:dom_3",
                "role": "textbox",
                "name": "",
                "value": None,
                "bounds": [0, 0, 10, 10],
                "enabled": True,
                "focused": False,
                "actions": ["set_value"],
                "children": [],
            },
        },
        clipboard=None,
    ).model_dump_json()

    result = _format_state_for_llm(semantic_map)

    assert "[toolbar]" in result
    assert "notion:btn_1" in result
    assert "[content]" in result
    assert "notion:txt_1" in result
    assert "notion:box_1" in result
    assert "cdp:UUID-N:dom_" not in result


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
    planner = OllamaPlanner(
        client=client,
        conductor=FakeConductor(),
        executor=InlineExecutor(),
    )

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


def test_oscillating_actions_stops_with_diagnostic():
    notion_focus = tool_call(
        "focus_window",
        {"type": "focus_window", "target_id": "cdp:notion:PAGE-1"},
        tool_call_id="call-a",
    )
    discord_focus = tool_call(
        "focus_window",
        {"type": "focus_window", "target_id": "cdp:discord:PAGE-2"},
        tool_call_id="call-b",
    )
    client = FakeOllamaClient(
        [
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[notion_focus]))]),
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[discord_focus]))]),
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[notion_focus]))]),
            FakeResponse([FakeChoice("tool_calls", FakeMessage(tool_calls=[discord_focus]))]),
        ]
    )
    planner = OllamaPlanner(
        client=client,
        conductor=FakeConductor(),
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("write to notion"))

    assert result["status"] == "stalled"
    assert result["reason"] == "oscillating_actions"
    assert result["turns"] == 4


def test_guard_allows_misspelled_discord_channel_name():
    """Discord server owners sometimes misspell channel names; the guard should be tolerant."""
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:discord:page-1",
        windows=[],
        elements={
            "cdp:page-1:dom_9": {
                "id": "cdp:page-1:dom_9",
                "role": "link",
                "name": "📢-annoucements (text channel)",
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
        Action(type="invoke", target_id="cdp:page-1:dom_9"),
    )

    assert result is None  # guard should allow it despite the typo


def test_channels_match_exact():
    assert _channels_match("announcements", "announcements (text channel)")
    assert _channels_match("announcements", "#announcements (text channel)")
    assert not _channels_match("announcements", "rules (text channel)")


def test_channels_match_tolerates_typos():
    assert _channels_match("announcements", "📢-annoucements (text channel)")
    assert not _channels_match("announcements", "📢-general (text channel)")


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
        executor=InlineExecutor(),
    )

    result = asyncio.run(planner.run_task("timeout", timeout=300.0))

    assert result["status"] == "timeout"
    assert result["turns"] == 0
    assert result["elapsed_seconds"] == 301.0


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
