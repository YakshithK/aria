from dataclasses import dataclass

from aria.conductor.orchestrator import Orchestrator, Subtask, _decompose_task


@dataclass
class FakeMessage:
    content: str


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list[FakeChoice]


class FakeClient:
    def __init__(self, *contents: str):
        self.contents = list(contents)
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse([FakeChoice(FakeMessage(self.contents.pop(0)))])


class FakePlanner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run_task(self, task, *, on_action=None):
        self.calls.append((task, on_action))
        return self.responses.pop(0)


def test_decompose_happy_path():
    client = FakeClient(
        """
        [
          {"step": 1, "task": "Open Discord #general", "success_condition": "#general is visible"},
          {"step": 2, "task": "Read the latest message", "success_condition": "latest message is known"}
        ]
        """
    )

    subtasks = _decompose_task("read Discord", client=client)

    assert subtasks == [
        Subtask(1, "Open Discord #general", "#general is visible"),
        Subtask(2, "Read the latest message", "latest message is known"),
    ]
    assert "Break the following task into sequential subtasks" in client.calls[0]["messages"][0]["content"]


def test_decompose_malformed_json_falls_back_to_single_subtask():
    client = FakeClient("not json")

    subtasks = _decompose_task("do the thing", client=client)

    assert subtasks == [Subtask(1, "do the thing", "task is complete")]


def test_fsm_advances_on_done():
    client = FakeClient(
        """
        [
          {"step": 1, "task": "Read Discord", "success_condition": "message read"},
          {"step": 2, "task": "Write Notion", "success_condition": "summary written"}
        ]
        """,
        "Discord message was read.",
        "Notion summary was written.",
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
        '[{"step": 1, "task": "Navigate Discord", "success_condition": "channel visible"}]',
        "Discord navigation completed.",
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
        '[{"step": 1, "task": "Navigate Discord", "success_condition": "channel visible"}]'
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
        """
        [
          {"step": 1, "task": "Read Discord", "success_condition": "message read"},
          {"step": 2, "task": "Write Notion", "success_condition": "summary written"}
        ]
        """,
        "The Discord message says hello.",
        "The Notion summary was written.",
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
