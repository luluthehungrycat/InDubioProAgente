"""Opt-in speaking queue and floor lifecycle (demonstrator semantics ``indubio.floor/1``).

Illustrative only: NOT derived from the StPO, GVG or any other verified source, and not
legal advice. Floor control is a deterministic turn-taking mechanism for text sessions;
it does not model who may legally address a court.

**Opt-in.** An engine has floor control only when built with a floor ruleset
(``SimulationEngine(..., floor_rules=...)``, ``build_engine(..., floor_rules=ID)``).
Without one, behavior is exactly as before: there is no queue, ``Speak`` is unscheduled,
and every floor action is rejected with ``FLOOR_DISABLED`` in every mode.

**State** (``FloorState``): at most one ``holder`` and a FIFO ``queue`` of actor IDs.
An actor appears at most once across holder and queue. State changes only through
accepted events, applied atomically with the event's append:

==========================  ===============================================================
Accepted action             Transition
==========================  ===============================================================
``request_floor``           proposer appended to the end of the queue
``withdraw_floor_request``  proposer removed from the queue; order of others unchanged
``release_floor``           holder cleared; queue unchanged (nobody is granted the floor)
``advance_floor``           holder (if any) ends; queue head becomes holder (strict FIFO)
``move_phase`` (boundary)   when the phase actually changes: holder and queue cleared
anything else               no change (``speak`` never consumes or grants the floor)
==========================  ===============================================================

**Structural checks** (``security`` severity, so they reject in *every* mode, and no
ruleset or simulation setting relaxes them), evaluated against the state before the
proposal:

* ``FLOOR_DISABLED``: a floor action on an engine without floor control.
* ``FLOOR_DUPLICATE_REQUEST``: ``request_floor`` by an actor already queued or holding
  the floor. There is no second place in line and no re-queueing behind oneself.
* ``FLOOR_NOT_QUEUED``: ``withdraw_floor_request`` by an actor not in the queue.
* ``FLOOR_NOT_HOLDER``: ``release_floor`` by an actor not holding the floor.
* ``FLOOR_QUEUE_EMPTY``: ``advance_floor`` with nobody queued (the current holder, if
  any, keeps the floor; ending a floor without a successor is ``release_floor``).

Role checks live in ``indubio.core.authorization`` (also unconditional). Procedural
checks (e.g. speaking without the floor) belong to the versioned floor ruleset, which
only returns ``procedural`` findings: in strict mode they reject, in realistic mode the
event is recorded with its finding. A recorded-but-improper act is still not lawful, and
an accepted ``speak`` without the floor does not grant the floor.

Phase boundaries are engine lifecycle, not procedure: pending requests and the floor do
not carry over into the next phase.

The state is derivable from the committed history alone (``derive_floor``), which the
projection uses and which must agree with the engine's live state; a history the engine
could not have produced raises ``ValueError``.
"""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from indubio.core.models import (
    AdvanceFloor,
    MovePhase,
    ReleaseFloor,
    RequestFloor,
    RuleFinding,
    TrialEvent,
    WithdrawFloorRequest,
)

FLOOR_SEMANTICS = "indubio.floor/1"
FLOOR_ACTION_TYPES: tuple[type[BaseModel], ...] = (
    RequestFloor, WithdrawFloorRequest, ReleaseFloor, AdvanceFloor,
)


class FloorState(BaseModel):
    """Immutable floor snapshot: the holder and the FIFO queue of waiting actor IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    holder: str | None = Field(default=None, min_length=1)
    queue: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> "FloorState":
        members = list(self.queue) + ([self.holder] if self.holder is not None else [])
        if len(set(members)) != len(members):
            raise ValueError("An actor may appear at most once in the floor state")
        return self


def _security(rule_id: str, description: str) -> RuleFinding:
    return RuleFinding(rule_id=rule_id, description=description, severity="security")


def is_floor_action(action: object) -> bool:
    return type(action) in FLOOR_ACTION_TYPES


def structural_findings(
    state: FloorState | None, actor_id: str, action: object
) -> list[RuleFinding]:
    """Unconditional structural findings for ``action`` against ``state`` (``None``: off)."""
    if not is_floor_action(action):
        return []
    if state is None:
        return [_security("FLOOR_DISABLED", "Floor control is not enabled for this run")]
    if isinstance(action, RequestFloor) and (
        actor_id == state.holder or actor_id in state.queue
    ):
        return [_security("FLOOR_DUPLICATE_REQUEST",
                          "Actor is already queued for or holding the floor")]
    if isinstance(action, WithdrawFloorRequest) and actor_id not in state.queue:
        return [_security("FLOOR_NOT_QUEUED", "Actor has no pending floor request")]
    if isinstance(action, ReleaseFloor) and actor_id != state.holder:
        return [_security("FLOOR_NOT_HOLDER", "Actor does not hold the floor")]
    if isinstance(action, AdvanceFloor) and not state.queue:
        return [_security("FLOOR_QUEUE_EMPTY", "No floor request is pending")]
    return []


def transition(
    state: FloorState, actor_id: str, action: object, *, phase_changed: bool
) -> FloorState:
    """The state after an *accepted* event; the caller has run ``structural_findings``."""
    if isinstance(action, MovePhase) and phase_changed:
        return FloorState()
    if isinstance(action, RequestFloor):
        return FloorState(holder=state.holder, queue=(*state.queue, actor_id))
    if isinstance(action, WithdrawFloorRequest):
        return FloorState(
            holder=state.holder, queue=tuple(a for a in state.queue if a != actor_id)
        )
    if isinstance(action, ReleaseFloor):
        return FloorState(queue=state.queue)
    if isinstance(action, AdvanceFloor):
        return FloorState(holder=state.queue[0], queue=state.queue[1:])
    return state


def derive_floor(events: Iterable[TrialEvent]) -> FloorState:
    """Floor state after a complete, ordered committed history of a floor-enabled run.

    Raises ``ValueError`` if an accepted floor event is structurally impossible at its
    position (a history the engine could not have produced).
    """
    state = FloorState()
    for event in events:
        if not event.accepted:
            continue
        action = event.proposal.action
        if structural_findings(state, event.actor_id, action):
            raise ValueError(f"Event {event.sequence} is an impossible floor transition")
        state = transition(
            state, event.actor_id, action,
            phase_changed=event.phase_after != event.phase_before,
        )
    return state


__all__ = [
    "FLOOR_ACTION_TYPES",
    "FLOOR_SEMANTICS",
    "FloorState",
    "derive_floor",
    "is_floor_action",
    "structural_findings",
    "transition",
]
