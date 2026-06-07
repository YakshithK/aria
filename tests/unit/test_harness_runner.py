from aria.harness.models import ActionProposal, Candidate, ObservationBundle, VerificationResult
from aria.harness.runner import preview_turn, run_approved_turn, run_subtask


def make_bundle(turn: int = 1) -> ObservationBundle:
    return ObservationBundle(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        screenshot_path=f"/tmp/screen-{turn}.png",
        screen_size=(1280, 720),
        focused_window=None,
        windows=[],
        candidates=[
            Candidate(
                id="candidate_1",
                backend_id="cdp:notion:abc:nodeId_12",
                source="cdp_ax",
                role="button",
                label="Search",
                bounds=(20, 48, 120, 32),
                bounds_space="screen",
                actions=["click_element"],
                confidence=0.9,
                visible=True,
                window_id=None,
            )
        ],
        recent_actions=[],
        turn=turn,
    )


class FakeObserver:
    def __init__(self):
        self.turn = 0

    def observe(self, *, goal: str, subtask: str, success_condition: str, recent_actions):
        self.turn += 1
        return make_bundle(self.turn).model_copy(
            update={
                "goal": goal,
                "subtask": subtask,
                "success_condition": success_condition,
                "recent_actions": recent_actions,
            }
        )


class FakeActor:
    def __init__(self, *proposals: ActionProposal):
        self.proposals = list(proposals)

    def propose(self, observation: ObservationBundle) -> ActionProposal:
        return self.proposals.pop(0)


class FakeVerifier:
    def __init__(self, *results: VerificationResult):
        self.results = list(results)

    def verify(self, *, before, after, action, execution):
        return self.results.pop(0)


class FakeExecutor:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.actions = []

    def execute(self, proposal, validation, observation):
        self.actions.append(proposal)
        return {"ok": self.ok, "route": validation.execution_route, "raw_result": {"ok": self.ok}}


class PreviewObserver:
    def __init__(self, observation):
        self.observation = observation
        self.calls = []

    def observe(self, *, goal, subtask, success_condition, recent_actions):
        self.calls.append(
            {
                "goal": goal,
                "subtask": subtask,
                "success_condition": success_condition,
                "recent_actions": recent_actions,
            }
        )
        return self.observation


class PreviewActor:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    def propose(self, observation):
        self.calls.append(observation)
        return self.proposal


class RecordingExecutor:
    def __init__(self, result=None):
        self.result = result or {"ok": True, "route": "wait", "raw_result": {"ok": True}}
        self.calls = []

    def execute(self, proposal, validation, observation):
        self.calls.append((proposal, validation, observation))
        return self.result


class RaisingExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, proposal, validation, observation):
        self.calls.append((proposal, validation, observation))
        raise RuntimeError("backend crashed")


class FakeVisualDebugger:
    def __init__(self):
        self.actor_calls = []
        self.marker_calls = []

    def prepare_actor_image(self, *, screenshot_path, screenshot_bytes):
        self.actor_calls.append((screenshot_path, screenshot_bytes))
        from aria.harness.visual_debug import VisualArtifacts

        return VisualArtifacts(actor_image_path="/tmp/actor-grid.png")

    def save_click_marker(self, *, screenshot_path, screenshot_bytes, x, y):
        self.marker_calls.append((screenshot_path, screenshot_bytes, x, y))
        return "/tmp/proposal-click.png"


def preview_observation():
    return ObservationBundle(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        screenshot_path="/tmp/screen.png",
        screen_size=(800, 600),
        focused_window=None,
        windows=[],
        candidates=[],
        recent_actions=[],
        turn=1,
    )


def click_search(confidence: float = 0.8) -> ActionProposal:
    return ActionProposal(
        type="click_element",
        candidate_id="candidate_1",
        confidence=confidence,
        evidence="Search is visible.",
    )


def verification(status: str) -> VerificationResult:
    return VerificationResult(status=status, confidence=0.8, evidence=f"{status} evidence")


def test_preview_turn_observes_proposes_and_validates_without_execution():
    observation = preview_observation()
    observer = PreviewObserver(observation)
    actor = PreviewActor(
        ActionProposal(
            type="wait",
            seconds=1,
            reason="loading",
            confidence=0.8,
            evidence="screen is visible",
        )
    )

    result = preview_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=observer,
        actor=actor,
    )

    assert result.observation == observation
    assert result.proposal.type == "wait"
    assert result.validation.ok is True
    assert observer.calls == [
        {
            "goal": "Search",
            "subtask": "Find input",
            "success_condition": "input visible",
            "recent_actions": [],
        }
    ]
    assert actor.calls == [observation]


def test_preview_turn_returns_validation_failure_for_bad_action():
    observation = preview_observation()
    observer = PreviewObserver(observation)
    actor = PreviewActor(
        ActionProposal(
            type="click",
            x=9999,
            y=9999,
            confidence=0.8,
            evidence="outside",
        )
    )

    result = preview_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=observer,
        actor=actor,
    )

    assert result.validation.ok is False
    assert "outside screen bounds" in result.validation.reason


def test_preview_turn_attaches_visual_artifacts_for_raw_click():
    observation = preview_observation()
    actor = PreviewActor(ActionProposal(type="click", x=100, y=50, confidence=0.8, evidence="target"))
    visual_debugger = FakeVisualDebugger()

    result = preview_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=PreviewObserver(observation),
        actor=actor,
        visual_debugger=visual_debugger,
        screenshot_bytes=b"png",
    )

    assert result.actor_image_path == "/tmp/actor-grid.png"
    assert result.proposal_debug_image_path == "/tmp/proposal-click.png"
    assert visual_debugger.actor_calls == [("/tmp/screen.png", b"png")]
    assert visual_debugger.marker_calls == [("/tmp/screen.png", b"png", 100, 50)]


def test_preview_turn_does_not_save_click_marker_for_wait_action():
    observation = preview_observation()
    actor = PreviewActor(ActionProposal(type="wait", seconds=1, reason="loading", confidence=0.8, evidence="loading"))
    visual_debugger = FakeVisualDebugger()

    result = preview_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=PreviewObserver(observation),
        actor=actor,
        visual_debugger=visual_debugger,
        screenshot_bytes=b"png",
    )

    assert result.actor_image_path == "/tmp/actor-grid.png"
    assert result.proposal_debug_image_path is None
    assert visual_debugger.marker_calls == []


def test_approved_turn_does_not_execute_when_validation_fails():
    observation = preview_observation()
    observer = PreviewObserver(observation)
    actor = PreviewActor(
        ActionProposal(
            type="click",
            x=9999,
            y=9999,
            confidence=0.8,
            evidence="outside",
        )
    )
    executor = RecordingExecutor()

    result = run_approved_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=observer,
        actor=actor,
        executor=executor,
        approve=lambda preview: True,
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert "outside screen bounds" in result["error"]
    assert result["execution"] is None
    assert executor.calls == []


def test_approved_turn_does_not_execute_when_approval_denies():
    observation = preview_observation()
    observer = PreviewObserver(observation)
    actor = PreviewActor(
        ActionProposal(
            type="wait",
            seconds=1,
            reason="loading",
            confidence=0.8,
            evidence="screen is visible",
        )
    )
    executor = RecordingExecutor()

    result = run_approved_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=observer,
        actor=actor,
        executor=executor,
        approve=lambda preview: False,
    )

    assert result["ok"] is False
    assert result["status"] == "denied"
    assert result["error"] == "action not approved"
    assert result["execution"] is None
    assert executor.calls == []


def test_approved_turn_executes_once_when_approved():
    observation = preview_observation()
    observer = PreviewObserver(observation)
    actor = PreviewActor(
        ActionProposal(
            type="wait",
            seconds=1,
            reason="loading",
            confidence=0.8,
            evidence="screen is visible",
        )
    )
    executor = RecordingExecutor({"ok": True, "route": "wait", "raw_result": {"ok": True}})

    result = run_approved_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=observer,
        actor=actor,
        executor=executor,
        approve=lambda preview: True,
    )

    assert result["ok"] is True
    assert result["status"] == "executed"
    assert result["error"] is None
    assert result["execution"]["ok"] is True
    assert len(executor.calls) == 1


def test_approved_turn_reports_executor_failure():
    observation = preview_observation()
    observer = PreviewObserver(observation)
    actor = PreviewActor(
        ActionProposal(
            type="wait",
            seconds=1,
            reason="loading",
            confidence=0.8,
            evidence="screen is visible",
        )
    )
    executor = RecordingExecutor({"ok": False, "error": "executor unavailable"})

    result = run_approved_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=observer,
        actor=actor,
        executor=executor,
        approve=lambda preview: True,
    )

    assert result["ok"] is False
    assert result["status"] == "execution_failed"
    assert result["error"] == "executor unavailable"
    assert result["execution"]["ok"] is False


def test_approved_turn_normalizes_executor_exceptions():
    observation = preview_observation()
    observer = PreviewObserver(observation)
    actor = PreviewActor(
        ActionProposal(
            type="wait",
            seconds=1,
            reason="loading",
            confidence=0.8,
            evidence="screen is visible",
        )
    )
    executor = RaisingExecutor()

    result = run_approved_turn(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=observer,
        actor=actor,
        executor=executor,
        approve=lambda preview: True,
    )

    assert result["ok"] is False
    assert result["status"] == "execution_failed"
    assert result["error"] == "backend crashed"
    assert result["execution"] == {"ok": False, "error": "backend crashed"}
    assert len(executor.calls) == 1


def test_runner_completes_when_verifier_returns_complete():
    result = run_subtask(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        observer=FakeObserver(),
        actor=FakeActor(click_search()),
        verifier=FakeVerifier(verification("complete")),
        executor=FakeExecutor(),
    )

    assert result.status == "complete"
    assert result.turns == 1
    assert result.verification.status == "complete"


def test_runner_retries_after_incomplete_verification():
    executor = FakeExecutor()

    result = run_subtask(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        observer=FakeObserver(),
        actor=FakeActor(click_search(), click_search()),
        verifier=FakeVerifier(verification("incomplete"), verification("complete")),
        executor=executor,
    )

    assert result.status == "complete"
    assert result.turns == 2
    assert len(executor.actions) == 2


def test_runner_requests_approval_for_each_turn():
    approvals = []

    result = run_subtask(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        observer=FakeObserver(),
        actor=FakeActor(click_search(), click_search()),
        verifier=FakeVerifier(verification("incomplete"), verification("complete")),
        executor=FakeExecutor(),
        approve=lambda preview: approvals.append(preview.proposal.type) or True,
    )

    assert result.status == "complete"
    assert approvals == ["click_element", "click_element"]


def test_runner_fails_when_validator_rejects_action():
    result = run_subtask(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        observer=FakeObserver(),
        actor=FakeActor(click_search(confidence=0.2)),
        verifier=FakeVerifier(),
        executor=FakeExecutor(),
    )

    assert result.status == "failed"
    assert "confidence" in result.message.lower()


def test_runner_does_not_execute_when_approval_denies():
    executor = FakeExecutor()
    previews = []

    result = run_subtask(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        observer=FakeObserver(),
        actor=FakeActor(click_search()),
        verifier=FakeVerifier(),
        executor=executor,
        approve=lambda preview: previews.append(preview) or False,
    )

    assert result.status == "failed"
    assert result.turns == 1
    assert result.message == "action not approved"
    assert executor.actions == []
    assert len(previews) == 1
    assert result.action_trace[0]["approved"] is False
    assert result.action_trace[0]["execution"] is None


def test_runner_stops_on_actor_fail_without_approval_or_execution():
    executor = FakeExecutor()
    records = []

    result = run_subtask(
        goal="Search",
        subtask="Find input",
        success_condition="input focused",
        observer=FakeObserver(),
        actor=FakeActor(
            ActionProposal(
                type="fail",
                confidence=1.0,
                evidence="VLM actor returned invalid action JSON",
                reason="invalid_vlm_action",
            )
        ),
        verifier=FakeVerifier(),
        executor=executor,
        trace_writer=records.append,
        approve=lambda preview: (_ for _ in ()).throw(AssertionError("fail should not ask approval")),
    )

    assert result.status == "failed"
    assert result.turns == 1
    assert result.message == "VLM actor returned invalid action JSON"
    assert executor.actions == []
    assert records[0]["proposal"]["type"] == "fail"
    assert records[0]["approved"] is None
    assert records[0]["execution"] is None


def test_runner_fails_after_max_turns():
    result = run_subtask(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        observer=FakeObserver(),
        actor=FakeActor(click_search(), click_search()),
        verifier=FakeVerifier(verification("incomplete"), verification("incomplete")),
        executor=FakeExecutor(),
        max_turns=2,
    )

    assert result.status == "max_turns"
    assert result.turns == 2


def test_runner_trace_records_candidates_and_after_screenshot():
    records = []

    run_subtask(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        observer=FakeObserver(),
        actor=FakeActor(click_search()),
        verifier=FakeVerifier(verification("complete")),
        executor=FakeExecutor(),
        trace_writer=records.append,
    )

    assert records[0]["before_screenshot_path"] == "/tmp/screen-1.png"
    assert records[0]["after_screenshot_path"] == "/tmp/screen-2.png"
    assert records[0]["candidates"][0]["id"] == "candidate_1"


def test_runner_trace_records_visual_artifacts_for_raw_click():
    records = []
    visual_debugger = FakeVisualDebugger()

    result = run_subtask(
        goal="Search",
        subtask="Find input",
        success_condition="input visible",
        observer=PreviewObserver(preview_observation()),
        actor=FakeActor(ActionProposal(type="click", x=100, y=50, confidence=0.8, evidence="target")),
        verifier=FakeVerifier(verification("complete")),
        executor=FakeExecutor(),
        trace_writer=records.append,
        approve=lambda preview: True,
        visual_debugger=visual_debugger,
        screenshot_bytes_loader=lambda path: b"png",
    )

    assert result.status == "complete"
    assert records[0]["actor_image_path"] == "/tmp/actor-grid.png"
    assert records[0]["proposal_debug_image_path"] == "/tmp/proposal-click.png"
