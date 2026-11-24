"""Ruleset contract tests using synthetic actors and the unvalidated demonstrator pack."""

import pytest
from pydantic import ValidationError

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor,
    FileMotion,
    Mode,
    MovePhase,
    Object,
    Phase,
    Proposal,
    Role,
    RuleFinding,
    RuleOnMotion,
    SimulationConfig,
    Speak,
    SubmitEvidence,
)
from indubio.jurisdictions.base import JurisdictionRuleset, RuleContext, RulesetMetadata
from indubio.jurisdictions.demo import DEMO_METADATA, DEMO_RULESET_ID, DemoRuleset
from indubio.jurisdictions.registry import get_ruleset

NON_STRICT = (Mode.REALISTIC, Mode.EXPERIMENTAL)


@pytest.fixture
def actors():
    return [
        Actor(actor_id="j", role=Role.JUDGE, display_name="Synthetic Judge"),
        Actor(actor_id="d", role=Role.DEFENSE, display_name="Synthetic Defense"),
        Actor(actor_id="w", role=Role.WITNESS, display_name="Synthetic Witness"),
    ]


class PermissiveRuleset:
    """A ruleset that reports nothing; it must not be able to relax security."""

    metadata = DEMO_METADATA.model_copy(update={"ruleset_id": "test-permissive"})

    def evaluate(self, context, action):
        return []


def engine_with(actors, ruleset, mode=Mode.STRICT, **kwargs):
    config = SimulationConfig(jurisdiction=ruleset.metadata.ruleset_id, mode=mode)
    return SimulationEngine(actors, config, ruleset=ruleset, **kwargs)


# --- Reference test: one illustrative rule (DEMO_PHASE_ORDER) across modes -------------

def skip_phase(actor_id):
    return Proposal(actor_id=actor_id, action=MovePhase(destination=Phase.FINISHED))


def test_reference_phase_order_strict_rejects(actors):
    engine = SimulationEngine(actors, SimulationConfig(mode=Mode.STRICT))
    event = engine.propose(skip_phase("j"))
    assert not event.accepted
    assert [(f.rule_id, f.severity) for f in event.findings] == [
        ("DEMO_PHASE_ORDER", "procedural")
    ]
    assert engine.phase == Phase.OPENING and event.phase_after == Phase.OPENING
    assert engine.events == [event]


@pytest.mark.parametrize("mode", NON_STRICT)
def test_reference_phase_order_realistic_records_and_accepts(actors, mode):
    engine = SimulationEngine(actors, SimulationConfig(mode=mode))
    event = engine.propose(skip_phase("j"))
    assert event.accepted
    # Acceptance does not erase the finding: the anomaly stays on the record.
    assert [(f.rule_id, f.status) for f in event.findings] == [("DEMO_PHASE_ORDER", "potential")]
    assert engine.phase == Phase.FINISHED
    assert engine.events[0].findings == event.findings


@pytest.mark.parametrize("mode", list(Mode))
def test_reference_phase_order_unauthorized_rejected_in_every_mode(actors, mode):
    engine = SimulationEngine(actors, SimulationConfig(mode=mode))
    event = engine.propose(skip_phase("w"))
    assert not event.accepted
    assert engine.phase == Phase.OPENING
    # Security findings precede procedural ones; the ruleset cannot remove them.
    assert [f.rule_id for f in event.findings] == ["AUTH_PHASE", "DEMO_PHASE_ORDER"]
    assert event.findings[0].severity == "security"


# --- Engine security is independent of the ruleset -------------------------------------

@pytest.mark.parametrize("mode", list(Mode))
def test_permissive_ruleset_cannot_relax_security(actors, mode):
    engine = engine_with(actors, PermissiveRuleset(), mode, available_evidence={"d": ["x1"]})
    cases = [
        (Proposal(actor_id="w", action=MovePhase(destination=Phase.EVIDENCE)), "AUTH_PHASE"),
        (Proposal(actor_id="d", action=RuleOnMotion(
            motion_id="m", ruling="granted", reasons="r")), "AUTH_RULING"),
        (Proposal(actor_id="w", action=FileMotion(motion_id="m", grounds="g")), "AUTH_MOTION"),
        (Proposal(actor_id="w", action=Object(target_event_sequence=1, grounds="g")),
         "AUTH_OBJECTION"),
        (Proposal(actor_id="d", action=Object(target_event_sequence=99, grounds="g")),
         "REFERENCE_EVENT"),
        (Proposal(actor_id="w", action=SubmitEvidence(evidence_id="x1")), "ACL_EVIDENCE"),
        (Proposal(actor_id="d", action=SubmitEvidence(evidence_id="unknown")), "ACL_EVIDENCE"),
    ]
    for proposal, rule_id in cases:
        event = engine.propose(proposal)
        assert not event.accepted, rule_id
        assert [f.rule_id for f in event.findings] == [rule_id]
    assert engine.phase == Phase.OPENING
    with pytest.raises(PermissionError):
        engine.propose(Proposal(actor_id="ghost", action=Speak(text="hi")))
    assert len(engine.events) == len(cases)


def test_ruleset_cannot_emit_security_findings(actors):
    class Escalating(PermissiveRuleset):
        def evaluate(self, context, action):
            return [RuleFinding(rule_id="X", description="x", severity="security")]

    engine = engine_with(actors, Escalating())
    with pytest.raises(TypeError):
        engine.propose(Proposal(actor_id="j", action=Speak(text="hi")))
    assert engine.events == []


def test_ruleset_receives_frozen_snapshot_and_action_copy(actors):
    seen = {}

    class Tampering(PermissiveRuleset):
        def evaluate(self, context, action):
            with pytest.raises(ValidationError):
                context.phase = Phase.FINISHED
            with pytest.raises(AttributeError):
                context.motion_ids.add("forged")
            action.motion_id = "tampered"
            seen["context"] = context
            return []

    engine = engine_with(actors, Tampering())
    engine.propose(Proposal(actor_id="d", action=FileMotion(motion_id="m1", grounds="g")))
    assert engine.events[0].proposal.action.motion_id == "m1"
    assert seen["context"].motion_ids == frozenset()
    assert seen["context"].committed_event_count == 0
    assert seen["context"].actor_role == Role.DEFENSE
    ruling = engine.propose(Proposal(
        actor_id="j", action=RuleOnMotion(motion_id="m1", ruling="denied", reasons="r")
    ))
    assert ruling.accepted
    assert seen["context"].motion_ids == frozenset({"m1"})


def test_returned_findings_are_snapshotted(actors):
    shared = RuleFinding(rule_id="P", description="p", severity="procedural")

    class Leaky(PermissiveRuleset):
        def evaluate(self, context, action):
            return [shared]

    engine = engine_with(actors, Leaky(), Mode.REALISTIC)
    engine.propose(Proposal(actor_id="j", action=Speak(text="hi")))
    shared.severity = "security"
    shared.rule_id = "EDITED"
    assert engine.events[0].findings[0].rule_id == "P"
    assert engine.events[0].findings[0].severity == "procedural"


# --- Selection, versioning and provenance ---------------------------------------------

def test_default_ruleset_is_unvalidated_demonstrator(actors):
    engine = SimulationEngine(actors)
    assert isinstance(engine.ruleset, DemoRuleset)
    assert isinstance(engine.ruleset, JurisdictionRuleset)
    meta = engine.ruleset.metadata
    assert meta.ruleset_id == DEMO_RULESET_ID == SimulationConfig().jurisdiction
    assert meta.validation_status == "unvalidated_demonstrator"
    assert meta.sources == () and meta.effective_date is None
    assert "not legal advice" in meta.disclaimer.lower()


def test_event_metadata_records_ruleset_provenance(actors):
    engine = SimulationEngine(actors, SimulationConfig(mode=Mode.REALISTIC))
    event = engine.propose(Proposal(actor_id="j", action=Speak(text="Synthetic")))
    assert event.metadata == {
        "mode": "realistic",
        "ruleset": DEMO_RULESET_ID,
        "ruleset_version": DEMO_METADATA.version,
        "ruleset_validation": "unvalidated_demonstrator",
    }


def test_event_provenance_pinned_at_construction(actors):
    class Shifty(PermissiveRuleset):
        calls = 0

        @property
        def metadata(self):
            Shifty.calls += 1
            version = "1" if Shifty.calls == 1 else "2-swapped"
            return DEMO_METADATA.model_copy(
                update={"ruleset_id": "test-permissive", "version": version}
            )

    engine = engine_with(actors, Shifty())
    first = engine.propose(Proposal(actor_id="j", action=Speak(text="a")))
    second = engine.propose(Proposal(actor_id="j", action=Speak(text="b")))
    assert first.metadata["ruleset_version"] == second.metadata["ruleset_version"]


def test_unknown_jurisdiction_fails_instead_of_falling_back(actors):
    with pytest.raises(ValueError):
        get_ruleset("de-criminal-stpo")
    with pytest.raises(ValueError):
        SimulationEngine(actors, SimulationConfig(jurisdiction="us-federal"))


def test_ruleset_must_match_config_and_protocol(actors):
    with pytest.raises(ValueError):
        SimulationEngine(actors, SimulationConfig(), ruleset=PermissiveRuleset())
    with pytest.raises(TypeError):
        SimulationEngine(actors, ruleset=object())


def test_metadata_cannot_claim_review_without_provenance():
    with pytest.raises(ValidationError):
        RulesetMetadata(
            ruleset_id="fake", version="1", title="t", disclaimer="d",
            validation_status="human_reviewed",
        )
    with pytest.raises(ValidationError):
        DEMO_METADATA.validation_status = "human_reviewed"


def test_config_snapshot_cannot_swap_ruleset_label(actors):
    config = SimulationConfig(mode=Mode.STRICT)
    engine = SimulationEngine(actors, config)
    config.mode = Mode.REALISTIC
    config.jurisdiction = "forged"
    event = engine.propose(skip_phase("j"))
    assert not event.accepted
    assert event.metadata["ruleset"] == DEMO_RULESET_ID


def test_demo_ruleset_is_pure_function_of_snapshot():
    ruleset = DemoRuleset()
    context = RuleContext(
        mode=Mode.STRICT, phase=Phase.OPENING, committed_event_count=0,
        motion_ids=frozenset({"m1"}), actor_role=Role.JUDGE,
    )
    cases = {
        "DEMO_PHASE_ORDER": MovePhase(destination=Phase.CLOSING),
        "DEMO_MOTION_MISSING": RuleOnMotion(motion_id="m2", ruling="denied", reasons="r"),
        "DEMO_MOTION_DUPLICATE": FileMotion(motion_id="m1", grounds="g"),
        "DEMO_EVIDENCE_PHASE": SubmitEvidence(evidence_id="e"),
    }
    for rule_id, action in cases.items():
        assert [f.rule_id for f in ruleset.evaluate(context, action)] == [rule_id]
    assert ruleset.evaluate(context, MovePhase(destination=Phase.EVIDENCE)) == []
    finished = context.model_copy(update={"phase": Phase.FINISHED})
    assert [f.rule_id for f in ruleset.evaluate(finished, Speak(text="x"))] == [
        "DEMO_AFTER_FINISH"
    ]


def test_default_demo_script_behavior_is_preserved(actors):
    """Golden sequence: same outcomes, findings and phases as before the extraction."""
    actors = actors + [Actor(actor_id="a", role=Role.DEFENDANT, display_name="Synthetic")]
    script = [
        Proposal(actor_id="j", action=MovePhase(destination=Phase.EVIDENCE)),
        Proposal(actor_id="a", action=Speak(text="Synthetic statement")),
        Proposal(actor_id="d", action=FileMotion(motion_id="m1", grounds="g")),
        Proposal(actor_id="j", action=RuleOnMotion(motion_id="m1", ruling="denied", reasons="r")),
        Proposal(actor_id="j", action=MovePhase(destination=Phase.FINISHED)),
        Proposal(actor_id="a", action=Speak(text="After close")),
    ]
    expected = {
        Mode.STRICT: [
            (True, [], "evidence"), (True, [], "evidence"), (True, [], "evidence"),
            (True, [], "evidence"), (False, ["DEMO_PHASE_ORDER"], "evidence"),
            (True, [], "evidence"),
        ],
        Mode.REALISTIC: [
            (True, [], "evidence"), (True, [], "evidence"), (True, [], "evidence"),
            (True, [], "evidence"), (True, ["DEMO_PHASE_ORDER"], "finished"),
            (True, ["DEMO_AFTER_FINISH"], "finished"),
        ],
    }
    for mode, rows in expected.items():
        engine = SimulationEngine(actors, SimulationConfig(mode=mode))
        got = [
            (e.accepted, [f.rule_id for f in e.findings], e.phase_after.value)
            for e in map(engine.propose, script)
        ]
        assert got == rows, mode
        assert [e.sequence for e in engine.events] == list(range(1, len(script) + 1))
