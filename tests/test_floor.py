"""Opt-in speaking queue and floor lifecycle (``indubio.core.floor``).

Synthetic actors only; the floor rules are an unvalidated demonstrator, not StPO/GVG.
"""

import json

import pytest
from pydantic import ValidationError

from indubio.core.engine import SimulationEngine
from indubio.core.floor import FloorState, derive_floor
from indubio.core.models import (
    AdvanceFloor,
    FileMotion,
    Mode,
    MovePhase,
    Phase,
    Proposal,
    ReleaseFloor,
    RequestFloor,
    SimulationConfig,
    Speak,
    TrialEvent,
    WithdrawFloorRequest,
)
from indubio.core.projection import build_projection
from indubio.jurisdictions.base import RuleContext
from indubio.jurisdictions.demo import DEMO_METADATA, DemoRuleset
from indubio.jurisdictions.demo.floor import (
    DEMO_FLOOR_METADATA,
    DEMO_FLOOR_RULESET_ID,
    DemoFloorRuleset,
)
from indubio.jurisdictions.registry import get_floor_ruleset
from indubio.persistence.sqlite import EventStore
from indubio.scenarios import (
    RestoreError,
    build_engine,
    load_bundled_manifest,
    restore_engine,
    restore_from_store,
)
from indubio.scenarios.demo import FLOOR_DEMO_SCRIPT, SCENARIO_DEMO_SCRIPT, run_floor_demo
from indubio.scenarios.restore import EVENT_METADATA_KEYS, FLOOR_METADATA_KEYS

ALL_MODES = list(Mode)
VIEWERS = ["judge", "pros", "def", "acc", "wit", "obs"]
QUEUERS = ["pros", "def", "acc", "wit"]
FLOOR_ACTIONS = [RequestFloor(), WithdrawFloorRequest(), ReleaseFloor(), AdvanceFloor()]


def floor_engine(mode: Mode = Mode.STRICT) -> SimulationEngine:
    return build_engine(load_bundled_manifest(), mode, floor_rules=DEMO_FLOOR_RULESET_ID)


def p(actor_id, action) -> Proposal:
    return Proposal(actor_id=actor_id, action=action)


def rules(event):
    return [finding.rule_id for finding in event.findings]


def run(engine, *proposals):
    return [engine.propose(proposal) for proposal in proposals]


# --- Opt-in: unscheduled engines are unchanged -------------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("action", FLOOR_ACTIONS, ids=lambda a: a.kind)
def test_floor_actions_without_floor_control_are_rejected_in_every_mode(mode, action):
    engine = build_engine(load_bundled_manifest(), mode)
    actor_id = "judge" if isinstance(action, AdvanceFloor) else "pros"
    event = engine.propose(p(actor_id, action))
    assert not event.accepted
    assert [(f.rule_id, f.severity) for f in event.findings] == [("FLOOR_DISABLED", "security")]
    assert engine.floor is None
    assert set(event.metadata) == EVENT_METADATA_KEYS


@pytest.mark.parametrize("mode", ALL_MODES)
def test_unscheduled_speech_and_metadata_unchanged(mode):
    engine = build_engine(load_bundled_manifest(), mode)
    event = engine.propose(p("def", Speak(text="Synthetic")))
    assert event.accepted and event.findings == []
    assert set(event.metadata) == EVENT_METADATA_KEYS
    dumped = json.loads(engine.perspective("def").model_dump_json())
    assert "floor" not in dumped
    assert engine.perspective("def").floor is None


def test_default_ruleset_metadata_is_unchanged():
    assert (DEMO_METADATA.ruleset_id, DEMO_METADATA.version) == (
        "de-criminal-demo-unvalidated", "0.2.0-demo"
    )
    assert DEMO_FLOOR_METADATA.validation_status == "unvalidated_demonstrator"


def test_floor_metadata_recorded_on_every_event():
    engine = run_floor_demo(Mode.STRICT)
    for event in engine.events:
        assert set(event.metadata) == EVENT_METADATA_KEYS | FLOOR_METADATA_KEYS
        assert event.metadata["floor_semantics"] == "indubio.floor/1"
        assert event.metadata["floor_rules"] == DEMO_FLOOR_RULESET_ID
        assert event.metadata["floor_rules_version"] == DEMO_FLOOR_METADATA.version


# --- Configuration validation ------------------------------------------------------------

def test_floor_rules_must_be_a_ruleset():
    with pytest.raises(TypeError):
        SimulationEngine([], floor_rules=object())  # type: ignore[arg-type]


def test_floor_rules_cannot_be_the_jurisdiction_pack():
    with pytest.raises(ValueError):
        SimulationEngine([], floor_rules=DemoRuleset())


def test_unknown_floor_rules_fail_closed():
    with pytest.raises(ValueError, match="Unknown floor ruleset"):
        build_engine(load_bundled_manifest(), floor_rules="no-such-floor")
    with pytest.raises(ValueError):
        get_floor_ruleset("de-criminal-demo-unvalidated")  # separate namespace
    with pytest.raises(TypeError):
        build_engine(load_bundled_manifest(), floor_rules=DemoFloorRuleset())  # type: ignore


def test_floor_control_is_fixed_at_construction_not_in_config():
    engine = floor_engine()
    assert "floor" not in SimulationConfig.model_fields
    assert engine.floor == FloorState()


# --- FIFO, duplicates, withdraw, release, advance ----------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
def test_fifo_order_and_advance(mode):
    engine = floor_engine(mode)
    run(engine, p("wit", RequestFloor()), p("pros", RequestFloor()), p("acc", RequestFloor()))
    assert engine.floor == FloorState(queue=("wit", "pros", "acc"))
    engine.propose(p("judge", AdvanceFloor()))
    assert engine.floor == FloorState(holder="wit", queue=("pros", "acc"))
    # Advancing replaces the current holder with the next in line.
    engine.propose(p("judge", AdvanceFloor()))
    assert engine.floor == FloorState(holder="pros", queue=("acc",))


@pytest.mark.parametrize("mode", ALL_MODES)
def test_withdraw_from_middle_preserves_order(mode):
    engine = floor_engine(mode)
    run(engine, *(p(a, RequestFloor()) for a in ["pros", "def", "wit"]))
    event = engine.propose(p("def", WithdrawFloorRequest()))
    assert event.accepted
    assert engine.floor == FloorState(queue=("pros", "wit"))
    # Re-requesting after withdrawal goes to the end of the line.
    engine.propose(p("def", RequestFloor()))
    assert engine.floor == FloorState(queue=("pros", "wit", "def"))


@pytest.mark.parametrize("mode", ALL_MODES)
def test_duplicate_request_rejected_in_every_mode(mode):
    engine = floor_engine(mode)
    run(engine, p("pros", RequestFloor()), p("def", RequestFloor()))
    queued_dup = engine.propose(p("pros", RequestFloor()))
    assert not queued_dup.accepted and rules(queued_dup) == ["FLOOR_DUPLICATE_REQUEST"]
    engine.propose(p("judge", AdvanceFloor()))
    holder_dup = engine.propose(p("pros", RequestFloor()))
    assert not holder_dup.accepted and rules(holder_dup) == ["FLOOR_DUPLICATE_REQUEST"]
    assert engine.floor == FloorState(holder="pros", queue=("def",))


@pytest.mark.parametrize("mode", ALL_MODES)
def test_structural_reject_paths(mode):
    engine = floor_engine(mode)
    not_queued = engine.propose(p("def", WithdrawFloorRequest()))
    empty = engine.propose(p("judge", AdvanceFloor()))
    no_holder = engine.propose(p("def", ReleaseFloor()))
    assert [rules(e) for e in (not_queued, empty, no_holder)] == [
        ["FLOOR_NOT_QUEUED"], ["FLOOR_QUEUE_EMPTY"], ["FLOOR_NOT_HOLDER"]
    ]
    run(engine, p("pros", RequestFloor()), p("judge", AdvanceFloor()))
    # Someone else cannot release the holder's floor; the holder cannot withdraw it.
    other = engine.propose(p("def", ReleaseFloor()))
    holder_withdraw = engine.propose(p("pros", WithdrawFloorRequest()))
    empty_with_holder = engine.propose(p("judge", AdvanceFloor()))
    assert [rules(e) for e in (other, holder_withdraw, empty_with_holder)] == [
        ["FLOOR_NOT_HOLDER"], ["FLOOR_NOT_QUEUED"], ["FLOOR_QUEUE_EMPTY"]
    ]
    assert not any(e.accepted for e in (other, holder_withdraw, empty_with_holder))
    assert engine.floor == FloorState(holder="pros")


@pytest.mark.parametrize("mode", ALL_MODES)
def test_release_keeps_queue_and_grants_nobody(mode):
    engine = floor_engine(mode)
    run(engine, p("pros", RequestFloor()), p("def", RequestFloor()),
        p("judge", AdvanceFloor()))
    event = engine.propose(p("pros", ReleaseFloor()))
    assert event.accepted
    assert engine.floor == FloorState(queue=("def",))


# --- Roles -------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("actor_id", VIEWERS)
def test_role_matrix_with_floor_control(mode, actor_id):
    allowed_queue = actor_id in QUEUERS
    # request
    engine = floor_engine(mode)
    event = engine.propose(p(actor_id, RequestFloor()))
    assert event.accepted == allowed_queue
    if not allowed_queue:
        assert rules(event)[0] == "AUTH_FLOOR_REQUEST"
        assert engine.floor == FloorState()
        return
    # withdraw (queued), then release (holding)
    assert engine.propose(p(actor_id, WithdrawFloorRequest())).accepted
    run(engine, p(actor_id, RequestFloor()), p("judge", AdvanceFloor()))
    assert engine.floor.holder == actor_id
    assert engine.propose(p(actor_id, ReleaseFloor())).accepted


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("actor_id", ["judge", "obs"])
def test_judge_and_observer_never_queue_withdraw_or_release(mode, actor_id):
    engine = floor_engine(mode)
    for action, rule in [(WithdrawFloorRequest(), "AUTH_FLOOR_WITHDRAW"),
                         (ReleaseFloor(), "AUTH_FLOOR_RELEASE")]:
        event = engine.propose(p(actor_id, action))
        assert not event.accepted and rules(event)[0] == rule


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("actor_id", ["pros", "def", "acc", "wit", "obs"])
def test_only_judge_advances(mode, actor_id):
    engine = floor_engine(mode)
    engine.propose(p("def" if actor_id != "def" else "pros", RequestFloor()))
    before = engine.floor
    event = engine.propose(p(actor_id, AdvanceFloor()))
    assert not event.accepted and rules(event) == ["AUTH_FLOOR_ADVANCE"]
    assert engine.floor == before


# --- Procedural rules (versioned floor ruleset) ------------------------------------------

def test_speak_without_floor_strict_rejects():
    engine = floor_engine(Mode.STRICT)
    event = engine.propose(p("def", Speak(text="Synthetic")))
    assert not event.accepted
    assert [(f.rule_id, f.severity) for f in event.findings] == [
        ("DEMO_FLOOR_SPEAK", "procedural")
    ]


@pytest.mark.parametrize("mode", [Mode.REALISTIC, Mode.EXPERIMENTAL])
def test_speak_without_floor_realistic_records_but_grants_nothing(mode):
    engine = floor_engine(mode)
    engine.propose(p("pros", RequestFloor()))
    event = engine.propose(p("def", Speak(text="Synthetic")))
    assert event.accepted and rules(event) == ["DEMO_FLOOR_SPEAK"]
    assert engine.floor == FloorState(queue=("pros",))
    # Findings on accepted events are audit data, not projected to anyone.
    for viewer in VIEWERS:
        assert engine.perspective(viewer).events[-1].findings == ()


@pytest.mark.parametrize("mode", ALL_MODES)
def test_judge_and_holder_speak_cleanly(mode):
    engine = floor_engine(mode)
    assert engine.propose(p("judge", Speak(text="Synthetic"))).findings == []
    run(engine, p("wit", RequestFloor()), p("judge", AdvanceFloor()))
    event = engine.propose(p("wit", Speak(text="Synthetic")))
    assert event.accepted and event.findings == []
    assert engine.floor == FloorState(holder="wit")  # speech does not consume the floor


def _to_finished(engine):
    for phase in [Phase.EVIDENCE, Phase.CLOSING, Phase.JUDGMENT, Phase.FINISHED]:
        assert engine.propose(p("judge", MovePhase(destination=phase))).accepted


def test_floor_activity_after_finish_strict():
    engine = floor_engine(Mode.STRICT)
    _to_finished(engine)
    event = engine.propose(p("pros", RequestFloor()))
    assert not event.accepted and rules(event) == ["DEMO_FLOOR_FINISHED"]
    assert engine.floor == FloorState()


def test_floor_activity_after_finish_realistic():
    engine = floor_engine(Mode.REALISTIC)
    _to_finished(engine)
    request = engine.propose(p("pros", RequestFloor()))
    advance = engine.propose(p("judge", AdvanceFloor()))
    assert request.accepted and rules(request) == ["DEMO_FLOOR_FINISHED"]
    assert advance.accepted and rules(advance) == ["DEMO_FLOOR_FINISHED"]
    assert engine.floor == FloorState(holder="pros")


def test_structural_finding_precedes_procedural():
    engine = floor_engine(Mode.REALISTIC)
    _to_finished(engine)
    event = engine.propose(p("judge", AdvanceFloor()))
    assert not event.accepted
    assert rules(event) == ["FLOOR_QUEUE_EMPTY", "DEMO_FLOOR_FINISHED"]


def test_floor_ruleset_sees_frozen_context():
    seen: list[RuleContext] = []

    class Capturing(DemoFloorRuleset):
        def evaluate(self, context, action):
            seen.append(context)
            return super().evaluate(context, action)

    manifest = load_bundled_manifest()
    engine = SimulationEngine(
        manifest.actors, SimulationConfig(jurisdiction=manifest.jurisdiction),
        evidence=manifest.registry(), floor_rules=Capturing(),
    )
    run(engine, p("pros", RequestFloor()), p("judge", AdvanceFloor()),
        p("pros", Speak(text="Synthetic")))
    assert [(c.floor_enabled, c.actor_holds_floor) for c in seen] == [
        (True, False), (True, False), (True, True)
    ]
    with pytest.raises(ValidationError):
        seen[0].actor_holds_floor = False  # type: ignore[misc]


def test_floor_ruleset_cannot_return_security_findings():
    from indubio.core.models import RuleFinding

    class Bad(DemoFloorRuleset):
        def evaluate(self, context, action):
            return [RuleFinding(rule_id="X", description="x", severity="security")]

    manifest = load_bundled_manifest()
    engine = SimulationEngine(
        manifest.actors, SimulationConfig(jurisdiction=manifest.jurisdiction),
        evidence=manifest.registry(), floor_rules=Bad(),
    )
    with pytest.raises(TypeError):
        engine.propose(p("pros", RequestFloor()))
    assert engine.events == [] and engine.floor == FloorState()


def test_failure_before_commit_leaves_floor_and_history_unchanged():
    class Exploding(DemoFloorRuleset):
        armed = False

        def evaluate(self, context, action):
            if self.armed:
                raise RuntimeError("synthetic failure")
            return super().evaluate(context, action)

    rules_pack = Exploding()
    manifest = load_bundled_manifest()
    engine = SimulationEngine(
        manifest.actors, SimulationConfig(jurisdiction=manifest.jurisdiction),
        evidence=manifest.registry(), floor_rules=rules_pack,
    )
    engine.propose(p("pros", RequestFloor()))
    rules_pack.armed = True
    with pytest.raises(RuntimeError):
        engine.propose(p("judge", AdvanceFloor()))
    assert engine.floor == FloorState(queue=("pros",))
    assert len(engine.events) == 1


# --- Phase boundaries --------------------------------------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
def test_phase_boundary_clears_holder_and_queue(mode):
    engine = floor_engine(mode)
    run(engine, p("pros", RequestFloor()), p("def", RequestFloor()),
        p("judge", AdvanceFloor()))
    engine.propose(p("judge", MovePhase(destination=Phase.EVIDENCE)))
    assert engine.floor == FloorState()
    event = engine.propose(p("def", WithdrawFloorRequest()))
    assert not event.accepted and rules(event) == ["FLOOR_NOT_QUEUED"]


@pytest.mark.parametrize("mode", ALL_MODES)
def test_rejected_phase_move_does_not_clear(mode):
    engine = floor_engine(mode)
    engine.propose(p("pros", RequestFloor()))
    event = engine.propose(p("wit", MovePhase(destination=Phase.EVIDENCE)))
    assert not event.accepted
    assert engine.floor == FloorState(queue=("pros",))


def test_accepted_move_to_same_phase_is_not_a_boundary():
    engine = floor_engine(Mode.REALISTIC)
    engine.propose(p("pros", RequestFloor()))
    event = engine.propose(p("judge", MovePhase(destination=Phase.OPENING)))
    assert event.accepted and event.phase_before == event.phase_after
    assert engine.floor == FloorState(queue=("pros",))


def test_other_accepted_actions_do_not_change_floor():
    engine = floor_engine(Mode.STRICT)
    engine.propose(p("pros", RequestFloor()))
    engine.propose(p("def", FileMotion(motion_id="m1", grounds="Synthetic")))
    assert engine.floor == FloorState(queue=("pros",))


# --- Projection --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [Mode.STRICT, Mode.REALISTIC])
def test_projection_visibility_and_floor_view(mode):
    engine = run_floor_demo(mode)
    events = engine.events
    for viewer in VIEWERS:
        view = engine.perspective(viewer)
        assert view.floor is not None
        assert (view.floor.holder_actor_id, view.floor.queue) == (
            engine.floor.holder, engine.floor.queue
        )
        for event, projected in zip(events, view.events, strict=True):
            if event.actor_id == viewer:
                assert projected.visibility == "own"
                assert projected.findings == (() if event.accepted else tuple(event.findings))
            elif event.accepted:
                assert projected.visibility == "public"
                assert projected.action == event.proposal.action
                assert projected.findings == ()
            else:
                assert projected.visibility == "withheld"
                assert projected.actor_id is None and projected.action is None


def test_projection_floor_mid_run_matches_engine():
    engine = floor_engine(Mode.STRICT)
    for proposal in FLOOR_DEMO_SCRIPT[:9]:
        engine.propose(proposal)
        for viewer in VIEWERS:
            floor = engine.perspective(viewer).floor
            assert (floor.holder_actor_id, floor.queue) == (
                engine.floor.holder, engine.floor.queue
            )
    assert engine.floor == FloorState(queue=("def", "wit"))


def test_projection_refuses_impossible_floor_history():
    engine = run_floor_demo(Mode.STRICT)
    events = engine.events
    # Forge: turn the rejected duplicate request (event 3) into an accepted one.
    events[2] = events[2].model_copy(update={"accepted": True, "findings": []})
    with pytest.raises(ValueError):
        derive_floor(events)
    manifest = load_bundled_manifest()
    with pytest.raises(ValueError):
        build_projection(
            "judge", actors={a.actor_id: a for a in manifest.actors}, events=events,
            evidence_acl={a.actor_id: frozenset() for a in manifest.actors},
            evidence=manifest.registry(), phase=engine.phase, ruleset=DEMO_METADATA,
            floor_enabled=True,
        )


def test_perspective_unknown_actor_denied():
    engine = run_floor_demo()
    with pytest.raises(PermissionError):
        engine.perspective("intruder")


def test_unknown_actor_floor_proposal_commits_nothing():
    engine = floor_engine()
    with pytest.raises(PermissionError):
        engine.propose(p("intruder", RequestFloor()))
    assert engine.events == [] and engine.floor == FloorState()


# --- Journal round trip and restoration --------------------------------------------------

@pytest.mark.parametrize("mode", [Mode.STRICT, Mode.REALISTIC])
def test_sqlite_round_trip_and_restore(tmp_path, mode):
    engine = run_floor_demo(mode)
    store = EventStore(tmp_path / "floor.sqlite")
    for event in engine.events:
        store.append("sim", event)
    assert store.load("sim") == engine.events
    restored = restore_from_store(store, "sim", load_bundled_manifest())
    store.close()
    assert restored.events == engine.events
    assert restored.floor == engine.floor
    assert restored.phase == engine.phase
    for viewer in VIEWERS:
        assert restored.perspective(viewer) == engine.perspective(viewer)


@pytest.mark.parametrize("mode", [Mode.STRICT, Mode.REALISTIC])
@pytest.mark.parametrize("cut", [0, 2, 5, 9, 10, 12, len(FLOOR_DEMO_SCRIPT)])
def test_restore_then_continue_matches_uninterrupted(tmp_path, mode, cut):
    full = run_floor_demo(mode)
    extra = (p("acc", RequestFloor()), p("judge", AdvanceFloor()),
             p("acc", Speak(text="Synthetic")))
    tail = (*FLOOR_DEMO_SCRIPT[cut:], *extra)
    reference = floor_engine(mode)
    for proposal in (*FLOOR_DEMO_SCRIPT, *extra):
        reference.propose(proposal)

    store = EventStore(tmp_path / "cut.sqlite")
    for event in full.events[:cut]:
        store.append("sim", event)
    restored = restore_from_store(
        store, "sim", load_bundled_manifest(), mode=mode, floor_rules=DEMO_FLOOR_RULESET_ID
    )
    assert restored.floor == derive_floor(full.events[:cut])
    for proposal in tail:
        event = restored.propose(proposal)
        store.append("sim", event)
    assert restored.events == reference.events
    assert store.load("sim") == reference.events
    assert restored.floor == reference.floor == FloorState(holder="acc")
    store.close()


def test_restore_infers_floor_control_from_journal():
    engine = run_floor_demo(Mode.REALISTIC)
    restored = restore_engine(load_bundled_manifest(), engine.events)
    assert restored.floor_rules is not None
    assert restored.events == engine.events


def test_empty_history_restore_selects_floor_control():
    manifest = load_bundled_manifest()
    assert restore_engine(manifest, []).floor is None
    restored = restore_engine(manifest, [], floor_rules=DEMO_FLOOR_RULESET_ID)
    assert restored.floor == FloorState()
    assert restored.propose(p("pros", RequestFloor())).accepted


def test_unscheduled_journal_restores_unchanged_and_refuses_floor_request():
    engine = build_engine(load_bundled_manifest(), Mode.STRICT)
    for proposal in SCENARIO_DEMO_SCRIPT:
        engine.propose(proposal)
    manifest = load_bundled_manifest()
    restored = restore_engine(manifest, engine.events)
    assert restored.floor is None and restored.events == engine.events
    with pytest.raises(RestoreError, match="floor rules"):
        restore_engine(manifest, engine.events, floor_rules=DEMO_FLOOR_RULESET_ID)


def test_restore_rejects_requested_floor_mismatch():
    engine = run_floor_demo()
    with pytest.raises(RestoreError, match="floor rules"):
        restore_engine(load_bundled_manifest(), engine.events, floor_rules="other-floor")
    with pytest.raises(TypeError):
        restore_engine(load_bundled_manifest(), engine.events, floor_rules=1)  # type: ignore


def _with_metadata(event: TrialEvent, **changes) -> TrialEvent:
    metadata = {**event.metadata, **changes}
    metadata = {k: v for k, v in metadata.items() if v is not None}
    return event.model_copy(update={"metadata": metadata})


@pytest.mark.parametrize("changes,match", [
    ({"floor_rules_version": "9.9.9"}, "no migrations"),
    ({"floor_rules_validation": "human_reviewed"}, "no migrations"),
    ({"floor_semantics": "indubio.floor/2"}, "floor semantics"),
    ({"floor_rules": "unknown-floor"}, "Unknown floor ruleset"),
    ({"floor_rules_version": None}, "metadata keys"),
    ({"floor_extra": "x"}, "metadata keys"),
])
def test_restore_rejects_tampered_floor_metadata(changes, match):
    events = run_floor_demo().events
    events[3] = _with_metadata(events[3], **changes)
    with pytest.raises(RestoreError, match=match):
        restore_engine(load_bundled_manifest(), events)


def test_restore_rejects_mixed_floor_and_unscheduled_events():
    events = run_floor_demo().events
    events[4] = _with_metadata(events[4], floor_semantics=None, floor_rules=None,
                               floor_rules_version=None, floor_rules_validation=None)
    with pytest.raises(RestoreError, match="changes floor control"):
        restore_engine(load_bundled_manifest(), events)


def test_restore_rejects_forged_floor_outcome():
    events = run_floor_demo().events
    events[2] = events[2].model_copy(update={"accepted": True, "findings": []})
    with pytest.raises(RestoreError, match="differs from its regeneration"):
        restore_engine(load_bundled_manifest(), events)


def test_floor_demo_is_deterministic():
    for mode in ALL_MODES:
        first = [e.model_dump_json() for e in run_floor_demo(mode).events]
        assert first == [e.model_dump_json() for e in run_floor_demo(mode).events]
