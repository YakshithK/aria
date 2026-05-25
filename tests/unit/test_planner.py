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

    assert result == {"status": "max_turns", "turns": 3}


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
