import pytest

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor, FileMotion, Mode, MovePhase, Phase, Proposal, Role, RuleOnMotion,
    SimulationConfig, SubmitEvidence,
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
