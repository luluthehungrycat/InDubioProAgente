"""Typed floor interrupt requests and explicit judge responses (``indubio.core.floor``).

Synthetic actors only; the floor rules are an unvalidated demonstrator, not StPO/GVG.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from indubio.__main__ import main
from indubio.core.floor import (
    FloorState,
    PendingInterrupt,
    derive_floor,
    structural_findings,
    transition,
)
from indubio.core.models import (
    AdvanceFloor,
    Mode,
    MovePhase,
    Phase,
    Proposal,
    ReleaseFloor,
    RequestFloor,
    RequestInterrupt,
    RespondToInterrupt,
    Role,
    Speak,
    TrialEvent,
    WithdrawFloorRequest,
)
from indubio.core.projection import EventVisibility, build_projection
from indubio.jurisdictions.base import RuleContext
from indubio.jurisdictions.demo import DEMO_METADATA
from indubio.jurisdictions.demo.floor import (
    DEMO_FLOOR_METADATA,
    DEMO_FLOOR_RULESET_ID,
    DemoFloorRuleset,
)
from indubio.persistence.sqlite import EventStore
from indubio.scenarios import (
    RestoreError,
    build_engine,
    load_bundled_manifest,
    restore_engine,
    restore_from_store,
)
from indubio.scenarios.demo import (
    INTERRUPT_DEMO_SCRIPT,
    run_floor_demo,
    run_interrupt_demo,
    run_scenario_demo,
)
from indubio.scenarios.restore import EVENT_METADATA_KEYS, FLOOR_METADATA_KEYS

ALL_MODES = list(Mode)
MODES = [Mode.STRICT, Mode.REALISTIC]
VIEWERS = ["judge", "pros", "def", "acc", "wit", "obs"]
ROLE_OF = {"judge": Role.JUDGE, "pros": Role.PROSECUTOR, "def": Role.DEFENSE,
           "acc": Role.DEFENDANT, "wit": Role.WITNESS, "obs": Role.HUMAN_OBSERVER}
QUEUERS = ["pros", "def", "acc", "wit"]
FIXTURES = Path(__file__).parent / "fixtures"
NOT_PENDING = ["FLOOR_INTERRUPT_NOT_PENDING"]


def floor_engine(mode: Mode = Mode.STRICT):
    return build_engine(load_bundled_manifest(), mode, floor_rules=DEMO_FLOOR_RULESET_ID)


def p(actor_id, action) -> Proposal:
    return Proposal(actor_id=actor_id, action=action)


def respond(sequence, decision="granted") -> Proposal:
    return p("judge", RespondToInterrupt(request_sequence=sequence, decision=decision))


def rules(event):
    return [finding.rule_id for finding in event.findings]


def run(engine, *proposals):
    return [engine.propose(proposal) for proposal in proposals]


def held_by_pros(mode=Mode.STRICT):
    """Engine after: pros holds the floor (events 1-3), def queued."""
    engine = floor_engine(mode)
    run(engine, p("pros", RequestFloor()), p("def", RequestFloor()),
        p("judge", AdvanceFloor()))
    assert engine.floor == FloorState(holder="pros", queue=("def",))
    return engine


def pending(*pairs):
    return tuple(PendingInterrupt(request_sequence=s, actor_id=a) for s, a in pairs)


def load_fixture(name):
    lines = (FIXTURES / name).read_text().splitlines()
    return [TrialEvent.model_validate_json(line) for line in lines]


# --- Schema ------------------------------------------------------------------------------

def test_interrupt_action_schema_is_closed():
    with pytest.raises(ValidationError):
        RequestInterrupt(target="pros")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RespondToInterrupt(request_sequence=0, decision="granted")
    with pytest.raises(ValidationError):
        RespondToInterrupt(request_sequence=1, decision="accepted")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RespondToInterrupt(request_sequence=1, decision="denied", actor_id="x")  # type: ignore
    proposal = Proposal.model_validate_json(respond(3, "denied").model_dump_json())
    assert proposal.action == RespondToInterrupt(request_sequence=3, decision="denied")


# --- Opt-in: unscheduled engines refuse interrupts ---------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
def test_interrupts_without_floor_control_are_rejected(mode):
    engine = build_engine(load_bundled_manifest(), mode)
    for event in run(engine, p("wit", RequestInterrupt()), respond(1)):
        assert not event.accepted
        assert [(f.rule_id, f.severity) for f in event.findings] == [
            ("FLOOR_DISABLED", "security")
        ]
        assert set(event.metadata) == EVENT_METADATA_KEYS
    assert engine.floor is None


@pytest.mark.parametrize("mode", ALL_MODES)
def test_role_finding_precedes_structural_without_floor(mode):
    engine = build_engine(load_bundled_manifest(), mode)
    assert rules(engine.propose(p("obs", RequestInterrupt()))) == [
        "AUTH_FLOOR_INTERRUPT", "FLOOR_DISABLED"
    ]


# --- Role authorization (every mode) -----------------------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("actor_id", VIEWERS)
def test_request_interrupt_role_matrix(mode, actor_id):
    engine = held_by_pros(mode)
    if actor_id == "pros":  # the holder: structural, not a role question
        event = engine.propose(p(actor_id, RequestInterrupt()))
        assert rules(event) == ["FLOOR_INTERRUPT_HOLDER"] and not event.accepted
        return
    event = engine.propose(p(actor_id, RequestInterrupt()))
    if ROLE_OF[actor_id] in {Role.JUDGE, Role.HUMAN_OBSERVER}:
        assert not event.accepted and rules(event) == ["AUTH_FLOOR_INTERRUPT"]
        assert engine.floor.interrupts == ()
    else:
        assert event.accepted and event.findings == []
        assert engine.floor.interrupts == pending((4, actor_id))


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("actor_id", VIEWERS)
@pytest.mark.parametrize("decision", ["granted", "denied"])
def test_only_judge_responds(mode, actor_id, decision):
    engine = held_by_pros(mode)
    engine.propose(p("wit", RequestInterrupt()))
    before = engine.floor
    action = RespondToInterrupt(request_sequence=4, decision=decision)
    event = engine.propose(p(actor_id, action))
    if actor_id == "judge":
        assert event.accepted and event.findings == []
    else:
        assert not event.accepted
        assert rules(event) == ["AUTH_FLOOR_INTERRUPT_RESPONSE"]
        assert engine.floor == before


def test_unauthorized_respond_also_reports_stale_structure():
    engine = held_by_pros()
    event = engine.propose(p("def", RespondToInterrupt(request_sequence=99,
                                                       decision="granted")))
    assert rules(event) == ["AUTH_FLOOR_INTERRUPT_RESPONSE", "FLOOR_INTERRUPT_NOT_PENDING"]


# --- Structural request checks (every mode) ----------------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
def test_request_interrupt_structural_rejections(mode):
    engine = floor_engine(mode)
    event = engine.propose(p("wit", RequestInterrupt()))
    assert rules(event) == ["FLOOR_INTERRUPT_NO_HOLDER"] and not event.accepted
    run(engine, p("pros", RequestFloor()), p("judge", AdvanceFloor()))
    assert rules(engine.propose(p("pros", RequestInterrupt()))) == ["FLOOR_INTERRUPT_HOLDER"]
    assert engine.propose(p("wit", RequestInterrupt())).accepted
    duplicate = engine.propose(p("wit", RequestInterrupt()))
    assert rules(duplicate) == ["FLOOR_DUPLICATE_INTERRUPT"] and not duplicate.accepted
    assert all(f.severity == "security" for e in engine.events for f in e.findings)
    assert engine.floor == FloorState(holder="pros", interrupts=pending((5, "wit")))


# --- Identity, ordering and responses ----------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_pending_identity_is_request_sequence_in_arrival_order(mode):
    engine = held_by_pros(mode)
    events = run(engine, p("acc", RequestInterrupt()), p("obs", RequestInterrupt()),
                 p("wit", RequestInterrupt()), p("def", RequestInterrupt()))
    assert [e.accepted for e in events] == [True, False, True, True]
    assert engine.floor.interrupts == pending((4, "acc"), (6, "wit"), (7, "def"))
    # Holder and queue are untouched by requests.
    assert (engine.floor.holder, engine.floor.queue) == ("pros", ("def",))


@pytest.mark.parametrize("mode", MODES)
def test_denied_removes_only_that_request(mode):
    engine = held_by_pros(mode)
    run(engine, p("acc", RequestInterrupt()), p("wit", RequestInterrupt()))
    event = engine.propose(respond(5, "denied"))
    assert event.accepted and event.findings == []
    assert engine.floor == FloorState(holder="pros", queue=("def",),
                                      interrupts=pending((4, "acc")))
    # The denied requester may ask again; it gets a new identity.
    assert engine.propose(p("wit", RequestInterrupt())).accepted
    assert engine.floor.interrupts == pending((4, "acc"), (7, "wit"))


@pytest.mark.parametrize("mode", MODES)
def test_granted_out_of_order_moves_holder_to_queue_head(mode):
    engine = held_by_pros(mode)
    run(engine, p("acc", RequestInterrupt()), p("def", RequestInterrupt()))
    event = engine.propose(respond(5))  # def (queued) jumps ahead; acc's #4 is discarded
    assert event.accepted
    assert engine.floor == FloorState(holder="def", queue=("pros",))
    assert rules(engine.propose(respond(4))) == NOT_PENDING


@pytest.mark.parametrize("mode", MODES)
def test_granted_unqueued_requester_keeps_queue_order(mode):
    engine = held_by_pros(mode)
    run(engine, p("wit", RequestFloor()), p("acc", RequestInterrupt()), respond(5))
    assert engine.floor == FloorState(holder="acc", queue=("pros", "def", "wit"))
    # The interrupted holder resumes by ordinary FIFO advance.
    engine.propose(p("judge", AdvanceFloor()))
    assert engine.floor == FloorState(holder="pros", queue=("def", "wit"))


# --- Stale requests ----------------------------------------------------------------------

STALE_CAUSES = {
    "release": p("pros", ReleaseFloor()),
    "advance": p("judge", AdvanceFloor()),
    "phase": p("judge", MovePhase(destination=Phase.EVIDENCE)),
}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("cause", STALE_CAUSES, ids=str)
def test_holder_change_or_boundary_discards_pending(mode, cause):
    engine = held_by_pros(mode)
    run(engine, p("acc", RequestInterrupt()), p("wit", RequestInterrupt()))
    assert engine.propose(STALE_CAUSES[cause]).accepted
    assert engine.floor.interrupts == ()
    for sequence in (4, 5):
        event = engine.propose(respond(sequence))
        assert not event.accepted and rules(event) == NOT_PENDING


@pytest.mark.parametrize("mode", MODES)
def test_answered_request_is_stale(mode):
    engine = held_by_pros(mode)
    run(engine, p("acc", RequestInterrupt()), respond(4, "denied"))
    for decision in ("granted", "denied"):
        assert rules(engine.propose(respond(4, decision))) == NOT_PENDING


@pytest.mark.parametrize("mode", MODES)
def test_unchanged_holder_keeps_pending(mode):
    engine = held_by_pros(mode)
    engine.propose(p("acc", RequestInterrupt()))
    run(engine, p("wit", RequestFloor()), p("def", WithdrawFloorRequest()),
        p("pros", Speak(text="Synthetic")))
    assert engine.floor == FloorState(holder="pros", queue=("wit",),
                                      interrupts=pending((4, "acc")))


def test_rejected_move_to_same_phase_keeps_pending_in_realistic():
    engine = held_by_pros(Mode.REALISTIC)
    engine.propose(p("acc", RequestInterrupt()))
    event = engine.propose(p("judge", MovePhase(destination=Phase.OPENING)))
    assert event.accepted and rules(event) == ["DEMO_PHASE_ORDER"]
    assert engine.floor.interrupts == pending((4, "acc"))


# --- Strict / realistic procedural interplay --------------------------------------------

def test_pending_interrupter_talk_over_strict_rejects():
    engine = held_by_pros(Mode.STRICT)
    engine.propose(p("wit", RequestInterrupt()))
    event = engine.propose(p("wit", Speak(text="Synthetic talk-over")))
    assert not event.accepted and rules(event) == ["DEMO_FLOOR_SPEAK"]
    assert engine.floor == FloorState(holder="pros", queue=("def",),
                                      interrupts=pending((4, "wit")))


def test_pending_interrupter_talk_over_realistic_records_but_grants_nothing():
    engine = held_by_pros(Mode.REALISTIC)
    engine.propose(p("wit", RequestInterrupt()))
    before = engine.floor
    event = engine.propose(p("wit", Speak(text="Synthetic talk-over")))
    assert event.accepted and rules(event) == ["DEMO_FLOOR_SPEAK"]
    assert all(f.severity == "procedural" for f in event.findings)
    assert engine.floor == before  # still pending; recording is not a grant


def test_granted_interrupter_speaks_cleanly():
    for mode in MODES:
        engine = held_by_pros(mode)
        run(engine, p("wit", RequestInterrupt()), respond(4))
        event = engine.propose(p("wit", Speak(text="Synthetic")))
        assert event.accepted and event.findings == []


def test_floor_pack_is_unchanged_and_silent_on_interrupts():
    assert (DEMO_FLOOR_METADATA.ruleset_id, DEMO_FLOOR_METADATA.version) == (
        "demo-floor-fifo-unvalidated", "0.1.0-demo"
    )
    assert DEMO_FLOOR_METADATA.validation_status == "unvalidated_demonstrator"
    pack = DemoFloorRuleset()
    for phase in Phase:
        for role in Role:
            context = RuleContext(mode=Mode.STRICT, phase=phase, committed_event_count=0,
                                  actor_role=role, floor_enabled=True)
            for action in (RequestInterrupt(),
                           RespondToInterrupt(request_sequence=1, decision="granted")):
                assert pack.evaluate(context, action) == []


@pytest.mark.parametrize("mode", MODES)
def test_interrupt_events_record_floor_metadata(mode):
    for event in run_interrupt_demo(mode).events:
        assert set(event.metadata) == EVENT_METADATA_KEYS | FLOOR_METADATA_KEYS
        assert event.metadata["floor_semantics"] == "indubio.floor/1"


# --- Privacy and projection --------------------------------------------------------------

def test_not_pending_finding_is_not_an_oracle():
    engine = held_by_pros()
    run(engine, p("obs", RequestInterrupt()),       # 4 rejected (role)
        p("pros", Speak(text="Synthetic")),         # 5 accepted, not an interrupt
        p("acc", RequestInterrupt()),               # 6 accepted
        respond(6, "denied"))                       # 7 accepted
    stale = [engine.propose(respond(sequence)) for sequence in (4, 5, 6, 99)]
    assert {json.dumps([f.model_dump() for f in e.findings]) for e in stale} == {
        json.dumps([{"rule_id": "FLOOR_INTERRUPT_NOT_PENDING",
                     "description": "No pending interrupt request has this sequence",
                     "severity": "security", "status": "potential"}])
    }


@pytest.mark.parametrize("mode", MODES)
def test_interrupt_projection_visibility(mode):
    engine = run_interrupt_demo(mode)
    events = engine.events
    for viewer in VIEWERS:
        view = engine.perspective(viewer)
        for event, projected in zip(events, view.events, strict=True):
            if event.actor_id == viewer:
                assert projected.visibility == EventVisibility.OWN
                assert projected.findings == (() if event.accepted else tuple(event.findings))
            elif event.accepted:
                assert projected.visibility == EventVisibility.PUBLIC
                assert projected.action == event.proposal.action and projected.findings == ()
            else:
                # Rejected interrupt attempts and responses reveal neither author nor kind.
                assert projected.visibility == EventVisibility.WITHHELD
                assert (projected.actor_id, projected.action_kind, projected.action) == (
                    None, None, None
                )
                assert projected.findings == ()


def _floor_from_visible(view) -> FloorState:
    """Rebuild the floor from what the viewer was shown, using the one transition path."""
    state = FloorState()
    for projected in view.events:
        if projected.accepted and projected.action is not None:
            state = transition(
                state, projected.actor_id, projected.action,
                sequence=projected.sequence,
                phase_changed=projected.phase_after != projected.phase_before,
            )
    return state


@pytest.mark.parametrize("mode", MODES)
def test_visible_accepted_events_suffice_to_derive_projected_floor(mode):
    engine = floor_engine(mode)
    for step, proposal in enumerate(INTERRUPT_DEMO_SCRIPT, start=1):
        engine.propose(proposal)
        assert engine.floor == derive_floor(engine.events)
        for viewer in VIEWERS:
            view = engine.perspective(viewer)
            rebuilt = _floor_from_visible(view)
            assert rebuilt == engine.floor, (step, viewer)
            assert view.floor.holder_actor_id == rebuilt.holder
            assert view.floor.queue == rebuilt.queue
            assert [(i.request_sequence, i.actor_id)
                    for i in view.floor.pending_interrupts] == [
                (i.request_sequence, i.actor_id) for i in rebuilt.interrupts
            ]


def test_projected_pending_interrupts_serialize_only_when_present():
    engine = held_by_pros()
    assert "pending_interrupts" not in json.loads(engine.perspective("obs").model_dump_json())[
        "floor"
    ]
    engine.propose(p("wit", RequestInterrupt()))
    dumped = json.loads(engine.perspective("obs").model_dump_json())["floor"]
    assert dumped["pending_interrupts"] == [{"request_sequence": 4, "actor_id": "wit"}]


# --- derive_floor contract and the single transition path --------------------------------

def test_transition_refuses_structurally_impossible_steps():
    with pytest.raises(ValueError):
        transition(FloorState(), "wit", RequestInterrupt(), sequence=1, phase_changed=False)
    with pytest.raises(ValueError):
        transition(FloorState(holder="pros"), "judge",
                   RespondToInterrupt(request_sequence=1, decision="granted"),
                   sequence=2, phase_changed=False)
    assert structural_findings(FloorState(holder="pros"), "wit", RequestInterrupt()) == []


def test_derive_floor_rejects_forged_accepted_interrupt_events():
    events = run_interrupt_demo().events
    # Event 16 (a response to the already answered #6) forged into an accepted one.
    forged = list(events)
    forged[15] = forged[15].model_copy(update={"accepted": True, "findings": []})
    with pytest.raises(ValueError, match="Event 16"):
        derive_floor(forged)
    manifest = load_bundled_manifest()
    with pytest.raises(ValueError):
        build_projection(
            "judge", actors={a.actor_id: a for a in manifest.actors}, events=forged,
            evidence_acl={a.actor_id: frozenset() for a in manifest.actors},
            evidence=manifest.registry(), phase=Phase.EVIDENCE, ruleset=DEMO_METADATA,
            floor_enabled=True,
        )
    with pytest.raises(RestoreError):
        restore_engine(manifest, forged)


def test_derive_floor_trusts_roles_as_documented():
    """derive_floor checks floor structure only; role checks are the engine's."""
    events = run_interrupt_demo().events
    # Event 9 (observer's role-rejected request) forged into an accepted one: structurally
    # possible, so derive_floor accepts it, but restoration (which re-runs the engine)
    # refuses the journal.
    forged = list(events[:9])
    forged[8] = forged[8].model_copy(update={"accepted": True, "findings": []})
    assert "obs" in {i.actor_id for i in derive_floor(forged).interrupts}
    with pytest.raises(RestoreError, match="differs from its regeneration"):
        restore_engine(load_bundled_manifest(), forged)


@pytest.mark.parametrize("state", [
    {"interrupts": pending((1, "wit"))},                          # no holder
    {"holder": "pros", "interrupts": pending((2, "wit"), (1, "acc"))},  # unordered
    {"holder": "pros", "interrupts": pending((1, "wit"), (1, "acc"))},  # duplicate id
    {"holder": "pros", "interrupts": pending((1, "wit"), (2, "wit"))},  # duplicate actor
    {"holder": "pros", "interrupts": pending((1, "pros"))},       # holder interrupts self
])
def test_floor_state_rejects_inconsistent_interrupts(state):
    with pytest.raises(ValidationError):
        FloorState(**state)


# --- Journals: SQLite round trip, restore, restore-then-continue -------------------------

@pytest.mark.parametrize("mode", MODES)
def test_interrupt_journal_round_trip_and_restore(tmp_path, mode):
    engine = run_interrupt_demo(mode)
    store = EventStore(tmp_path / "interrupts.sqlite")
    for event in engine.events:
        store.append("sim", event)
    assert store.load("sim") == engine.events
    restored = restore_from_store(store, "sim", load_bundled_manifest())
    store.close()
    assert restored.events == engine.events
    assert restored.floor == engine.floor and restored.phase == engine.phase
    for viewer in VIEWERS:
        assert restored.perspective(viewer) == engine.perspective(viewer)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("cut", [0, 5, 6, 11, 13, 14, 17, 18, 21, 22,
                                 len(INTERRUPT_DEMO_SCRIPT)])
def test_interrupt_restore_then_continue_matches_uninterrupted(tmp_path, mode, cut):
    extra = (p("acc", RequestFloor()), p("judge", AdvanceFloor()),
             p("wit", RequestFloor()), p("def", RequestInterrupt()), respond(27))
    reference = floor_engine(mode)
    for proposal in (*INTERRUPT_DEMO_SCRIPT, *extra):
        reference.propose(proposal)
    full = run_interrupt_demo(mode)

    store = EventStore(tmp_path / "cut.sqlite")
    for event in full.events[:cut]:
        store.append("sim", event)
    restored = restore_from_store(
        store, "sim", load_bundled_manifest(), mode=mode, floor_rules=DEMO_FLOOR_RULESET_ID
    )
    assert restored.floor == derive_floor(full.events[:cut])
    for proposal in (*INTERRUPT_DEMO_SCRIPT[cut:], *extra):
        store.append("sim", restored.propose(proposal))
    assert restored.events == reference.events == store.load("sim")
    assert restored.floor == reference.floor == FloorState(holder="def", queue=("acc", "wit"))
    store.close()


def test_restore_rejects_tampered_interrupt_decision():
    events = run_interrupt_demo().events
    tampered = events[13].model_copy(deep=True)  # event 14: #6 granted
    tampered.proposal.action.decision = "denied"
    events[13] = tampered
    with pytest.raises(RestoreError, match="differs from its regeneration"):
        restore_engine(load_bundled_manifest(), events)


# --- Earlier journals (frozen at base 547bc4b) stay byte-identical and continue ----------

@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name,runner", [("scenario", run_scenario_demo),
                                         ("floor", run_floor_demo)])
def test_base_journals_are_regenerated_byte_identically(mode, name, runner):
    recorded = (FIXTURES / f"base547bc4b_{name}_demo_{mode.value}.jsonl").read_text()
    assert "".join(e.model_dump_json() + "\n" for e in runner(mode).events) == recorded


@pytest.mark.parametrize("mode", MODES)
def test_base_floor_journal_restores_and_continues_with_interrupts(tmp_path, mode):
    history = load_fixture(f"base547bc4b_floor_demo_{mode.value}.jsonl")
    store = EventStore(tmp_path / "pr8.sqlite")
    for event in history:
        store.append("sim", event)
    restored = restore_from_store(store, "sim", load_bundled_manifest())
    assert restored.events == history and restored.floor == FloorState()
    n = len(history)
    tail = run(restored, p("pros", RequestFloor()), p("judge", AdvanceFloor()),
               p("acc", RequestInterrupt()), respond(n + 3))
    assert [e.accepted for e in tail] == [True, True, True, True]
    for event in tail:
        store.append("sim", event)
    assert restored.floor == FloorState(holder="acc", queue=("pros",))
    again = restore_from_store(store, "sim", load_bundled_manifest())
    assert again.events == restored.events and again.floor == restored.floor
    store.close()


@pytest.mark.parametrize("mode", MODES)
def test_base_unfloored_journal_restores_and_refuses_interrupts(tmp_path, mode):
    history = load_fixture(f"base547bc4b_scenario_demo_{mode.value}.jsonl")
    store = EventStore(tmp_path / "pr7.sqlite")
    for event in history:
        store.append("sim", event)
    restored = restore_from_store(store, "sim", load_bundled_manifest())
    assert restored.events == history and restored.floor is None
    event = restored.propose(p("wit", RequestInterrupt()))
    assert not event.accepted and rules(event) == ["FLOOR_DISABLED"]
    assert set(event.metadata) == EVENT_METADATA_KEYS
    store.append("sim", event)
    assert restore_from_store(store, "sim", load_bundled_manifest()).events == [
        *history, event
    ]
    store.close()


# --- Offline demo ------------------------------------------------------------------------

def test_interrupt_demo_is_deterministic_and_ends_cleared():
    for mode in ALL_MODES:
        first = [e.model_dump_json() for e in run_interrupt_demo(mode).events]
        assert first == [e.model_dump_json() for e in run_interrupt_demo(mode).events]
    assert run_interrupt_demo().floor == FloorState()


def test_interrupt_demo_cli(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["indubio", "interrupt-demo", "--mode", "strict",
                                     "--perspective", "obs"])
    main()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(INTERRUPT_DEMO_SCRIPT) + 1
    assert json.loads(lines[-1])["viewer_actor_id"] == "obs"
