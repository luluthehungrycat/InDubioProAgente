"""Per-role action authorization: authoritative table, fail-closed lookup, engine wiring.

Synthetic actors and records only; the policy is an unvalidated demonstrator, not StPO.
"""

import typing

import pytest
from pydantic import ValidationError

from indubio.core import authorization
from indubio.core.authorization import (
    ACTION_POLICY,
    DISCLOSURE_RECIPIENT_ROLES,
    UNREGISTERED_ACTION_RULE_ID,
    authorization_finding,
    can_receive_disclosure,
    is_authorized,
    permission_for,
)
from indubio.core.disclosure import (
    DISCLOSER_ROLES,
    RECIPIENT_ROLES,
    access_at,
    derive_grants,
    has_access,
)
from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    ACTION_TYPES,
    Action,
    Actor,
    AdvanceFloor,
    DiscloseEvidence,
    FileMotion,
    Mode,
    MovePhase,
    Object,
    Phase,
    Proposal,
    ReleaseFloor,
    RequestFloor,
    Role,
    RuleOnMotion,
    SimulationConfig,
    Speak,
    SubmitEvidence,
    TrialEvent,
    WithdrawFloorRequest,
)
from indubio.evidence.models import EpistemicLayer, EvidenceRecord
from indubio.evidence.registry import EvidenceRegistry
from indubio.jurisdictions.demo import DEMO_METADATA
from indubio.persistence.sqlite import EventStore

J, P, D, A, W, O = (Role.JUDGE, Role.PROSECUTOR, Role.DEFENSE, Role.DEFENDANT,
                    Role.WITNESS, Role.HUMAN_OBSERVER)

# Written out independently of the implementation: the reviewed expectation.
EXPECTED = {
    "speak": ({J, P, D, A, W}, "AUTH_SPEAK"),
    "submit_evidence": ({J, P, D, A, W}, "AUTH_SUBMIT_EVIDENCE"),
    "move_phase": ({J}, "AUTH_PHASE"),
    "rule_on_motion": ({J}, "AUTH_RULING"),
    "file_motion": ({P, D, A}, "AUTH_MOTION"),
    "object": ({P, D, A}, "AUTH_OBJECTION"),
    "disclose_evidence": ({J, P, D}, "AUTH_DISCLOSE"),
}
# Opt-in floor control; the engine role matrix for these lives in tests/test_floor.py,
# because a permitted floor action also needs floor control and a matching floor state.
FLOOR_EXPECTED = {
    "request_floor": ({P, D, A, W}, "AUTH_FLOOR_REQUEST"),
    "withdraw_floor_request": ({P, D, A, W}, "AUTH_FLOOR_WITHDRAW"),
    "release_floor": ({P, D, A, W}, "AUTH_FLOOR_RELEASE"),
    "advance_floor": ({J}, "AUTH_FLOOR_ADVANCE"),
}
CORE_EXPECTED = EXPECTED
EXPECTED = {**CORE_EXPECTED, **FLOOR_EXPECTED}

ACTOR_FOR_ROLE = {J: "judge", P: "pros", D: "def", A: "acc", W: "wit", O: "obs"}


def sample_action(kind, actor_id):
    recipient = "pros" if actor_id == "acc" else "acc"
    return {
        "speak": Speak(text="Synthetic statement"),
        "submit_evidence": SubmitEvidence(evidence_id="ex"),
        "move_phase": MovePhase(destination=Phase.EVIDENCE),
        "rule_on_motion": RuleOnMotion(motion_id="m", ruling="denied", reasons="r"),
        "file_motion": FileMotion(motion_id="m-new", grounds="g"),
        "object": Object(target_event_sequence=1, grounds="g"),
        "disclose_evidence": DiscloseEvidence(evidence_id="ex", recipient_actor_id=recipient),
        "request_floor": RequestFloor(),
        "withdraw_floor_request": WithdrawFloorRequest(),
        "release_floor": ReleaseFloor(),
        "advance_floor": AdvanceFloor(),
    }[kind]


CASES = [(kind, role) for kind in CORE_EXPECTED for role in Role]
ALL_CASES = [(kind, role) for kind in EXPECTED for role in Role]


class PermissiveRuleset:
    """Reports no procedural findings, isolating the security layer."""

    metadata = DEMO_METADATA.model_copy(update={"ruleset_id": "test-permissive"})

    def evaluate(self, context, action):
        return []


@pytest.fixture
def actors():
    return [Actor(actor_id=actor_id, role=role, display_name=f"Synthetic {role.value}")
            for role, actor_id in ACTOR_FOR_ROLE.items()]


@pytest.fixture
def registry():
    return EvidenceRegistry([
        EvidenceRecord(evidence_id="ex", summary="Synthetic shared exhibit",
                       layer=EpistemicLayer.DISCLOSED,
                       visible_to_actor_ids=set(ACTOR_FOR_ROLE.values())),
        EvidenceRecord(evidence_id="pros-only", summary="Synthetic prosecution note",
                       layer=EpistemicLayer.ACTOR_KNOWLEDGE, visible_to_actor_ids={"pros"}),
    ])


def make(actors, registry, mode, ruleset=None):
    ruleset = ruleset or PermissiveRuleset()
    config = SimulationConfig(jurisdiction=ruleset.metadata.ruleset_id, mode=mode)
    engine = SimulationEngine(actors, config, ruleset=ruleset, evidence=registry)
    # Event 1 exists, so ``Object(target_event_sequence=1)`` is structurally valid.
    engine.propose(Proposal(actor_id="judge", action=Speak(text="Synthetic opening")))
    return engine


def rules(event):
    return [finding.rule_id for finding in event.findings]


# --- The table itself ---------------------------------------------------------------------

def test_every_action_kind_in_the_union_is_registered():
    union = typing.get_args(typing.get_args(Action)[0])
    assert ACTION_TYPES == union  # shared, schema-derived membership
    assert set(ACTION_TYPES) == set(ACTION_POLICY)
    for model, permission in ACTION_POLICY.items():
        assert model.model_fields["kind"].default == permission.kind


def test_policy_matches_reviewed_expectation():
    assert {p.kind: (set(p.allowed_roles), p.rule_id) for p in ACTION_POLICY.values()} == (
        EXPECTED
    )


def test_passive_observer_is_authorized_for_nothing():
    assert all(O not in p.allowed_roles for p in ACTION_POLICY.values())
    assert not can_receive_disclosure(O)


def test_policy_is_read_only():
    with pytest.raises(TypeError):
        ACTION_POLICY[Speak] = ACTION_POLICY[MovePhase]  # type: ignore[index]
    with pytest.raises(ValidationError):
        ACTION_POLICY[Speak].allowed_roles = frozenset(Role)  # frozen model


def test_disclosure_constants_alias_the_authoritative_table():
    assert DISCLOSER_ROLES == ACTION_POLICY[DiscloseEvidence].allowed_roles == {J, P, D}
    assert RECIPIENT_ROLES == DISCLOSURE_RECIPIENT_ROLES == {J, P, D, A}


@pytest.mark.parametrize("kind,role", ALL_CASES)
def test_pure_lookup(kind, role):
    allowed, rule_id = EXPECTED[kind]
    action = sample_action(kind, ACTOR_FOR_ROLE[role])
    finding = authorization_finding(role, action)
    assert is_authorized(role, action) == (role in allowed)
    if role in allowed:
        assert finding is None
    else:
        assert (finding.rule_id, finding.severity) == (rule_id, "security")


# --- Fail closed: missing policy vs out-of-schema runtime types -------------------------------------------

class UnregisteredSpeak(Speak):
    """A subclass is not the registered class and must not inherit its permission."""


class ForeignAction:
    kind = "speak"


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("action", [UnregisteredSpeak(text="x"), ForeignAction(), None])
def test_unregistered_action_is_denied_for_every_role(role, action):
    assert permission_for(action) is None
    assert not is_authorized(role, action)
    finding = authorization_finding(role, action)
    assert (finding.rule_id, finding.severity) == (UNREGISTERED_ACTION_RULE_ID, "security")


class SpyRuleset(PermissiveRuleset):
    """Records whether the ruleset was consulted at all."""

    def __init__(self):
        self.calls = 0

    def evaluate(self, context, action):
        self.calls += 1
        return []


def engine_state(engine):
    return (engine.events, engine.phase, dict(engine._motions),
            {k: dict(v) for k, v in engine._grants.items()})


OUT_OF_SCHEMA = [UnregisteredSpeak(text="x"), ForeignAction(), None, {"kind": "speak",
                                                                     "text": "x"}]


@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("action", OUT_OF_SCHEMA,
                         ids=["subclass", "foreign", "none", "dict"])
def test_engine_refuses_out_of_schema_action_before_any_change(actors, registry, mode, action):
    ruleset = SpyRuleset()
    engine = make(actors, registry, mode, ruleset)
    before, calls = engine_state(engine), ruleset.calls
    proposal = Proposal.model_construct(actor_id="judge", action=action)
    with pytest.raises(TypeError, match="not part of the Action schema"):
        engine.propose(proposal)
    assert engine_state(engine) == before and ruleset.calls == calls


@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("action", [
    Speak.model_construct(text=""),                       # violates min_length
    Speak.model_construct(),                              # required field missing
    MovePhase.model_construct(destination="nowhere"),     # not a Phase
    Object.model_construct(target_event_sequence=0, grounds="g"),
    RuleOnMotion.model_construct(motion_id="m", ruling="maybe", reasons="r"),
    Speak.model_construct(text=123),                      # wrong type, no coercion
], ids=["empty-text", "missing-field", "bad-phase", "bad-sequence", "bad-literal",
        "wrong-type"])
def test_engine_refuses_malformed_schema_action_before_any_change(
    actors, registry, mode, action
):
    ruleset = SpyRuleset()
    engine = make(actors, registry, mode, ruleset)
    before, calls = engine_state(engine), ruleset.calls
    with pytest.raises(ValueError, match="does not conform"):
        engine.propose(Proposal.model_construct(actor_id="obs", action=action))
    assert engine_state(engine) == before and ruleset.calls == calls


def test_engine_refuses_non_proposal(actors, registry):
    engine = make(actors, registry, Mode.STRICT)
    before = engine_state(engine)
    with pytest.raises(TypeError):
        engine.propose({"actor_id": "judge", "action": {"kind": "speak", "text": "x"}})
    assert engine_state(engine) == before


def test_engine_records_canonical_copy_of_valid_action(actors, registry):
    engine = make(actors, registry, Mode.STRICT)
    proposal = Proposal.model_construct(
        actor_id="judge", action=MovePhase.model_construct(destination="evidence"))
    event = engine.propose(proposal)
    assert event.accepted and type(event.proposal.action.destination) is Phase


def test_removing_a_policy_entry_fails_closed(actors, registry, monkeypatch):
    shrunk = {k: v for k, v in ACTION_POLICY.items() if k is not Speak}
    monkeypatch.setattr(authorization, "ACTION_POLICY", shrunk)
    config = SimulationConfig(jurisdiction="test-permissive", mode=Mode.EXPERIMENTAL)
    engine = SimulationEngine(actors, config, ruleset=PermissiveRuleset(), evidence=registry)
    event = engine.propose(Proposal(actor_id="judge", action=Speak(text="x")))
    assert not event.accepted and rules(event) == [UNREGISTERED_ACTION_RULE_ID]


@pytest.mark.parametrize("mode", list(Mode))
def test_missing_policy_rejection_round_trips_through_sqlite(
    actors, registry, monkeypatch, tmp_path, mode
):
    """A canonical schema action without a policy entry is a normal rejected event."""
    shrunk = {k: v for k, v in ACTION_POLICY.items() if k is not Speak}
    monkeypatch.setattr(authorization, "ACTION_POLICY", shrunk)
    config = SimulationConfig(jurisdiction="test-permissive", mode=mode)
    engine = SimulationEngine(actors, config, ruleset=PermissiveRuleset(), evidence=registry)
    event = engine.propose(Proposal(actor_id="judge", action=Speak(text="x")))
    assert not event.accepted and rules(event) == [UNREGISTERED_ACTION_RULE_ID]
    assert engine.phase == Phase.OPENING

    store = EventStore(tmp_path / "events.sqlite3")
    try:
        store.append("case", event)
        (loaded,) = store.load("case")
    finally:
        store.close()
    assert loaded == event == engine.events[-1]
    assert type(loaded.proposal.action) is Speak
    assert [(f.rule_id, f.severity) for f in loaded.findings] == [
        (UNREGISTERED_ACTION_RULE_ID, "security")]


# --- Engine: every role x action kind x mode ---------------------------------------------

@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("kind,role", CASES)
def test_engine_role_matrix(actors, registry, kind, role, mode):
    allowed, rule_id = EXPECTED[kind]
    actor_id = ACTOR_FOR_ROLE[role]
    engine = make(actors, registry, mode)
    phase_before = engine.phase
    event = engine.propose(Proposal(actor_id=actor_id, action=sample_action(kind, actor_id)))
    if role in allowed:
        assert event.accepted and event.findings == []
    else:
        # Security severity rejects in every mode, and the role finding comes first.
        assert not event.accepted
        assert [(f.rule_id, f.severity) for f in event.findings] == [(rule_id, "security")]
        assert engine.phase == phase_before
        assert engine._motions == {} and engine._grants == {}
    assert engine.events[-1] == event


@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("kind", list(EXPECTED))
def test_observer_attempts_are_audited_and_withheld(actors, registry, kind, mode):
    engine = make(actors, registry, mode)
    event = engine.propose(Proposal(actor_id="obs", action=sample_action(kind, "obs")))
    assert not event.accepted
    assert engine.perspective("obs").events[-1].findings[0].rule_id == EXPECTED[kind][1]
    for viewer in ["judge", "pros", "def", "acc", "wit"]:
        assert engine.perspective(viewer).events[-1].visibility == "withheld"


@pytest.mark.parametrize("mode", list(Mode))
def test_disclosure_recipient_roles_matrix(actors, registry, mode):
    for role in Role:
        recipient = ACTOR_FOR_ROLE[role]
        if recipient == "pros":
            continue  # pros is the discloser below; self-disclosure is REFERENCE_ACTOR
        engine = make(actors, registry, mode)
        event = engine.propose(Proposal(actor_id="pros", action=DiscloseEvidence(
            evidence_id="pros-only", recipient_actor_id=recipient)))
        if role in RECIPIENT_ROLES:
            assert event.accepted and rules(event) == []
        else:
            assert not event.accepted and rules(event) == ["AUTH_DISCLOSE_RECIPIENT"]
            assert engine._grants == {}


# --- Finding order is preserved (role first, then structural/ACL, then procedural) -------

@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("actor_id,action,expected", [
    ("wit", DiscloseEvidence(evidence_id="pros-only", recipient_actor_id="obs"),
     ["AUTH_DISCLOSE", "AUTH_DISCLOSE_RECIPIENT", "ACL_EVIDENCE"]),
    ("obs", DiscloseEvidence(evidence_id="ex", recipient_actor_id="obs"),
     ["AUTH_DISCLOSE", "REFERENCE_ACTOR"]),
    ("wit", Object(target_event_sequence=99, grounds="g"),
     ["AUTH_OBJECTION", "REFERENCE_EVENT"]),
    ("obs", SubmitEvidence(evidence_id="pros-only"),
     ["AUTH_SUBMIT_EVIDENCE", "ACL_EVIDENCE"]),
    ("wit", SubmitEvidence(evidence_id="pros-only"), ["ACL_EVIDENCE"]),
])
def test_security_finding_order(actors, registry, mode, actor_id, action, expected):
    engine = make(actors, registry, mode)
    event = engine.propose(Proposal(actor_id=actor_id, action=action))
    assert not event.accepted and rules(event) == expected


@pytest.mark.parametrize("mode", list(Mode))
def test_role_finding_precedes_demo_procedural_finding(actors, registry, mode):
    config = SimulationConfig(mode=mode)
    engine = SimulationEngine(actors, config, evidence=registry)
    engine.propose(Proposal(actor_id="judge", action=MovePhase(destination=Phase.EVIDENCE)))
    engine.propose(Proposal(actor_id="judge", action=MovePhase(destination=Phase.CLOSING)))
    event = engine.propose(Proposal(actor_id="obs", action=SubmitEvidence(evidence_id="ex")))
    assert not event.accepted
    assert rules(event) == ["AUTH_SUBMIT_EVIDENCE", "DEMO_EVIDENCE_PHASE"]


# --- Revalidation of trusted history uses the same policy --------------------------------

def forged_disclosure(sequence, actor_id, recipient_id, evidence_id="ex"):
    return TrialEvent(
        sequence=sequence, actor_id=actor_id, phase_before=Phase.OPENING,
        phase_after=Phase.OPENING, accepted=True,
        proposal=Proposal(actor_id=actor_id, action=DiscloseEvidence(
            evidence_id=evidence_id, recipient_actor_id=recipient_id)),
    )


@pytest.mark.parametrize("discloser", list(Role))
@pytest.mark.parametrize("recipient", list(Role))
def test_derive_grants_revalidates_with_authoritative_roles(
    actors, registry, discloser, recipient
):
    if discloser == recipient:
        return  # self-disclosure is a reference failure, covered elsewhere
    by_id = {actor.actor_id: actor for actor in actors}
    base = {actor_id: registry.accessible_ids(actor_id) for actor_id in by_id}
    event = forged_disclosure(1, ACTOR_FOR_ROLE[discloser], ACTOR_FOR_ROLE[recipient])
    valid = is_authorized(discloser, event.proposal.action) and can_receive_disclosure(recipient)
    if valid:
        grants = derive_grants([event], actors=by_id, base_acl=base, registry=registry)
        assert grants == {ACTOR_FOR_ROLE[recipient]: {"ex": 1}}
    else:
        with pytest.raises(ValueError):
            derive_grants([event], actors=by_id, base_acl=base, registry=registry)


def test_has_access_matches_access_at():
    base = {"a": frozenset({"x"}), "b": frozenset()}
    grants = {"b": {"y": 3}, "c": {"x": 1}}
    for actor_id in ["a", "b", "c", "missing"]:
        for evidence_id in ["x", "y", "z"]:
            assert has_access(actor_id, evidence_id, base, grants) == (
                evidence_id in access_at(actor_id, base, grants)
            )
