import pytest

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor, FileMotion, Mode, MovePhase, Phase, Proposal, Role, RuleFinding,
    RuleOnMotion, SimulationConfig, SubmitEvidence,
)


@pytest.fixture
def actors():
    return [
        Actor(actor_id="j", role=Role.JUDGE, display_name="Judge"),
        Actor(actor_id="d", role=Role.DEFENSE, display_name="Defense"),
        Actor(actor_id="w", role=Role.WITNESS, display_name="Witness"),
    ]


def test_strict_mode_blocks_skipped_phase(actors):
    engine = SimulationEngine(actors)
    event = engine.propose(Proposal(actor_id="j", action=MovePhase(destination=Phase.FINISHED)))
    assert not event.accepted
    assert engine.phase == Phase.OPENING
    assert event.findings[0].rule_id == "DEMO_PHASE_ORDER"


def test_realistic_mode_logs_but_accepts_error(actors):
    engine = SimulationEngine(actors, SimulationConfig(mode=Mode.REALISTIC))
    event = engine.propose(Proposal(actor_id="j", action=MovePhase(destination=Phase.FINISHED)))
    assert event.accepted
    assert engine.phase == Phase.FINISHED
    assert event.findings[0].severity == "procedural"


def test_security_is_always_enforced_even_in_realistic_mode(actors):
    engine = SimulationEngine(actors, SimulationConfig(mode=Mode.REALISTIC))
    event = engine.propose(Proposal(actor_id="w", action=MovePhase(destination=Phase.EVIDENCE)))
    assert not event.accepted
    assert engine.phase == Phase.OPENING
    assert event.findings[0].severity == "security"


def test_evidence_acl_is_unconditional(actors):
    engine = SimulationEngine(
        actors, SimulationConfig(mode=Mode.EXPERIMENTAL),
        available_evidence={"d": {"public_exhibit"}},
    )
    denied = engine.propose(
        Proposal(actor_id="w", action=SubmitEvidence(evidence_id="public_exhibit"))
    )
    assert not denied.accepted
    assert denied.findings[0].rule_id == "ACL_EVIDENCE"


def test_motion_ruling_and_event_sequence(actors):
    engine = SimulationEngine(actors)
    first = engine.propose(
        Proposal(actor_id="d", action=FileMotion(motion_id="m1", grounds="Objection"))
    )
    second = engine.propose(Proposal(
        actor_id="j", action=RuleOnMotion(motion_id="m1", ruling="granted", reasons="Granted")
    ))
    assert first.accepted and second.accepted
    assert [event.sequence for event in engine.events] == [1, 2]


def test_unknown_actor_never_commits(actors):
    engine = SimulationEngine(actors)
    with pytest.raises(PermissionError):
        engine.propose(Proposal(actor_id="intruder", action=MovePhase(destination=Phase.FINISHED)))
    assert engine.events == []


def test_caller_mutation_cannot_rewrite_committed_history(actors):
    engine = SimulationEngine(actors)
    proposal = Proposal(actor_id="d", action=FileMotion(motion_id="m1", grounds="Objection"))
    returned = engine.propose(proposal)
    assert returned.proposal is not proposal

    proposal.action.motion_id = "edited"
    returned.accepted = False
    returned.proposal.action.motion_id = "edited-via-return"
    engine.events[0].findings.append(
        RuleFinding(rule_id="FAKE", description="Injected", severity="procedural")
    )

    recorded = engine.events[0]
    assert recorded.accepted
    assert recorded.proposal.action.motion_id == "m1"
    assert recorded.findings == []
    ruling = engine.propose(Proposal(
        actor_id="j", action=RuleOnMotion(motion_id="m1", ruling="denied", reasons="Denied")
    ))
    assert ruling.accepted


def test_events_list_cannot_be_appended_or_cleared(actors):
    engine = SimulationEngine(actors)
    engine.propose(Proposal(actor_id="j", action=MovePhase(destination=Phase.EVIDENCE)))
    engine.events.clear()
    assert [event.sequence for event in engine.events] == [1]


def test_actor_and_acl_snapshots_prevent_later_escalation(actors):
    acl = {"d": {"exhibit"}}
    engine = SimulationEngine(actors, available_evidence=acl)
    actors[2].role = Role.JUDGE
    acl["w"] = {"exhibit"}
    acl["d"].add("secret")

    phase = engine.propose(Proposal(actor_id="w", action=MovePhase(destination=Phase.EVIDENCE)))
    assert not phase.accepted and phase.findings[0].rule_id == "AUTH_PHASE"
    for actor_id, evidence_id in (("w", "exhibit"), ("d", "secret")):
        event = engine.propose(
            Proposal(actor_id=actor_id, action=SubmitEvidence(evidence_id=evidence_id))
        )
        assert not event.accepted
        assert event.findings[0].rule_id == "ACL_EVIDENCE"
