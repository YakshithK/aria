import json

from aria.harness.config import ModelConfig
from aria.harness.planner import (
    JsonTaskPlanner,
    PlannedSubtask,
    build_planner_messages,
    build_task_planner,
    validate_plan,
)


class Message:
    def __init__(self, content: str):
        self.content = content


class Choice:
    def __init__(self, content: str):
        self.message = Message(content)


class Response:
    def __init__(self, content: str):
        self.choices = [Choice(content)]


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return Response(self.content)


class SequenceClient:
    def __init__(self, contents: list[str]):
        self.contents = contents
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.contents) - 1)
        return Response(self.contents[index])


def test_validate_plan_rejects_empty_plan():
    result = validate_plan([])

    assert result.ok is False
    assert "empty" in result.reason


def test_validate_plan_rejects_too_many_subtasks():
    plan = [
        PlannedSubtask(
            title=f"Step {index}",
            instruction=f"Perform visible step {index}.",
            success_condition=f"Visible result {index} is shown.",
        )
        for index in range(3)
    ]

    result = validate_plan(plan, max_subtasks=2)

    assert result.ok is False
    assert "too many" in result.reason


def test_validate_plan_rejects_vague_subtasks():
    plan = [
        PlannedSubtask(
            title="Do task",
            instruction="Do everything",
            success_condition="done",
        )
    ]

    result = validate_plan(plan)

    assert result.ok is False
    assert result.invalid_index == 0
    assert "too vague" in result.reason


def test_validate_plan_rejects_multi_action_instruction():
    plan = [
        PlannedSubtask(
            title="Search web",
            instruction="Focus the search input and then type aria.",
            success_condition="The search input contains aria.",
        )
    ]

    result = validate_plan(plan)

    assert result.ok is False
    assert result.invalid_index == 0
    assert "one action" in result.reason


def test_validate_plan_rejects_too_short_fields():
    plan = [
        PlannedSubtask(
            title="Go",
            instruction="Click.",
            success_condition="Shown.",
        )
    ]

    result = validate_plan(plan)

    assert result.ok is False
    assert result.invalid_index == 0
    assert "too short" in result.reason


def test_validate_plan_rejects_then_chaining_variants():
    for instruction in (
        "Focus the search input then type aria.",
        "Focus the search input, then type aria.",
    ):
        plan = [
            PlannedSubtask(
                title="Search web",
                instruction=instruction,
                success_condition="The search input contains aria.",
            )
        ]

        result = validate_plan(plan)

        assert result.ok is False
        assert result.invalid_index == 0
        assert "one action" in result.reason


def test_validate_plan_accepts_observable_steps():
    plan = [
        PlannedSubtask(
            title="Focus search input",
            instruction="Focus the browser search or address input.",
            success_condition="A browser search or address input is focused.",
        ),
        PlannedSubtask(
            title="Type query",
            instruction="Type aria into the focused search input.",
            success_condition="The focused search input contains aria.",
        ),
    ]

    result = validate_plan(plan)

    assert result.ok is True
    assert result.reason == "plan accepted"


def test_build_planner_messages_requires_json_and_observable_subtasks():
    messages = build_planner_messages("search the web for aria", max_subtasks=3)

    text = str(messages)
    assert "Return exactly one JSON object" in text
    assert "subtasks" in text
    assert "observable success_condition" in text
    assert "Do not execute" in text
    assert "max 3 subtasks" in text


def test_json_task_planner_parses_valid_plan_and_uses_model():
    client = FakeClient(
        json.dumps(
            {
                "subtasks": [
                    {
                        "title": "Focus search input",
                        "instruction": "Focus the browser search or address input.",
                        "success_condition": "A browser search or address input is focused.",
                    }
                ]
            }
        )
    )
    planner = JsonTaskPlanner(client=client, model="planner-model")

    result = planner.plan("search the web for aria", max_subtasks=3)

    assert result.goal == "search the web for aria"
    assert result.subtasks[0].title == "Focus search input"
    assert client.calls[0]["model"] == "planner-model"
    assert client.calls[0]["temperature"] == 0


def test_build_task_planner_uses_configured_model():
    client = FakeClient(
        json.dumps(
            {
                "subtasks": [
                    {
                        "title": "Focus search input",
                        "instruction": "Focus the browser search or address input.",
                        "success_condition": "A browser search or address input is focused.",
                    }
                ]
            }
        )
    )
    planner = build_task_planner(
        client=client,
        config=ModelConfig(provider="hackclub", model="planner-model"),
    )

    planner.plan("search", max_subtasks=2)

    assert client.calls[0]["model"] == "planner-model"


def test_json_task_planner_returns_empty_plan_for_malformed_response():
    planner = JsonTaskPlanner(client=FakeClient("not json"), model="planner-model")

    result = planner.plan("search", max_subtasks=3)

    assert result.goal == "search"
    assert result.subtasks == []


def test_json_task_planner_repairs_malformed_plan_response():
    client = SequenceClient(
        [
            "not json",
            json.dumps(
                {
                    "subtasks": [
                        {
                            "title": "Focus search input",
                            "instruction": "Focus the browser search or address input.",
                            "success_condition": (
                                "A browser search or address input is focused."
                            ),
                        }
                    ]
                }
            ),
        ]
    )
    planner = JsonTaskPlanner(client=client, model="planner-model")

    result = planner.plan("search the web for aria", max_subtasks=3)

    assert len(client.calls) == 2
    assert result.subtasks[0].title == "Focus search input"
    assert planner.last_error is None
    repair_messages = str(client.calls[1]["messages"])
    assert "valid JSON" in repair_messages
    assert "success_condition" in repair_messages


def test_json_task_planner_normalizes_extra_trailing_brace_and_missing_success():
    client = FakeClient(
        (
            '{"subtasks": [{"title": "Focus search input", '
            '"instruction": "Click on the browser search input."}]}}'
        )
    )
    planner = JsonTaskPlanner(client=client, model="planner-model")

    result = planner.plan("search the web for aria", max_subtasks=3)

    assert len(client.calls) == 1
    assert result.subtasks[0].title == "Focus search input"
    assert result.subtasks[0].success_condition == "Focus search input is visible."
    assert planner.last_error is None


def test_json_task_planner_returns_empty_plan_when_repair_fails():
    client = SequenceClient(["not json", '{"subtasks": "still wrong"}'])
    planner = JsonTaskPlanner(client=client, model="planner-model")

    result = planner.plan("search", max_subtasks=3)

    assert len(client.calls) == 2
    assert result.subtasks == []
    assert planner.last_error is not None
    assert "after repair" in planner.last_error


def test_json_task_planner_records_failure_diagnostics_for_malformed_response():
    planner = JsonTaskPlanner(client=FakeClient("not json"), model="planner-model")

    planner.plan("search", max_subtasks=3)

    assert planner.last_error is not None
    assert "json" in planner.last_error.lower()
    assert planner.last_response_content == "not json"
