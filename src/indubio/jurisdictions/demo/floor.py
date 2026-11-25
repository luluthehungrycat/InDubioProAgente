"""Illustrative demonstrator floor ruleset. NOT German procedural law, NOT legal advice.

A separate, versioned procedural pack for the opt-in speaking queue
(``indubio.core.floor``). It is kept apart from the jurisdiction ruleset so that enabling
floor control never changes the default ruleset's identity or version: journals recorded
without floor control keep restoring against ``de-criminal-demo-unvalidated`` unchanged,
and floor-enabled events record this pack's ID and version in their own metadata keys.

Rules (``procedural`` only; strict rejects, realistic records the event with the finding):

* ``DEMO_FLOOR_SPEAK``: a non-judge ``speak`` while not holding the floor. The presiding
  judge is never queued in this demonstrator and may always speak.
* ``DEMO_FLOOR_FINISHED``: ``request_floor`` or ``advance_floor`` after the demonstrator
  proceeding has finished.

The pack sees only the frozen ``RuleContext``; it cannot change the queue, grant the
floor or relax the engine's unconditional role and structural floor checks.
"""

from indubio.core.models import (
    Action,
    AdvanceFloor,
    Phase,
    RequestFloor,
    Role,
    RuleFinding,
    Speak,
)
from indubio.jurisdictions.base import RuleContext, RulesetMetadata

DEMO_FLOOR_RULESET_ID = "demo-floor-fifo-unvalidated"

DEMO_FLOOR_METADATA = RulesetMetadata(
    ruleset_id=DEMO_FLOOR_RULESET_ID,
    version="0.1.0-demo",
    title="Schematic demonstrator speaking-queue checks",
    validation_status="unvalidated_demonstrator",
    disclaimer=(
        "Simplified demonstrator turn-taking rules for testing the engine only. Not derived "
        "from or verified against the StPO/GVG or any courtroom practice; not legal advice."
    ),
)


def _procedural(rule_id: str, description: str) -> RuleFinding:
    return RuleFinding(rule_id=rule_id, description=description, severity="procedural")


class DemoFloorRuleset:
    @property
    def metadata(self) -> RulesetMetadata:
        return DEMO_FLOOR_METADATA

    def evaluate(self, context: RuleContext, action: Action) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        if not context.floor_enabled:  # pragma: no cover - the engine only calls it enabled
            return findings
        if (
            isinstance(action, Speak)
            and context.actor_role != Role.JUDGE
            and not context.actor_holds_floor
        ):
            findings.append(_procedural(
                "DEMO_FLOOR_SPEAK", "Speech without holding the demonstrator floor"
            ))
        if isinstance(action, RequestFloor | AdvanceFloor) and context.phase == Phase.FINISHED:
            findings.append(_procedural(
                "DEMO_FLOOR_FINISHED", "Floor activity after close of demonstrator proceeding"
            ))
        return findings
