from aria.harness.planner import PlannedSubtask, validate_plan


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
