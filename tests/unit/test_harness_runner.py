from aria.harness.models import ActionProposal, Candidate, ObservationBundle, VerificationResult
from aria.harness.runner import run_subtask


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


def click_search(confidence: float = 0.8) -> ActionProposal:
    return ActionProposal(
        type="click_element",
        candidate_id="candidate_1",
        confidence=confidence,
        evidence="Search is visible.",
    )


def verification(status: str) -> VerificationResult:
    return VerificationResult(status=status, confidence=0.8, evidence=f"{status} evidence")


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
