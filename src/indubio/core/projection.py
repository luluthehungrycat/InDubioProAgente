"""Deterministic per-actor perspective projections over committed events.

A projection is what one known actor may see of the proceeding. It is derived purely
from trusted inputs (committed events, the actor registry, the engine's evidence ACL and
its scoped ``EvidenceRegistry`` snapshot); the same inputs always yield an equal
projection. Projections are read-only views: they never mutate engine state and are
never the source of a legal decision. The trusted audit history (``engine.events`` and
the SQLite journal) is unchanged and keeps every field.

Visibility policy (conservative, fail closed):

* **Unknown viewer** -> ``PermissionError``. An event naming an actor outside the
  registry -> ``ValueError``; no partial projection is returned.
* **Own events** (``OWN``): the viewer's full proposal, accepted or rejected. Rule
  findings are included only on the viewer's own *rejected* events, to explain the
  rejection. Findings on accepted events are evaluator/audit data and are not projected
  to any actor (a realistic-mode finding is not a judicial determination and must not
  turn into actor knowledge).
* **Other actors' accepted events** (``PUBLIC`` / ``PUBLIC_REDACTED``): author, role,
  phase change and action. Per-kind field allowlist; a ``SubmitEvidence`` evidence ID
  is shown only if the viewer may itself access that ID, otherwise the action payload is
  withheld and ``redacted_fields`` names what was removed. Findings are never shown.
* **Other actors' rejected events** (``WITHHELD``): a rejected attempt is not an act of
  the proceeding. Only the global sequence number and the (unchanged) phase remain; the
  author, action kind, payload and findings are withheld. The existence and position of
  a withheld attempt is therefore visible, which is also inferable from sequence numbers.
* **Unrecognised action kinds** are withheld from everyone except their author.
* Engine metadata (simulation mode, etc.) and ``Actor.human_controlled`` are not
  projected. Ruleset identity and validation status are, so a viewer is never misled
  about the rule pack's status.

Trust boundary of free text: ``Speak.text``, ``FileMotion.grounds``,
``RuleOnMotion.reasons`` and ``Object.grounds`` are actor-authored, untrusted strings.
Redaction here is structural only; free text in a public accepted event is passed
through verbatim and is *not* scanned for evidence IDs, hidden facts or instructions.
Anything an actor writes into accepted free text is published by that actor's own act.
Consumers (adapters, UIs, prompts) must treat it as untrusted data.

Trust boundary of legacy ID ACLs: when the engine was built with the legacy
``available_evidence`` mapping there are no records. The viewer's granted IDs are then
trusted, caller-asserted setup input: they are projected as ``accessible_evidence_ids``
(and govern evidence-ID redaction) with no record content and no epistemic-layer
check, because there is no record to check. Use an ``EvidenceRegistry`` for sealed
hidden truth.

Projected evidence records omit ``visible_to_actor_ids`` so a viewer does not learn who
else holds a record.

Disclosure events (``DiscloseEvidence``, policy in ``indubio.core.disclosure``):

* Discloser: ``OWN`` as for any event. Recipient of an **accepted** disclosure:
  ``RECIPIENT`` with author, role and full action. Everyone else, and the named recipient
  of a *rejected* disclosure: ``WITHHELD``. Disclosure is a private act between two
  actors, not a public courtroom act.
* Grants are derived from accepted disclosures in the trusted history and revalidated;
  a history the engine could not have produced raises ``ValueError``.
* **Event-time versus current visibility.** ``accessible_evidence_ids`` and ``evidence``
  reflect *current* access (scenario grants plus all accepted disclosures). Redaction of
  an individual event uses the viewer's access *as of that event* (grants from strictly
  earlier events). A later disclosure therefore never retroactively un-redacts an earlier
  ``SubmitEvidence`` event: receiving a record is not learning which act, earlier, used
  it. Records received by disclosure carry ``disclosed_at_sequence``.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from indubio.core.disclosure import access_at, derive_grants, is_disclosable_record
from indubio.core.models import (
    Action,
    Actor,
    DiscloseEvidence,
    FileMotion,
    MovePhase,
    Object,
    Phase,
    Role,
    RuleFinding,
    RuleOnMotion,
    Speak,
    SubmitEvidence,
    TrialEvent,
)
from indubio.evidence.models import EpistemicLayer
from indubio.evidence.registry import EvidenceRegistry
from indubio.jurisdictions.base import RulesetMetadata


class EventVisibility(StrEnum):
    OWN = "own"
    PUBLIC = "public"
    PUBLIC_REDACTED = "public_redacted"
    RECIPIENT = "recipient"
    WITHHELD = "withheld"


class ProjectedParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str
    role: Role
    display_name: str


class ProjectedEvidence(BaseModel):
    """A record the viewer may see, without the list of other actors who may see it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    summary: str
    layer: EpistemicLayer
    provenance: str | None = None
    source_timestamp: str | None = None
    # Set only for records the viewer holds because of a disclosure event, not a
    # scenario grant: the sequence of the first accepted disclosure to the viewer.
    disclosed_at_sequence: int | None = Field(default=None, ge=1)


class ProjectedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    visibility: EventVisibility
    phase_before: Phase
    phase_after: Phase
    actor_id: str | None = None
    actor_role: Role | None = None
    accepted: bool | None = None
    action_kind: str | None = None
    action: Action | None = None
    redacted_fields: tuple[str, ...] = ()
    findings: tuple[RuleFinding, ...] = ()


class PerspectiveProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    viewer_actor_id: str
    viewer_role: Role
    phase: Phase
    committed_event_count: int = Field(ge=0)
    ruleset_id: str
    ruleset_version: str
    ruleset_validation: str
    participants: tuple[ProjectedParticipant, ...]
    accessible_evidence_ids: tuple[str, ...]
    evidence: tuple[ProjectedEvidence, ...]
    events: tuple[ProjectedEvent, ...]


# Action kinds whose accepted form may be shown to other actors. Anything else is
# withheld from non-authors (fail closed when a new kind is added).
_PUBLIC_KINDS = (Speak, MovePhase, FileMotion, RuleOnMotion, Object, SubmitEvidence)


def _project_event(
    event: TrialEvent,
    viewer: Actor,
    actors: Mapping[str, Actor],
    viewer_evidence_ids: frozenset[str],
) -> ProjectedEvent:
    author = actors.get(event.actor_id)
    if author is None or event.proposal.actor_id != event.actor_id:
        raise ValueError(f"Event {event.sequence} names an unknown or inconsistent actor")
    base = {
        "sequence": event.sequence,
        "phase_before": event.phase_before,
        "phase_after": event.phase_after,
    }
    action = event.proposal.action

    if author.actor_id == viewer.actor_id:
        return ProjectedEvent(
            **base,
            visibility=EventVisibility.OWN,
            actor_id=author.actor_id,
            actor_role=author.role,
            accepted=event.accepted,
            action_kind=action.kind,
            action=action.model_copy(deep=True),
            findings=() if event.accepted else tuple(
                finding.model_copy(deep=True) for finding in event.findings
            ),
        )

    if (
        isinstance(action, DiscloseEvidence)
        and event.accepted
        and action.recipient_actor_id == viewer.actor_id
    ):
        return ProjectedEvent(
            **base,
            visibility=EventVisibility.RECIPIENT,
            actor_id=author.actor_id,
            actor_role=author.role,
            accepted=True,
            action_kind=action.kind,
            action=action.model_copy(deep=True),
        )

    if not event.accepted or not isinstance(action, _PUBLIC_KINDS):
        return ProjectedEvent(**base, visibility=EventVisibility.WITHHELD)

    public = {
        **base,
        "actor_id": author.actor_id,
        "actor_role": author.role,
        "accepted": True,
        "action_kind": action.kind,
    }
    if isinstance(action, SubmitEvidence) and action.evidence_id not in viewer_evidence_ids:
        return ProjectedEvent(
            **public,
            visibility=EventVisibility.PUBLIC_REDACTED,
            redacted_fields=("evidence_id",),
        )
    return ProjectedEvent(
        **public, visibility=EventVisibility.PUBLIC, action=action.model_copy(deep=True)
    )


def build_projection(
    viewer_actor_id: str,
    *,
    actors: Mapping[str, Actor],
    events: Sequence[TrialEvent],
    evidence_acl: Mapping[str, frozenset[str]],
    evidence: EvidenceRegistry,
    phase: Phase,
    ruleset: RulesetMetadata,
) -> PerspectiveProjection:
    """Pure projection from trusted inputs; callers must not pass actor-supplied state."""
    viewer = actors.get(viewer_actor_id)
    if viewer is None:
        raise PermissionError("Unknown actor: no projection is available")
    expected = 1
    for event in events:
        if event.sequence != expected:
            raise ValueError("Events must be the complete committed history in order")
        expected += 1
    timeline = derive_grants(events, actors=actors, base_acl=evidence_acl, registry=evidence)
    viewer_ids = access_at(viewer.actor_id, evidence_acl, timeline[-1])
    scenario_ids = evidence.accessible_ids(viewer.actor_id)
    received = timeline[-1].get(viewer.actor_id, {})
    records = []
    for evidence_id in evidence:  # trusted registry order; filtered to the viewer below
        if evidence_id in scenario_ids:
            disclosed_at = None
        elif evidence_id in received and is_disclosable_record(evidence, evidence_id):
            disclosed_at = received[evidence_id]
        else:
            continue
        record = evidence.get(evidence_id)
        records.append(ProjectedEvidence(
            evidence_id=record.evidence_id,
            summary=record.summary,
            layer=record.layer,
            provenance=record.provenance,
            source_timestamp=record.source_timestamp,
            disclosed_at_sequence=disclosed_at,
        ))
    return PerspectiveProjection(
        viewer_actor_id=viewer.actor_id,
        viewer_role=viewer.role,
        phase=phase,
        committed_event_count=len(events),
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.version,
        ruleset_validation=ruleset.validation_status,
        participants=tuple(
            ProjectedParticipant(
                actor_id=actor.actor_id, role=actor.role, display_name=actor.display_name
            )
            for actor in sorted(actors.values(), key=lambda actor: actor.actor_id)
        ),
        accessible_evidence_ids=tuple(sorted(viewer_ids)),
        evidence=tuple(records),
        events=tuple(
            # Event-time access: grants from strictly earlier events only.
            _project_event(event, viewer, actors,
                           access_at(viewer.actor_id, evidence_acl, before))
            for event, before in zip(events, timeline, strict=False)
        ),
    )
