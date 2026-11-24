"""Deterministic kernel; illustrative, NOT a validated model of German proceedings.

The engine owns state, security checks and acceptance. Procedural checks are delegated to
a ``JurisdictionRuleset`` that sees only an immutable snapshot and may return procedural
findings; it can neither mutate state nor relax actor authority, evidence ACLs or
structural reference checks.
"""

from collections.abc import Iterable, Mapping

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
    SubmitEvidence,
    TrialEvent,
)
from indubio.core.projection import PerspectiveProjection, build_projection
from indubio.evidence.models import EvidenceRecord
from indubio.evidence.registry import EvidenceRegistry
from indubio.jurisdictions.base import JurisdictionRuleset, RuleContext
from indubio.jurisdictions.registry import get_ruleset


def _snapshot_acl(
    available_evidence: Mapping[str, Iterable[str]], known_actor_ids: Iterable[str]
) -> dict[str, frozenset[str]]:
    known = set(known_actor_ids)
    acl: dict[str, frozenset[str]] = {}
    for actor_id, ids in available_evidence.items():
        if actor_id not in known:
            raise ValueError(f"Evidence ACL names unknown actor: {actor_id!r}")
        # A bare string would otherwise be split into single-character evidence IDs.
        if isinstance(ids, (str, bytes)):
            raise TypeError("Evidence ACL values must be collections of evidence IDs")
        snapshot = frozenset(ids)
        if not all(isinstance(evidence_id, str) and evidence_id for evidence_id in snapshot):
            raise TypeError("Evidence IDs must be non-empty strings")
        acl[actor_id] = snapshot
    return acl


class SimulationEngine:
    def __init__(
        self,
        actors: Iterable[Actor],
        config: SimulationConfig | None = None,
        available_evidence: Mapping[str, Iterable[str]] | None = None,
        *,
        ruleset: JurisdictionRuleset | None = None,
        evidence: EvidenceRegistry | None = None,
    ) -> None:
        # Snapshot caller-owned models so later mutation cannot change authority.
        actor_list = [actor.model_copy(deep=True) for actor in actors]
        self._actors: dict[str, Actor] = {actor.actor_id: actor for actor in actor_list}
        if len(self._actors) != len(actor_list):
            raise ValueError("Duplicate actor IDs")
        self.config = (config or SimulationConfig()).model_copy(deep=True)
        if ruleset is None:
            ruleset = get_ruleset(self.config.jurisdiction)
        if not isinstance(ruleset, JurisdictionRuleset):
            raise TypeError("ruleset must implement JurisdictionRuleset")
        # Metadata is frozen; pin it once so every event carries the same provenance.
        self._ruleset_metadata = ruleset.metadata.model_copy(deep=True)
        if self._ruleset_metadata.ruleset_id != self.config.jurisdiction:
            raise ValueError("Ruleset ID does not match SimulationConfig.jurisdiction")
        self._ruleset = ruleset
        self.phase = Phase.OPENING
        self._events: list[TrialEvent] = []
        self._motions: dict[str, str] = {}
        if available_evidence is not None and evidence is not None:
            raise ValueError("Pass either an evidence registry or a legacy ACL, not both")
        if evidence is not None and not isinstance(evidence, EvidenceRegistry):
            raise TypeError("evidence must be an EvidenceRegistry")
        # Engine-owned snapshot: views and the ACL below derive from this one stable
        # record set, never from the caller's instance.
        self._evidence = evidence.snapshot() if evidence is not None else EvidenceRegistry()
        if evidence is not None:
            unknown = self._evidence.actor_ids() - self._actors.keys()
            if unknown:
                raise ValueError(f"Evidence registry names unknown actors: {sorted(unknown)}")
            # Derived from scoped views, so hidden truth is never submittable.
            self._evidence_acl = {
                actor_id: self._evidence.accessible_ids(actor_id) for actor_id in self._actors
            }
        else:
            # Legacy pattern: bare per-actor ID grants without records (snapshotted).
            self._evidence_acl = _snapshot_acl(available_evidence or {}, self._actors)

    @property
    def ruleset(self) -> JurisdictionRuleset:
        return self._ruleset

    def evidence_view(self, actor_id: str) -> list[EvidenceRecord]:
        """Detached copies of the records visible to a known actor; never hidden truth."""
        if actor_id not in self._actors:
            raise PermissionError("Unknown actor")
        return self._evidence.visible_to(actor_id)

    def perspective(self, actor_id: str) -> PerspectiveProjection:
        """Deterministic, redacted view of the committed history for one known actor.

        Fails closed for unknown actors. See ``indubio.core.projection`` for the policy;
        ``events`` remains the trusted, unredacted audit history.
        """
        return build_projection(
            actor_id,
            actors=self._actors,
            events=self._events,
            evidence_acl=self._evidence_acl,
            evidence=self._evidence,
            phase=self.phase,
            ruleset=self._ruleset_metadata,
        )

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

        # Procedural checks come from the ruleset, which sees only a frozen snapshot.
        context = RuleContext(
            mode=self.config.mode,
            phase=self.phase,
            committed_event_count=len(self._events),
            motion_ids=frozenset(self._motions),
            actor_role=actor.role,
        )
        ruleset_findings = self._ruleset.evaluate(context, action.model_copy(deep=True))
        for finding in ruleset_findings:
            if not isinstance(finding, RuleFinding) or finding.severity != "procedural":
                # Rulesets must not create, or claim to waive, security findings.
                raise TypeError("Rulesets may only return procedural RuleFinding objects")
            findings.append(finding.model_copy(deep=True))

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
                      "ruleset": self._ruleset_metadata.ruleset_id,
                      "ruleset_version": self._ruleset_metadata.version,
                      "ruleset_validation": self._ruleset_metadata.validation_status},
        )
        self._events.append(event)
        return event.model_copy(deep=True)
