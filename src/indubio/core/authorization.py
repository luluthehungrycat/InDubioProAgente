"""Authoritative per-role action authorization (demonstrator starter model).

Illustrative only: NOT derived from the StPO, GVG or any other verified source, and not
legal advice. This is a *security* layer (who may submit which action kind at all), kept
separate from:

* procedural rules in the jurisdiction ruleset (``indubio.jurisdictions``), which only
  return ``procedural`` findings and can never grant or waive authority;
* evidence ACL and structural reference checks in the engine (``ACL_EVIDENCE``,
  ``REFERENCE_EVENT``, ``REFERENCE_ACTOR``, ``DISCLOSE_RECORD_REQUIRED``).

Every finding produced here has ``security`` severity, so it rejects the proposal in
every mode; no simulation setting relaxes it.

Policy table (``ACTION_POLICY``):

========================  ==========================================  =========================
Action kind               Allowed roles                                Denial rule ID
========================  ==========================================  =========================
``speak``                 judge, prosecutor, defense, defendant,       ``AUTH_SPEAK``
                          witness
``submit_evidence``       judge, prosecutor, defense, defendant,       ``AUTH_SUBMIT_EVIDENCE``
                          witness
``move_phase``            judge                                        ``AUTH_PHASE``
``rule_on_motion``        judge                                        ``AUTH_RULING``
``file_motion``           prosecutor, defense, defendant               ``AUTH_MOTION``
``object``                prosecutor, defense, defendant               ``AUTH_OBJECTION``
``disclose_evidence``     judge, prosecutor, defense                   ``AUTH_DISCLOSE``
``request_floor``         prosecutor, defense, defendant, witness      ``AUTH_FLOOR_REQUEST``
``withdraw_floor_request`` prosecutor, defense, defendant, witness     ``AUTH_FLOOR_WITHDRAW``
``release_floor``         prosecutor, defense, defendant, witness      ``AUTH_FLOOR_RELEASE``
``advance_floor``         judge                                        ``AUTH_FLOOR_ADVANCE``
========================  ==========================================  =========================

Floor actions (opt-in, ``indubio.core.floor``): the presiding judge is never queued and
alone advances the queue; the other participants queue, withdraw and release. The
passive observer has none. Whether floor control is enabled, and whether the proposer is
queued or holding the floor, are structural checks in the engine (``FLOOR_*``), not role
questions; speaking without the floor is a procedural question for the floor ruleset.

Disclosure recipients (``DISCLOSURE_RECIPIENT_ROLES``): judge, prosecutor, defense,
defendant; otherwise ``AUTH_DISCLOSE_RECIPIENT``. Whether the recipient is a known actor
other than the discloser is a structural reference check (``REFERENCE_ACTOR``) in the
engine, not a role question.

**Passive observer.** ``human_observer`` is a passive role: it may hold a perspective
(``engine.perspective``) but is authorized for *no* action kind. Before this table existed,
``speak`` and ``submit_evidence`` had no role check, so an observer could speak or (with an
evidence grant) submit evidence; both are now rejected with ``AUTH_SPEAK`` /
``AUTH_SUBMIT_EVIDENCE``. This is an intentional correction. All other role permissions
are unchanged, including witness speech and witness evidence submission (still gated by
the evidence ACL).

**Fail closed.** Authorization is looked up by the action's exact registered model class.
A canonical ``Action`` schema member without a policy entry here (for example a new union
member added without one) is denied with ``AUTH_ACTION_UNREGISTERED`` for every role, as
a normal rejected event that persists and reloads from the journal. A role outside a
permission's set is denied; there is no default-allow. The table may only name schema
members (``models.ACTION_TYPES``); this is checked at import.

Runtime objects *outside* the schema (a subclass of a registered model, a foreign object,
``None``) never reach this table through the engine: ``SimulationEngine.propose`` refuses
them at the proposal boundary with ``TypeError`` before the ruleset runs or any event or
state exists, because they could not be journaled faithfully. The pure lookups below
still return "no permission" for them.

**Finding order.** The role finding, if any, is reported first and the engine's evidence
and reference checks still run afterwards, matching the order the engine used before this
table was extracted (e.g. ``["AUTH_DISCLOSE_RECIPIENT", "ACL_EVIDENCE"]``).
"""

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from indubio.core.models import (
    ACTION_TYPES,
    AdvanceFloor,
    DiscloseEvidence,
    FileMotion,
    MovePhase,
    Object,
    ReleaseFloor,
    RequestFloor,
    Role,
    RuleFinding,
    RuleOnMotion,
    Speak,
    SubmitEvidence,
    WithdrawFloorRequest,
)

UNREGISTERED_ACTION_RULE_ID = "AUTH_ACTION_UNREGISTERED"
UNREGISTERED_ACTION_DESCRIPTION = "Action kind has no authorization policy in this starter model"


class ActionPermission(BaseModel):
    """Which roles may submit one action kind, and the finding issued otherwise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1)
    allowed_roles: frozenset[Role]
    rule_id: str = Field(min_length=1)
    description: str = Field(min_length=1)

    def permits(self, role: Role) -> bool:
        return role in self.allowed_roles


_PARTICIPANTS = frozenset({
    Role.JUDGE, Role.PROSECUTOR, Role.DEFENSE, Role.DEFENDANT, Role.WITNESS,
})
_PARTIES = frozenset({Role.PROSECUTOR, Role.DEFENSE, Role.DEFENDANT})
_JUDGE = frozenset({Role.JUDGE})
_FLOOR_QUEUERS = frozenset({Role.PROSECUTOR, Role.DEFENSE, Role.DEFENDANT, Role.WITNESS})

# Rule IDs and descriptions of pre-existing checks are kept verbatim for audit continuity.
ACTION_POLICY: Mapping[type[BaseModel], ActionPermission] = MappingProxyType({
    Speak: ActionPermission(
        kind="speak", allowed_roles=_PARTICIPANTS, rule_id="AUTH_SPEAK",
        description="Role cannot speak in this starter model",
    ),
    SubmitEvidence: ActionPermission(
        kind="submit_evidence", allowed_roles=_PARTICIPANTS, rule_id="AUTH_SUBMIT_EVIDENCE",
        description="Role cannot submit evidence in this starter model",
    ),
    MovePhase: ActionPermission(
        kind="move_phase", allowed_roles=_JUDGE, rule_id="AUTH_PHASE",
        description="Only a judge can direct phase transitions",
    ),
    RuleOnMotion: ActionPermission(
        kind="rule_on_motion", allowed_roles=_JUDGE, rule_id="AUTH_RULING",
        description="Only a judge can issue rulings",
    ),
    FileMotion: ActionPermission(
        kind="file_motion", allowed_roles=_PARTIES, rule_id="AUTH_MOTION",
        description="Role cannot file motions in this starter model",
    ),
    Object: ActionPermission(
        kind="object", allowed_roles=_PARTIES, rule_id="AUTH_OBJECTION",
        description="Role cannot lodge objections in starter model",
    ),
    DiscloseEvidence: ActionPermission(
        kind="disclose_evidence",
        allowed_roles=frozenset({Role.JUDGE, Role.PROSECUTOR, Role.DEFENSE}),
        rule_id="AUTH_DISCLOSE",
        description="Role cannot disclose evidence in this starter model",
    ),
    RequestFloor: ActionPermission(
        kind="request_floor", allowed_roles=_FLOOR_QUEUERS, rule_id="AUTH_FLOOR_REQUEST",
        description="Role cannot request the floor in this starter model",
    ),
    WithdrawFloorRequest: ActionPermission(
        kind="withdraw_floor_request", allowed_roles=_FLOOR_QUEUERS,
        rule_id="AUTH_FLOOR_WITHDRAW",
        description="Role cannot withdraw a floor request in this starter model",
    ),
    ReleaseFloor: ActionPermission(
        kind="release_floor", allowed_roles=_FLOOR_QUEUERS, rule_id="AUTH_FLOOR_RELEASE",
        description="Role cannot release the floor in this starter model",
    ),
    AdvanceFloor: ActionPermission(
        kind="advance_floor", allowed_roles=_JUDGE, rule_id="AUTH_FLOOR_ADVANCE",
        description="Only a judge can advance the speaking queue",
    ),
})

if not set(ACTION_POLICY) <= set(ACTION_TYPES):  # pragma: no cover - import-time guard
    raise TypeError("ACTION_POLICY may only name Action schema members")

DISCLOSURE_RECIPIENT_ROLES = frozenset({
    Role.JUDGE, Role.PROSECUTOR, Role.DEFENSE, Role.DEFENDANT,
})
DISCLOSURE_RECIPIENT_RULE_ID = "AUTH_DISCLOSE_RECIPIENT"
DISCLOSURE_RECIPIENT_DESCRIPTION = (
    "Recipient role cannot receive disclosures in this starter model"
)


def permission_for(action: object) -> ActionPermission | None:
    """The registered permission for this exact action class, or ``None`` (deny)."""
    return ACTION_POLICY.get(type(action))  # type: ignore[call-overload]


def is_authorized(role: Role, action: object) -> bool:
    permission = permission_for(action)
    return permission is not None and permission.permits(role)


def can_receive_disclosure(role: Role) -> bool:
    return role in DISCLOSURE_RECIPIENT_ROLES


def _security(rule_id: str, description: str) -> RuleFinding:
    return RuleFinding(rule_id=rule_id, description=description, severity="security")


def authorization_finding(role: Role, action: object) -> RuleFinding | None:
    """The role-authorization ``security`` finding for this proposal, or ``None``."""
    permission = permission_for(action)
    if permission is None:
        return _security(UNREGISTERED_ACTION_RULE_ID, UNREGISTERED_ACTION_DESCRIPTION)
    if not permission.permits(role):
        return _security(permission.rule_id, permission.description)
    return None


def recipient_finding(role: Role) -> RuleFinding | None:
    if can_receive_disclosure(role):
        return None
    return _security(DISCLOSURE_RECIPIENT_RULE_ID, DISCLOSURE_RECIPIENT_DESCRIPTION)
