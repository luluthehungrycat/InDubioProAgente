"""Illustrative demonstrator ruleset. NOT German procedural law, NOT legal advice."""

from indubio.core.models import (
    PHASES,
    Action,
    FileMotion,
    MovePhase,
    Phase,
    RuleFinding,
    RuleOnMotion,
    Speak,
    SubmitEvidence,
)
from indubio.jurisdictions.base import RuleContext, RulesetMetadata

DEMO_RULESET_ID = "de-criminal-demo-unvalidated"

DEMO_METADATA = RulesetMetadata(
    ruleset_id=DEMO_RULESET_ID,
    version="0.1.0-demo",
    title="Schematic demonstrator phase and motion checks",
    validation_status="unvalidated_demonstrator",
    disclaimer=(
        "Simplified demonstrator rules for testing the engine only. Not derived from or "
        "verified against the StPO/GVG; not legal advice."
    ),
)


def _procedural(rule_id: str, description: str) -> RuleFinding:
    return RuleFinding(rule_id=rule_id, description=description, severity="procedural")


class DemoRuleset:
    """The pre-extraction demonstrator rules, unchanged in IDs, order and wording."""

    @property
    def metadata(self) -> RulesetMetadata:
        return DEMO_METADATA

    def evaluate(self, context: RuleContext, action: Action) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        if isinstance(action, MovePhase):
            current = PHASES.index(context.phase)
            target = PHASES.index(action.destination)
            if target != current + 1:
                findings.append(_procedural("DEMO_PHASE_ORDER", "Unexpected phase transition"))
        if isinstance(action, RuleOnMotion) and action.motion_id not in context.motion_ids:
            findings.append(
                _procedural("DEMO_MOTION_MISSING", "Ruling refers to an unknown motion")
            )
        if isinstance(action, FileMotion) and action.motion_id in context.motion_ids:
            findings.append(_procedural("DEMO_MOTION_DUPLICATE", "Motion ID already exists"))
        if isinstance(action, SubmitEvidence) and context.phase != Phase.EVIDENCE:
            findings.append(_procedural(
                "DEMO_EVIDENCE_PHASE", "Evidence submitted outside demonstrator phase"
            ))
        if isinstance(action, Speak) and context.phase == Phase.FINISHED:
            findings.append(_procedural(
                "DEMO_AFTER_FINISH", "Speech after close of demonstrator proceeding"
            ))
        return findings
