from dataclasses import dataclass
import json

from aria.conductor.orchestrator import Orchestrator, PLAN_TOOL, Subtask, _decompose_task


@dataclass
class FakeMessage:
    content: str | None = None
    tool_calls: list | None = None


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    function: FakeFunction


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list[FakeChoice]


class FakeClient:
    def __init__(self, *messages: FakeMessage):
        self.messages = list(messages)
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse([FakeChoice(self.messages.pop(0))])


def plan_message(subtasks):
    return FakeMessage(
        tool_calls=[
            FakeToolCall(
                FakeFunction(
                    "plan",
                    json.dumps({"subtasks": subtasks}),
                )
            )
        ]
    )


def text_message(content: str):
    return FakeMessage(content=content)


class FakePlanner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run_task(self, task, *, on_action=None):
        self.calls.append((task, on_action))
        return self.responses.pop(0)


def test_decompose_happy_path():
    client = FakeClient(
        plan_message(
            [
                {"step": 1, "task": "Open Discord #general", "success_condition": "#general is visible"},
                {"step": 2, "task": "Read the latest message", "success_condition": "latest message is known"},
            ]
        )
    )

    subtasks = _decompose_task("read Discord", client=client)

    assert subtasks == [
        Subtask(1, "Open Discord #general", "#general is visible"),
        Subtask(2, "Read the latest message", "latest message is known"),
    ]
    assert "Call the plan tool now" in client.calls[0]["messages"][1]["content"]
    assert client.calls[0]["tools"] == [PLAN_TOOL]
    assert client.calls[0]["tool_choice"] == {"type": "function", "function": {"name": "plan"}}


def test_decompose_uses_tool_call_arguments_not_message_content():
    client = FakeClient(
        FakeMessage(
            content="ignore this prose",
            tool_calls=[
                FakeToolCall(
                    FakeFunction(
                        "plan",
                        json.dumps(
                            {
                                "subtasks": [
                                    {
                                        "step": 1,
                                        "task": "Use the structured args",
                                        "success_condition": "structured args were used",
                                    }
                                ]
                            }
                        ),
                    )
                )
            ],
        )
    )

    subtasks = _decompose_task("do the thing", client=client)

    assert subtasks == [Subtask(1, "Use the structured args", "structured args were used")]


def test_decompose_falls_back_to_message_json_when_tool_call_missing():
    client = FakeClient(
        FakeMessage(
            content=json.dumps(
                {
                    "subtasks": [
                        {
                            "step": 1,
                            "task": "Use fallback JSON",
                            "success_condition": "fallback JSON was parsed",
                        }
                    ]
                }
            ),
            tool_calls=None,
        )
    )

    subtasks = _decompose_task("do the thing", client=client)

    assert subtasks == [Subtask(1, "Use fallback JSON", "fallback JSON was parsed")]


def test_decompose_malformed_text_falls_back_to_single_subtask():
    client = FakeClient(FakeMessage(content="I will just write prose.", tool_calls=None))

    subtasks = _decompose_task("do the thing", client=client)

    assert subtasks == [Subtask(1, "do the thing", "task is complete")]


def test_fsm_advances_on_done():
    client = FakeClient(
        plan_message(
            [
                {"step": 1, "task": "Read Discord", "success_condition": "message read"},
                {"step": 2, "task": "Write Notion", "success_condition": "summary written"},
            ]
        ),
        text_message("Discord message was read."),
        text_message("Notion summary was written."),
    )
    planner = FakePlanner([{"status": "done", "turns": 1}, {"status": "done", "turns": 2}])
    orchestrator = Orchestrator(
        conductor=object(),
        client=client,
        planner_factory=lambda conductor: planner,
    )

    result = orchestrator.run_task("summarize Discord in Notion")

    assert result["status"] == "done"
    assert result["steps"] == 2
    assert result["turns"] == 3
    assert len(planner.calls) == 2


def test_fsm_retries_on_stall():
    client = FakeClient(
        plan_message([{"step": 1, "task": "Navigate Discord", "success_condition": "channel visible"}]),
        text_message("Discord navigation completed."),
    )
    planner = FakePlanner(
        [
            {"status": "stalled", "turns": 1},
            {"status": "stalled", "turns": 1},
            {"status": "done", "turns": 1},
        ]
    )
    orchestrator = Orchestrator(
        conductor=object(),
        client=client,
        planner_factory=lambda conductor: planner,
    )

    result = orchestrator.run_task("go to Discord")

    assert result["status"] == "done"
    assert result["retries"] == 2
    assert len(planner.calls) == 3


def test_fsm_fails_after_max_retries():
    client = FakeClient(
        plan_message([{"step": 1, "task": "Navigate Discord", "success_condition": "channel visible"}])
    )
    planner = FakePlanner(
        [
            {"status": "stalled", "turns": 1},
            {"status": "stalled", "turns": 1},
            {"status": "stalled", "turns": 1},
        ]
    )
    orchestrator = Orchestrator(
        conductor=object(),
        client=client,
        planner_factory=lambda conductor: planner,
    )

    result = orchestrator.run_task("go to Discord")

    assert result == {
        "status": "failed",
        "step": 1,
        "subtask": "Navigate Discord",
        "success_condition": "channel visible",
        "attempts": 3,
        "last_planner_status": "stalled",
        "prior_context": "This is the first step.",
        "message": "Could not complete step 1/1: Navigate Discord. Tried 3x - last status: stalled.",
    }


def test_context_injection_passes_step_success_condition_and_prior_summary():
    client = FakeClient(
        plan_message(
            [
                {"step": 1, "task": "Read Discord", "success_condition": "message read"},
                {"step": 2, "task": "Write Notion", "success_condition": "summary written"},
            ]
        ),
        text_message("The Discord message says hello."),
        text_message("The Notion summary was written."),
    )
    planner = FakePlanner([{"status": "done", "turns": 1}, {"status": "done", "turns": 1}])
    orchestrator = Orchestrator(
        conductor=object(),
        client=client,
        planner_factory=lambda conductor: planner,
    )

    orchestrator.run_task("copy Discord to Notion")

    first_task = planner.calls[0][0]
    second_task = planner.calls[1][0]
    assert "[Step 1 of 2] Read Discord" in first_task
    assert "Success condition: message read" in first_task
    assert "Prior context: This is the first step." in first_task
    assert "[Step 2 of 2] Write Notion" in second_task
    assert "Success condition: summary written" in second_task
    assert "Prior context: The Discord message says hello." in second_task


def test_orchestrator_uses_groq_client_by_default(monkeypatch):
    class FakeGroqClient:
        model = "groq-model"

    monkeypatch.setattr("aria.conductor.orchestrator.GroqClient", FakeGroqClient)

    orchestrator = Orchestrator(conductor=object())

    assert isinstance(orchestrator.client, FakeGroqClient)
    assert orchestrator.model == "groq-model"


def test_orchestrator_falls_back_to_ollama_without_groq_key(monkeypatch):
    class FakeGroqClient:
        def __init__(self):
            raise KeyError("GROQ_API_KEY")

    class FakeOllamaClient:
        def __init__(self, model):
            self.model = model

    monkeypatch.setattr("aria.conductor.orchestrator.GroqClient", FakeGroqClient)
    monkeypatch.setattr("aria.conductor.orchestrator.OllamaChatClient", FakeOllamaClient)

    orchestrator = Orchestrator(conductor=object(), model="fallback-model")

    assert isinstance(orchestrator.client, FakeOllamaClient)
    assert orchestrator.client.model == "fallback-model"
