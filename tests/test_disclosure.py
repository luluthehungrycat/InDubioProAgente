"""Evidence disclosure events: authority, effects, privacy and event-time visibility.

Synthetic actors and records only; the disclosure policy is an unvalidated demonstrator.
"""

import pytest

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor,
    DiscloseEvidence,
    Mode,
    MovePhase,
    Phase,
    Proposal,
    Role,
    SimulationConfig,
    Speak,
    SubmitEvidence,
    TrialEvent,
)
from indubio.core.projection import EventVisibility, build_projection
from indubio.evidence.models import EpistemicLayer, EvidenceRecord
from indubio.evidence.registry import EvidenceRegistry
from indubio.jurisdictions.base import RuleContext
from indubio.jurisdictions.demo import DEMO_METADATA, DemoRuleset
from indubio.persistence.sqlite import EventStore

ALL_MODES = list(Mode)
MODES = [Mode.STRICT, Mode.REALISTIC]
VIEWERS = ["judge", "pros", "def", "acc", "wit", "obs"]


@pytest.fixture
def actors():
    return [
        Actor(actor_id="judge", role=Role.JUDGE, display_name="Synthetic Judge"),
        Actor(actor_id="pros", role=Role.PROSECUTOR, display_name="Synthetic Prosecutor"),
        Actor(actor_id="def", role=Role.DEFENSE, display_name="Synthetic Counsel"),
        Actor(actor_id="acc", role=Role.DEFENDANT, display_name="Synthetic Accused"),
        Actor(actor_id="wit", role=Role.WITNESS, display_name="Synthetic Witness"),
        Actor(actor_id="obs", role=Role.HUMAN_OBSERVER, display_name="Synthetic Observer"),
    ]


@pytest.fixture
def registry():
    return EvidenceRegistry([
        EvidenceRecord(evidence_id="ex-shared", summary="Synthetic shared exhibit",
                       layer=EpistemicLayer.DISCLOSED,
                       visible_to_actor_ids={"judge", "pros", "def", "acc"}),
        EvidenceRecord(evidence_id="pros-log", summary="Synthetic prosecution log",
                       layer=EpistemicLayer.ACTOR_KNOWLEDGE, visible_to_actor_ids={"pros"}),
        EvidenceRecord(evidence_id="def-file", summary="Synthetic defense file",
                       layer=EpistemicLayer.ACTOR_KNOWLEDGE,
                       visible_to_actor_ids={"def", "acc", "wit", "obs"}),
        EvidenceRecord(evidence_id="sealed", summary="Synthetic sealed fact",
                       layer=EpistemicLayer.HIDDEN_TRUTH,
                       visible_to_actor_ids={"judge", "pros", "def", "acc"}),
    ])


def make(actors, registry, mode=Mode.STRICT):
    return SimulationEngine(actors, SimulationConfig(mode=mode), evidence=registry)


def propose(engine, actor_id, action):
    return engine.propose(Proposal(actor_id=actor_id, action=action))


def disclose(engine, actor_id, evidence_id, recipient):
    return propose(engine, actor_id, DiscloseEvidence(
        evidence_id=evidence_id, recipient_actor_id=recipient))


def rules(event):
    return [finding.rule_id for finding in event.findings]


def access_snapshot(engine):
    return {viewer: engine.perspective(viewer).accessible_evidence_ids for viewer in VIEWERS}


# --- accepted disclosure ---------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_accepted_disclosure_grants_recipient_access(actors, registry, mode):
    engine = make(actors, registry, mode)
    event = disclose(engine, "pros", "pros-log", "def")
    assert event.accepted and event.findings == []
    view = engine.perspective("def")
    assert "pros-log" in view.accessible_evidence_ids
    received = {r.evidence_id: r for r in view.evidence}["pros-log"]
    assert received.summary == "Synthetic prosecution log"
    assert received.disclosed_at_sequence == 1
    assert {r.evidence_id: r for r in view.evidence}["ex-shared"].disclosed_at_sequence is None
    # Discloser keeps access; nobody else gains it.
    assert "pros-log" in engine.perspective("pros").accessible_evidence_ids
    for viewer in ["judge", "acc", "wit", "obs"]:
        assert "pros-log" not in engine.perspective(viewer).accessible_evidence_ids
    # The immutable scenario-initial view is unchanged.
    assert "pros-log" not in [r.evidence_id for r in engine.evidence_view("def")]
    # The recipient can now introduce it.
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    assert propose(engine, "def", SubmitEvidence(evidence_id="pros-log")).accepted


def test_received_record_can_be_redisclosed_by_an_authorized_role(actors, registry):
    engine = make(actors, registry)
    disclose(engine, "pros", "pros-log", "def")
    assert disclose(engine, "def", "pros-log", "acc").accepted
    assert {r.evidence_id: r for r in engine.perspective("acc").evidence}[
        "pros-log"].disclosed_at_sequence == 2


def test_redundant_disclosure_is_accepted_without_revealing_other_holders(actors, registry):
    # Rejecting it would tell the discloser that the recipient already holds the record.
    engine = make(actors, registry)
    before = access_snapshot(engine)
    event = disclose(engine, "def", "ex-shared", "pros")
    assert event.accepted and event.findings == []
    assert access_snapshot(engine) == before
    shared = {r.evidence_id: r for r in engine.perspective("pros").evidence}["ex-shared"]
    assert shared.disclosed_at_sequence is None  # still a scenario grant


# --- structural authorization, every mode ----------------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("discloser", ["acc", "wit", "obs"])
def test_unauthorized_discloser_roles_are_rejected(actors, registry, mode, discloser):
    engine = make(actors, registry, mode)
    event = disclose(engine, discloser, "def-file", "judge")
    assert not event.accepted
    assert rules(event) == ["AUTH_DISCLOSE"]
    assert "def-file" not in engine.perspective("judge").accessible_evidence_ids


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize(("recipient", "rule"), [
    ("ghost", "REFERENCE_ACTOR"),
    ("pros", "REFERENCE_ACTOR"),  # self
    ("wit", "AUTH_DISCLOSE_RECIPIENT"),
    ("obs", "AUTH_DISCLOSE_RECIPIENT"),
])
def test_invalid_recipients_are_rejected(actors, registry, mode, recipient, rule):
    engine = make(actors, registry, mode)
    before = access_snapshot(engine)
    event = disclose(engine, "pros", "pros-log", recipient)
    assert not event.accepted and rules(event) == [rule]
    assert access_snapshot(engine) == before


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("evidence_id", ["invented-id", "def-file", "sealed"])
def test_unheld_invented_or_sealed_evidence_cannot_be_disclosed(
    actors, registry, mode, evidence_id
):
    engine = make(actors, registry, mode)
    event = disclose(engine, "pros", evidence_id, "judge")
    assert not event.accepted
    assert rules(event) == ["ACL_EVIDENCE"]
    # Identical description for all three: the rejection is no existence oracle.
    assert event.findings[0].description == "Actor cannot access or disclose this evidence ID"
    assert evidence_id not in engine.perspective("judge").accessible_evidence_ids
    assert engine.perspective("judge").events[0].visibility == EventVisibility.WITHHELD
    for viewer in VIEWERS:
        assert "Synthetic sealed fact" not in engine.perspective(viewer).model_dump_json()


def test_legacy_id_grants_cannot_be_disclosed(actors):
    engine = SimulationEngine(actors, available_evidence={"pros": {"legacy-1"}})
    event = disclose(engine, "pros", "legacy-1", "def")
    assert not event.accepted and rules(event) == ["DISCLOSE_RECORD_REQUIRED"]
    assert engine.perspective("def").accessible_evidence_ids == ()


def test_sealed_record_with_visibility_list_is_still_not_disclosable(actors, registry):
    # "sealed" lists judge/pros/def/acc, but hidden truth is never accessible.
    engine = make(actors, registry, Mode.EXPERIMENTAL)
    assert rules(disclose(engine, "judge", "sealed", "def")) == ["ACL_EVIDENCE"]


# --- rejection never changes visibility ------------------------------------------------

@pytest.mark.parametrize("mode", ALL_MODES)
def test_rejected_disclosure_changes_no_visibility_and_stays_private(actors, registry, mode):
    engine = make(actors, registry, mode)
    before = {viewer: engine.perspective(viewer) for viewer in VIEWERS}
    event = disclose(engine, "acc", "def-file", "pros")  # AUTH_DISCLOSE
    assert not event.accepted
    for viewer in VIEWERS:
        after = engine.perspective(viewer)
        assert after.accessible_evidence_ids == before[viewer].accessible_evidence_ids
        assert after.evidence == before[viewer].evidence
    # The named recipient learns nothing beyond a withheld slot.
    projected = engine.perspective("pros").events[0]
    assert projected.visibility == EventVisibility.WITHHELD
    dumped = projected.model_dump_json()
    assert "def-file" not in dumped and '"acc"' not in dumped and "disclose_evidence" not in dumped
    own = engine.perspective("acc").events[0]
    assert own.visibility == EventVisibility.OWN and rules(own) == ["AUTH_DISCLOSE"]


def test_late_disclosure_strict_rejects_without_grant(actors, registry):
    engine = make(actors, registry, Mode.STRICT)
    for phase in (Phase.EVIDENCE, Phase.CLOSING):
        propose(engine, "judge", MovePhase(destination=phase))
    event = disclose(engine, "pros", "pros-log", "def")
    assert not event.accepted and rules(event) == ["DEMO_DISCLOSURE_PHASE"]
    assert "pros-log" not in engine.perspective("def").accessible_evidence_ids
    assert engine.perspective("def").events[2].visibility == EventVisibility.WITHHELD


def test_late_disclosure_realistic_is_recorded_with_finding(actors, registry):
    engine = make(actors, registry, Mode.REALISTIC)
    for phase in (Phase.EVIDENCE, Phase.CLOSING):
        propose(engine, "judge", MovePhase(destination=phase))
    event = disclose(engine, "pros", "pros-log", "def")
    # The event happened; the finding stays in the audit record (it is not made lawful).
    assert event.accepted and rules(event) == ["DEMO_DISCLOSURE_PHASE"]
    assert engine.events[2].findings[0].rule_id == "DEMO_DISCLOSURE_PHASE"
    assert "pros-log" in engine.perspective("def").accessible_evidence_ids
    for viewer in VIEWERS:
        assert "DEMO_DISCLOSURE_PHASE" not in engine.perspective(viewer).model_dump_json()


@pytest.mark.parametrize("mode", MODES)
def test_security_findings_block_even_with_procedural_finding(actors, registry, mode):
    engine = make(actors, registry, mode)
    for phase in (Phase.EVIDENCE, Phase.CLOSING):
        propose(engine, "judge", MovePhase(destination=phase))
    event = disclose(engine, "pros", "pros-log", "wit")
    assert not event.accepted
    assert rules(event) == ["AUTH_DISCLOSE_RECIPIENT", "DEMO_DISCLOSURE_PHASE"]
    assert "pros-log" not in engine.perspective("wit").accessible_evidence_ids


# --- projection privacy ----------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_accepted_disclosure_is_visible_only_to_discloser_and_recipient(actors, registry, mode):
    engine = make(actors, registry, mode)
    disclose(engine, "pros", "pros-log", "def")
    assert engine.perspective("pros").events[0].visibility == EventVisibility.OWN
    recipient = engine.perspective("def").events[0]
    assert recipient.visibility == EventVisibility.RECIPIENT
    assert recipient.actor_id == "pros" and recipient.actor_role == Role.PROSECUTOR
    assert recipient.action == DiscloseEvidence(evidence_id="pros-log", recipient_actor_id="def")
    assert recipient.findings == ()
    for viewer in ["judge", "acc", "wit", "obs"]:
        view = engine.perspective(viewer)
        event = view.events[0]
        assert event.visibility == EventVisibility.WITHHELD
        assert event.actor_id is None and event.action is None and event.action_kind is None
        dumped = view.model_dump_json()
        assert "pros-log" not in dumped and "Synthetic prosecution log" not in dumped
        assert "disclose_evidence" not in dumped


# --- event-time versus current visibility ----------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_later_disclosure_never_unredacts_earlier_events(actors, registry, mode):
    engine = make(actors, registry, mode)
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))           # 1
    assert propose(engine, "def", SubmitEvidence(evidence_id="def-file")).accepted  # 2
    assert disclose(engine, "def", "def-file", "pros").accepted               # 3
    assert propose(engine, "acc", SubmitEvidence(evidence_id="def-file")).accepted  # 4
    view = engine.perspective("pros")
    assert "def-file" in view.accessible_evidence_ids  # current access
    events = {event.sequence: event for event in view.events}
    # Event 2 predates the grant: stays redacted (no retrospective publication).
    assert events[2].visibility == EventVisibility.PUBLIC_REDACTED
    assert events[2].action is None and events[2].redacted_fields == ("evidence_id",)
    assert events[3].visibility == EventVisibility.RECIPIENT
    # Event 4 follows the grant: shown.
    assert events[4].visibility == EventVisibility.PUBLIC
    assert events[4].action.evidence_id == "def-file"
    # Still redacted for the judge, who never received it.
    judge = {event.sequence: event for event in engine.perspective("judge").events}
    assert judge[2].visibility == judge[4].visibility == EventVisibility.PUBLIC_REDACTED
    assert "def-file" not in engine.perspective("judge").model_dump_json()


def test_projection_access_matches_engine_access(actors, registry):
    engine = make(actors, registry, Mode.REALISTIC)
    disclose(engine, "pros", "pros-log", "def")
    disclose(engine, "def", "pros-log", "acc")
    disclose(engine, "acc", "def-file", "judge")  # rejected
    disclose(engine, "def", "def-file", "judge")
    for viewer in VIEWERS:
        assert set(engine.perspective(viewer).accessible_evidence_ids) == engine._access(viewer)


# --- audit journal and replay-safety ---------------------------------------------------

def test_disclosure_history_round_trips_through_sqlite(actors, registry, tmp_path):
    engine = make(actors, registry, Mode.REALISTIC)
    disclose(engine, "pros", "pros-log", "def")
    disclose(engine, "acc", "def-file", "pros")
    propose(engine, "judge", MovePhase(destination=Phase.EVIDENCE))
    propose(engine, "def", SubmitEvidence(evidence_id="pros-log"))
    store = EventStore(tmp_path / "events.sqlite")
    for event in engine.events:
        store.append("sim-1", event)
    loaded = store.load("sim-1")
    store.close()
    assert loaded == engine.events
    acl = {a.actor_id: registry.accessible_ids(a.actor_id) for a in actors}
    for viewer in VIEWERS:
        replayed = build_projection(
            viewer, actors=engine.actors, events=loaded, evidence_acl=acl,
            evidence=registry, phase=engine.phase, ruleset=DEMO_METADATA,
        )
        assert replayed == engine.perspective(viewer)


def test_pre_disclosure_journal_payload_still_loads():
    payload = (
        '{"sequence":1,"actor_id":"d","phase_before":"opening","phase_after":"opening",'
        '"proposal":{"actor_id":"d","action":{"kind":"speak","text":"No comment"}},'
        '"accepted":true,"findings":[],"metadata":{"mode":"strict",'
        '"ruleset":"de-criminal-demo-unvalidated","ruleset_version":"0.1.0-demo",'
        '"ruleset_validation":"unvalidated_demonstrator"}}'
    )
    event = TrialEvent.model_validate_json(payload)
    assert event.proposal.action == Speak(text="No comment")
    assert TrialEvent.model_validate_json(event.model_dump_json()) == event


def forged(sequence, actor_id, evidence_id, recipient):
    return TrialEvent(
        sequence=sequence, actor_id=actor_id, phase_before=Phase.OPENING,
        phase_after=Phase.OPENING, accepted=True,
        proposal=Proposal(actor_id=actor_id, action=DiscloseEvidence(
            evidence_id=evidence_id, recipient_actor_id=recipient)),
    )


@pytest.mark.parametrize(("actor_id", "evidence_id", "recipient"), [
    ("pros", "sealed", "def"),        # hidden truth
    ("pros", "invented-id", "def"),   # no record
    ("pros", "def-file", "judge"),    # discloser lacked access
    ("pros", "pros-log", "wit"),      # recipient role
    ("pros", "pros-log", "pros"),     # self
    ("acc", "def-file", "judge"),     # discloser role
])
def test_projection_fails_closed_on_impossible_accepted_disclosure(
    actors, registry, actor_id, evidence_id, recipient
):
    engine = make(actors, registry)
    acl = {a.actor_id: registry.accessible_ids(a.actor_id) for a in actors}
    with pytest.raises(ValueError):
        build_projection(
            "def", actors=engine.actors, events=[forged(1, actor_id, evidence_id, recipient)],
            evidence_acl=acl, evidence=registry, phase=Phase.OPENING, ruleset=DEMO_METADATA,
        )


def test_forged_disclosure_with_unknown_recipient_fails_closed(actors, registry):
    engine = make(actors, registry)
    acl = {a.actor_id: registry.accessible_ids(a.actor_id) for a in actors}
    with pytest.raises(ValueError):
        build_projection(
            "pros", actors=engine.actors, events=[forged(1, "pros", "pros-log", "ghost")],
            evidence_acl=acl, evidence=registry, phase=Phase.OPENING, ruleset=DEMO_METADATA,
        )


def test_disclosure_proposal_is_snapshotted(actors, registry):
    engine = make(actors, registry)
    action = DiscloseEvidence(evidence_id="pros-log", recipient_actor_id="def")
    proposal = Proposal(actor_id="pros", action=action)
    engine.propose(proposal)
    action.recipient_actor_id = "acc"  # caller edit after commit
    assert engine.events[0].proposal.action.recipient_actor_id == "def"
    assert "pros-log" not in engine.perspective("acc").accessible_evidence_ids


def test_disclose_action_forbids_extra_fields():
    with pytest.raises(ValueError):
        DiscloseEvidence(evidence_id="x", recipient_actor_id="y", recipients=["z"])


# --- ruleset ----------------------------------------------------------------------------

@pytest.mark.parametrize(("phase", "expected"), [
    (Phase.OPENING, []), (Phase.EVIDENCE, []),
    (Phase.CLOSING, ["DEMO_DISCLOSURE_PHASE"]), (Phase.JUDGMENT, ["DEMO_DISCLOSURE_PHASE"]),
    (Phase.FINISHED, ["DEMO_DISCLOSURE_PHASE"]),
])
def test_demo_disclosure_phase_rule(phase, expected):
    context = RuleContext(mode=Mode.STRICT, phase=phase, committed_event_count=0,
                          actor_role=Role.PROSECUTOR)
    findings = DemoRuleset().evaluate(
        context, DiscloseEvidence(evidence_id="x", recipient_actor_id="y"))
    assert [f.rule_id for f in findings] == expected
    assert all(f.severity == "procedural" for f in findings)
