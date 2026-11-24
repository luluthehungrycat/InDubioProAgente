"""Demonstrator evidence-disclosure policy and grant derivation.

Illustrative only: NOT derived from the StPO (e.g. rules on file inspection) or any other
verified source, and not legal advice.

Who may disclose, to whom (structural, enforced as ``security`` findings in every mode):

* Discloser roles: ``judge``, ``prosecutor``, ``defense`` (``DISCLOSER_ROLES``).
* Recipient roles: ``judge``, ``prosecutor``, ``defense``, ``defendant``
  (``RECIPIENT_ROLES``). Witnesses and observers can never receive a disclosure here.
* The recipient must be a known actor other than the discloser.
* The discloser must *currently* be able to access the evidence ID (scenario grant or an
  earlier accepted disclosure) and the ID must be backed by a non-hidden registry record.
  Unknown, inaccessible and hidden-truth IDs produce the same ``ACL_EVIDENCE`` finding, so
  a rejection is no oracle for which sealed IDs exist. Legacy bare-ID grants carry no
  record and cannot be disclosed (``DISCLOSE_RECORD_REQUIRED``).

When (procedural, from the ruleset): the demonstrator pack reports
``DEMO_DISCLOSURE_PHASE`` outside the opening and evidence phases. Strict mode rejects;
realistic mode records the disclosure as an actual (accepted) event that keeps the
finding, so the record shows the late disclosure happened and that it was flagged.

Effects: only an **accepted** event grants access. A rejected disclosure never changes
visibility, in any mode. A disclosure to a recipient who already holds the record is
accepted and changes nothing; rejecting it would reveal to the discloser who else holds
the record. Grants are derived from the trusted committed history, so a journal round
trip reproduces them; they never alter the immutable ``EvidenceRecord``.
"""

from collections.abc import Mapping, Sequence

from indubio.core.models import Actor, DiscloseEvidence, Role, TrialEvent
from indubio.evidence.models import EpistemicLayer
from indubio.evidence.registry import EvidenceRegistry

DISCLOSER_ROLES = frozenset({Role.JUDGE, Role.PROSECUTOR, Role.DEFENSE})
RECIPIENT_ROLES = frozenset({Role.JUDGE, Role.PROSECUTOR, Role.DEFENSE, Role.DEFENDANT})

# actor_id -> {evidence_id: sequence of the first accepted disclosure to that actor}
Grants = dict[str, dict[str, int]]


def is_disclosable_record(registry: EvidenceRegistry, evidence_id: str) -> bool:
    record = registry.get(evidence_id)
    return record is not None and record.layer != EpistemicLayer.HIDDEN_TRUTH


def access_at(
    actor_id: str, base_acl: Mapping[str, frozenset[str]], grants: Grants
) -> frozenset[str]:
    return frozenset(base_acl.get(actor_id, frozenset())) | frozenset(grants.get(actor_id, {}))


def derive_grants(
    events: Sequence[TrialEvent],
    *,
    actors: Mapping[str, Actor],
    base_acl: Mapping[str, frozenset[str]],
    registry: EvidenceRegistry,
) -> Grants:
    """Grants from all accepted disclosures in ``events``, in one linear pass.

    Each grant records the sequence of the first accepted disclosure to that actor, so
    the grants in force *before* event ``n`` are exactly those with sequence ``< n``;
    callers derive event-time access from that instead of copying the whole grant map
    per event. Revalidates every accepted disclosure against the structural policy and
    raises ``ValueError`` on a history the engine could not have produced (fail closed).
    """
    grants: Grants = {}
    for event in events:
        action = event.proposal.action
        if not (event.accepted and isinstance(action, DiscloseEvidence)):
            continue
        discloser = actors.get(event.actor_id)
        recipient = actors.get(action.recipient_actor_id)
        if (
            discloser is None
            or recipient is None
            or recipient.actor_id == discloser.actor_id
            or discloser.role not in DISCLOSER_ROLES
            or recipient.role not in RECIPIENT_ROLES
            or not is_disclosable_record(registry, action.evidence_id)
            # ``grants`` holds only strictly earlier events here: event-time access.
            or action.evidence_id not in access_at(discloser.actor_id, base_acl, grants)
        ):
            raise ValueError(f"Event {event.sequence} is not a valid accepted disclosure")
        grants.setdefault(recipient.actor_id, {}).setdefault(action.evidence_id, event.sequence)
    return grants
