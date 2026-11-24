"""Deterministic kernel; illustrative, NOT a validated model of German proceedings."""

from collections.abc import Iterable

from indubio.core.models import (
    PHASES,
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
    TrialEvent,
)


class SimulationEngine:
    def __init__(
        self,
        actors: Iterable[Actor],
        config: SimulationConfig | None = None,
        available_evidence: dict[str, set[str]] | None = None,
    ) -> None:
        # Snapshot caller-owned models so later mutation cannot change authority.
        actor_list = [actor.model_copy(deep=True) for actor in actors]
        self._actors: dict[str, Actor] = {actor.actor_id: actor for actor in actor_list}
        if len(self._actors) != len(actor_list):
            raise ValueError("Duplicate actor IDs")
        self.config = config or SimulationConfig()
        self.phase = Phase.OPENING
        self._events: list[TrialEvent] = []
        self._motions: dict[str, str] = {}
        # The engine receives only the per-actor evidence IDs it is permitted to show.
        self._evidence_acl: dict[str, frozenset[str]] = {
            actor_id: frozenset(ids) for actor_id, ids in (available_evidence or {}).items()
        }

    @property
    def actors(self) -> dict[str, Actor]:
        """Detached copies of the actor registry; editing them cannot change authority."""
        return {actor_id: actor.model_copy(deep=True) for actor_id, actor in self._actors.items()}

    @property
    def events(self) -> list[TrialEvent]:
        """Copies of the committed history; editing them cannot rewrite the record."""
        return [event.model_copy(deep=True) for event in self._events]

    def propose(self, proposal: Proposal) -> TrialEvent:
        # Validate and record a private snapshot, never the caller's mutable object.
        proposal = proposal.model_copy(deep=True)
        actor = self._actors.get(proposal.actor_id)
        if actor is None:
            raise PermissionError("Unknown actor: no event was committed")

        action = proposal.action
        findings: list[RuleFinding] = []

        def security(rule_id: str, description: str) -> None:
            findings.append(RuleFinding(rule_id=rule_id, description=description,
                                        severity="security"))

        def procedural(rule_id: str, description: str) -> None:
            findings.append(RuleFinding(rule_id=rule_id, description=description,
                                        severity="procedural"))

        # Never loosen security or actor authority merely by selecting realistic mode.
        if isinstance(action, SubmitEvidence):
            if action.evidence_id not in self._evidence_acl.get(actor.actor_id, frozenset()):
                security("ACL_EVIDENCE", "Actor cannot access or introduce this evidence ID")
        if isinstance(action, RuleOnMotion) and actor.role != Role.JUDGE:
            security("AUTH_RULING", "Only a judge can issue rulings")
        if isinstance(action, MovePhase) and actor.role != Role.JUDGE:
            security("AUTH_PHASE", "Only a judge can direct phase transitions")
        if isinstance(action, FileMotion) and actor.role not in {
            Role.DEFENSE, Role.PROSECUTOR, Role.DEFENDANT
        }:
            security("AUTH_MOTION", "Role cannot file motions in this starter model")
        if isinstance(action, Object) and actor.role not in {
            Role.DEFENSE, Role.PROSECUTOR, Role.DEFENDANT
        }:
            security("AUTH_OBJECTION", "Role cannot lodge objections in starter model")
        if isinstance(action, Object) and not (
            1 <= action.target_event_sequence <= len(self._events)
        ):
            security("REFERENCE_EVENT", "Target event does not exist")

        # Simplified demonstrator rules. NOT German procedural-law conformance.
        if isinstance(action, MovePhase):
            current = PHASES.index(self.phase)
            target = PHASES.index(action.destination)
            if target != current + 1:
                procedural("DEMO_PHASE_ORDER", "Unexpected phase transition")
        if isinstance(action, RuleOnMotion) and action.motion_id not in self._motions:
            procedural("DEMO_MOTION_MISSING", "Ruling refers to an unknown motion")
        if isinstance(action, FileMotion) and action.motion_id in self._motions:
            procedural("DEMO_MOTION_DUPLICATE", "Motion ID already exists")
        if isinstance(action, SubmitEvidence) and self.phase != Phase.EVIDENCE:
            procedural("DEMO_EVIDENCE_PHASE", "Evidence submitted outside demonstrator phase")
        if isinstance(action, Speak) and self.phase == Phase.FINISHED:
            procedural("DEMO_AFTER_FINISH", "Speech after close of demonstrator proceeding")

        blocked_by_security = any(f.severity == "security" for f in findings)
        blocked_by_procedure = (
            self.config.mode == Mode.STRICT and
            any(f.severity == "procedural" for f in findings)
        )
        accepted = not (blocked_by_security or blocked_by_procedure)
        before = self.phase

        if accepted:
            if isinstance(action, MovePhase):
                self.phase = action.destination
            if isinstance(action, FileMotion):
                self._motions[action.motion_id] = actor.actor_id

        event = TrialEvent(
            sequence=len(self._events) + 1,
            actor_id=actor.actor_id,
            phase_before=before,
            phase_after=self.phase,
            proposal=proposal,
            accepted=accepted,
            findings=findings,
            metadata={"mode": self.config.mode.value,
                      "ruleset": self.config.jurisdiction},
        )
        self._events.append(event)
        return event.model_copy(deep=True)
