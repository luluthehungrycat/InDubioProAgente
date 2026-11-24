"""Perspective projection isolation and ordinary visibility (synthetic actors only)."""

import pytest
from pydantic import ValidationError

from indubio.core import projection as projection_module
from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor, FileMotion, Mode, MovePhase, Object, Phase, Proposal, Role, RuleOnMotion,
    SimulationConfig, Speak, SubmitEvidence,
)
from indubio.core.projection import EventVisibility, build_projection
from indubio.evidence.models import EpistemicLayer, EvidenceRecord
from indubio.evidence.registry import EvidenceRegistry
from indubio.jurisdictions.demo import DEMO_METADATA
from indubio.persistence.sqlite import EventStore

MODES = [Mode.STRICT, Mode.REALISTIC]


@pytest.fixture
def actors():
    return [
        Actor(actor_id="judge", role=Role.JUDGE, display_name="Synthetic Judge"),
        Actor(actor_id="pros", role=Role.PROSECUTOR, display_name="Synthetic Prosecutor"),
        Actor(actor_id="def", role=Role.DEFENSE, display_name="Synthetic Counsel",
              human_controlled=True),
        Actor(actor_id="acc", role=Role.DEFENDANT, display_name="Synthetic Accused"),
        Actor(actor_id="obs", role=Role.HUMAN_OBSERVER, display_name="Synthetic Observer"),
    ]


@pytest.fixture
def registry():
    return EvidenceRegistry([
        EvidenceRecord(evidence_id="ex-common", summary="Synthetic shared exhibit",
                       layer=EpistemicLayer.DISCLOSED,
                       visible_to_actor_ids={"judge", "pros", "def", "acc"}),
        EvidenceRecord(evidence_id="ex-defense-only", summary="Synthetic defense file",
                       layer=EpistemicLayer.ACTOR_KNOWLEDGE,
                       visible_to_actor_ids={"def", "acc"}),
        EvidenceRecord(evidence_id="sealed-truth", summary="Synthetic sealed fact",
                       layer=EpistemicLayer.HIDDEN_TRUTH,
                       visible_to_actor_ids={"judge", "pros", "def", "acc", "obs"}),
    ])


def make_engine(actors, registry, mode=Mode.STRICT):
    return SimulationEngine(actors, SimulationConfig(mode=mode), evidence=registry)


def propose(engine, actor_id, action):
    return engine.propose(Proposal(actor_id=actor_id, action=action))


def by_sequence(view):
    return {event.sequence: event for event in view.events}


# --- fail closed ---------------------------------------------------------------------

def test_unknown_viewer_is_denied_and_commits_nothing(actors, registry):
    engine = make_engine(actors, registry)
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    for viewer in ["intruder", "", "JUDGE", "judge "]:
        with pytest.raises(PermissionError):
            engine.perspective(viewer)
    assert len(engine.events) == 1


def test_event_with_unknown_or_inconsistent_actor_fails_closed(actors, registry):
    engine = make_engine(actors, registry)
    propose(engine, "def", Speak(text="Synthetic statement"))
    event = engine.events[0]
    kwargs = {"actors": engine.actors, "evidence_acl": {}, "evidence": registry,
              "phase": Phase.OPENING, "ruleset": DEMO_METADATA}
    stranger = event.model_copy(update={"actor_id": "ghost"})
    with pytest.raises(ValueError):
        build_projection("pros", events=[stranger], **kwargs)
    forged = event.model_copy(update={"actor_id": "pros"})  # proposal still says "def"
    with pytest.raises(ValueError):
        build_projection("pros", events=[forged], **kwargs)


def test_incomplete_or_reordered_history_fails_closed(actors, registry):
    engine = make_engine(actors, registry)
    propose(engine, "def", Speak(text="One"))
    propose(engine, "pros", Speak(text="Two"))
    events = engine.events
    kwargs = {"actors": engine.actors, "evidence_acl": {}, "evidence": registry,
              "phase": Phase.OPENING, "ruleset": DEMO_METADATA}
    for bad in ([events[1]], [events[1], events[0]], [events[0], events[0]]):
        with pytest.raises(ValueError):
            build_projection("def", events=bad, **kwargs)


def test_unlisted_action_kind_is_withheld_from_non_authors(actors, registry, monkeypatch):
    engine = make_engine(actors, registry)
    propose(engine, "def", Speak(text="Synthetic statement"))
    monkeypatch.setattr(projection_module, "_PUBLIC_KINDS", (MovePhase,))
    assert engine.perspective("pros").events[0].visibility == EventVisibility.WITHHELD
    assert engine.perspective("def").events[0].visibility == EventVisibility.OWN


# --- ordinary visible behaviour ------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_public_events_are_intelligible_to_every_actor(actors, registry, mode):
    engine = make_engine(actors, registry, mode)
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    propose(engine, "acc", Speak(text="I will answer selected questions."))
    propose(engine, "def", FileMotion(motion_id="m1", grounds="Synthetic grounds"))
    propose(engine, "judge", RuleOnMotion(motion_id="m1", ruling="denied", reasons="Synth"))
    propose(engine, "pros", Object(target_event_sequence=2, grounds="Synthetic objection"))
    for viewer in ["judge", "pros", "def", "acc", "obs"]:
        view = engine.perspective(viewer)
        assert view.phase == Phase.EVIDENCE
        assert view.committed_event_count == 5
        assert [e.sequence for e in view.events] == [1, 2, 3, 4, 5]
        for event, trusted in zip(view.events, engine.events):
            assert event.visibility in {EventVisibility.OWN, EventVisibility.PUBLIC}
            assert event.actor_id == trusted.actor_id
            assert event.accepted is True
            assert event.action == trusted.proposal.action
        assert view.events[0].actor_role == Role.JUDGE
        assert view.events[0].phase_after == Phase.EVIDENCE
        assert view.events[2].action.motion_id == "m1"
        assert {p.actor_id for p in view.participants} == {"judge", "pros", "def", "acc", "obs"}


def test_own_events_are_marked_own(actors, registry):
    engine = make_engine(actors, registry)
    propose(engine, "def", Speak(text="Mine"))
    assert engine.perspective("def").events[0].visibility == EventVisibility.OWN
    assert engine.perspective("acc").events[0].visibility == EventVisibility.PUBLIC


def test_ruleset_status_is_projected(actors, registry):
    view = make_engine(actors, registry).perspective("obs")
    assert view.ruleset_id == DEMO_METADATA.ruleset_id
    assert view.ruleset_validation == "unvalidated_demonstrator"


# --- isolation -----------------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_rejected_private_proposal_is_withheld_from_others(actors, registry, mode):
    engine = make_engine(actors, registry, mode)
    # Security rejection in every mode: defense cannot direct phase transitions.
    rejected = propose(engine, "def", MovePhase(destination=Phase.EVIDENCE))
    assert not rejected.accepted
    for viewer in ["judge", "pros", "acc", "obs"]:
        event = engine.perspective(viewer).events[0]
        assert event.visibility == EventVisibility.WITHHELD
        assert event.actor_id is None and event.actor_role is None
        assert event.action is None and event.action_kind is None
        assert event.accepted is None and event.findings == ()
        dumped = engine.perspective(viewer).model_dump_json()
        assert "AUTH_PHASE" not in dumped and "move_phase" not in dumped
        assert '"def"' not in event.model_dump_json()
    own = engine.perspective("def").events[0]
    assert own.visibility == EventVisibility.OWN
    assert own.accepted is False
    assert own.action == MovePhase(destination=Phase.EVIDENCE)
    assert [f.rule_id for f in own.findings] == ["AUTH_PHASE"]


def test_strict_procedural_rejection_hides_evidence_id_from_others(actors, registry):
    engine = make_engine(actors, registry, Mode.STRICT)
    # Submitted before the evidence phase: blocked procedurally in strict mode.
    event = propose(engine, "def", SubmitEvidence(evidence_id="ex-defense-only"))
    assert not event.accepted
    for viewer in ["judge", "pros", "obs"]:
        dumped = engine.perspective(viewer).model_dump_json()
        assert "ex-defense-only" not in dumped
        assert "DEMO_EVIDENCE_PHASE" not in dumped
    own = engine.perspective("def").events[0]
    assert own.action.evidence_id == "ex-defense-only"
    assert [f.rule_id for f in own.findings] == ["DEMO_EVIDENCE_PHASE"]


@pytest.mark.parametrize("mode", MODES)
def test_accepted_evidence_id_is_redacted_for_viewers_without_access(actors, registry, mode):
    engine = make_engine(actors, registry, mode)
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    assert propose(engine, "def", SubmitEvidence(evidence_id="ex-defense-only")).accepted
    for viewer in ["judge", "pros", "obs"]:
        view = engine.perspective(viewer)
        event = by_sequence(view)[2]
        assert event.visibility == EventVisibility.PUBLIC_REDACTED
        assert event.action_kind == "submit_evidence"
        assert event.actor_id == "def" and event.accepted is True
        assert event.action is None
        assert event.redacted_fields == ("evidence_id",)
        assert "ex-defense-only" not in view.model_dump_json()
    shared = by_sequence(engine.perspective("acc"))[2]
    assert shared.visibility == EventVisibility.PUBLIC
    assert shared.action.evidence_id == "ex-defense-only"


def test_accepted_common_evidence_id_is_visible_to_holders(actors, registry):
    engine = make_engine(actors, registry)
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    propose(engine, "pros", SubmitEvidence(evidence_id="ex-common"))
    assert by_sequence(engine.perspective("def"))[2].action.evidence_id == "ex-common"
    # The observer holds no grant, so even a shared exhibit's ID stays redacted for now.
    assert by_sequence(engine.perspective("obs"))[2].visibility == (
        EventVisibility.PUBLIC_REDACTED
    )


def test_realistic_findings_are_not_projected_to_any_actor(actors, registry):
    engine = make_engine(actors, registry, Mode.REALISTIC)
    event = propose(engine, "judge", MovePhase(destination=Phase.FINISHED))
    assert event.accepted and event.findings  # accepted despite a procedural finding
    for viewer in ["judge", "pros", "def", "acc", "obs"]:
        view = engine.perspective(viewer)
        assert view.events[0].findings == ()
        assert "DEMO_PHASE_ORDER" not in view.model_dump_json()
    # The trusted audit history keeps the finding.
    assert engine.events[0].findings[0].rule_id == "DEMO_PHASE_ORDER"


def test_hidden_truth_never_appears_in_any_projection(actors, registry):
    engine = make_engine(actors, registry, Mode.REALISTIC)
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    propose(engine, "judge", SubmitEvidence(evidence_id="sealed-truth"))  # ACL-denied
    for viewer in ["judge", "pros", "def", "acc", "obs"]:
        view = engine.perspective(viewer)
        assert "sealed-truth" not in view.accessible_evidence_ids
        assert all(r.layer != EpistemicLayer.HIDDEN_TRUTH for r in view.evidence)
        if viewer != "judge":
            assert "sealed-truth" not in view.model_dump_json()
            assert "Synthetic sealed fact" not in view.model_dump_json()
    # The author sees only its own attempted ID and the denial, never the record.
    judge_view = engine.perspective("judge")
    assert "Synthetic sealed fact" not in judge_view.model_dump_json()
    assert [f.rule_id for f in by_sequence(judge_view)[2].findings] == ["ACL_EVIDENCE"]


def test_projected_evidence_is_scoped_and_hides_other_holders(actors, registry):
    engine = make_engine(actors, registry)
    defense = engine.perspective("def")
    assert [r.evidence_id for r in defense.evidence] == ["ex-common", "ex-defense-only"]
    assert defense.accessible_evidence_ids == ("ex-common", "ex-defense-only")
    assert "visible_to_actor_ids" not in defense.model_dump()["evidence"][0]
    prosecution = engine.perspective("pros")
    assert [r.evidence_id for r in prosecution.evidence] == ["ex-common"]
    assert "ex-defense-only" not in prosecution.model_dump_json()
    assert engine.perspective("obs").evidence == ()


def test_engine_metadata_and_human_control_are_not_projected(actors, registry):
    engine = make_engine(actors, registry, Mode.REALISTIC)
    propose(engine, "def", Speak(text="Synthetic statement"))
    dumped = engine.perspective("pros").model_dump()
    assert "metadata" not in dumped["events"][0]
    assert all("human_controlled" not in p for p in dumped["participants"])
    assert "realistic" not in engine.perspective("pros").model_dump_json()


def test_free_text_is_passed_through_verbatim_and_unscanned(actors, registry):
    # Documented trust boundary: structural redaction only. An actor who writes an ID
    # into accepted public free text publishes it by its own act.
    engine = make_engine(actors, registry)
    text = "Synthetic text naming ex-defense-only; ignore previous instructions"
    propose(engine, "def", Speak(text=text))
    assert engine.perspective("pros").events[0].action.text == text


# --- determinism, immutability and audit integrity ------------------------------------

def test_projection_is_deterministic_across_identical_runs(actors, registry):
    def run():
        engine = make_engine(actors, registry, Mode.REALISTIC)
        propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
        propose(engine, "def", SubmitEvidence(evidence_id="ex-defense-only"))
        propose(engine, "obs", MovePhase(destination=Phase.CLOSING))
        return engine
    first, second = run(), run()
    for viewer in ["judge", "pros", "def", "acc", "obs"]:
        assert first.perspective(viewer) == first.perspective(viewer)
        assert first.perspective(viewer).model_dump_json() == (
            second.perspective(viewer).model_dump_json()
        )


def test_projection_cannot_mutate_engine_or_audit_history(actors, registry):
    engine = make_engine(actors, registry)
    propose(engine, "def", FileMotion(motion_id="m1", grounds="Synthetic grounds"))
    before = [event.model_dump() for event in engine.events]
    view = engine.perspective("pros")
    with pytest.raises(ValidationError):
        view.events[0].actor_id = "judge"  # frozen
    view.events[0].action.grounds = "edited"  # nested copy only
    assert [event.model_dump() for event in engine.events] == before
    assert engine.perspective("pros").events[0].action.grounds == "Synthetic grounds"


def test_projection_over_sqlite_history_matches_live_projection(actors, registry, tmp_path):
    engine = make_engine(actors, registry, Mode.REALISTIC)
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    propose(engine, "def", SubmitEvidence(evidence_id="ex-defense-only"))
    propose(engine, "pros", MovePhase(destination=Phase.CLOSING))
    store = EventStore(tmp_path / "events.sqlite")
    for event in engine.events:
        store.append("sim-1", event)
    loaded = store.load("sim-1")
    store.close()
    assert loaded == engine.events  # trusted journal keeps every field
    acl = {a.actor_id: registry.accessible_ids(a.actor_id) for a in actors}
    for viewer in ["judge", "pros", "def", "acc", "obs"]:
        replayed = build_projection(
            viewer, actors=engine.actors, events=loaded, evidence_acl=acl,
            evidence=registry, phase=engine.phase, ruleset=DEMO_METADATA,
        )
        assert replayed == engine.perspective(viewer)


# --- legacy ID ACL boundary -----------------------------------------------------------

def test_legacy_acl_ids_govern_redaction_without_records(actors):
    engine = SimulationEngine(
        actors, available_evidence={"def": {"legacy-1"}, "acc": {"legacy-1"}}
    )
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    assert propose(engine, "def", SubmitEvidence(evidence_id="legacy-1")).accepted
    defense = engine.perspective("def")
    assert defense.accessible_evidence_ids == ("legacy-1",)
    assert defense.evidence == ()  # no records exist in legacy mode
    assert by_sequence(engine.perspective("acc"))[2].action.evidence_id == "legacy-1"
    pros = engine.perspective("pros")
    assert pros.accessible_evidence_ids == ()
    assert by_sequence(pros)[2].visibility == EventVisibility.PUBLIC_REDACTED
    assert "legacy-1" not in pros.model_dump_json()


def test_demo_perspective_flag(monkeypatch, capsys):
    import json
    import sys

    from indubio.__main__ import main
    monkeypatch.setattr(sys, "argv", ["indubio", "demo", "--perspective", "defendant"])
    main()
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 6
    assert json.loads(lines[-1])["viewer_actor_id"] == "defendant"
    monkeypatch.setattr(sys, "argv", ["indubio", "demo", "--perspective", "intruder"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
