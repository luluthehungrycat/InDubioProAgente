"""Opt-in speaking queue, floor lifecycle and interrupt requests (``indubio.floor/1``).

Illustrative only: NOT derived from the StPO, GVG or any other verified source, and not
legal advice. Floor control is a deterministic turn-taking mechanism for text sessions;
it does not model who may legally address or interrupt a court.

**Opt-in.** An engine has floor control only when built with a floor ruleset
(``SimulationEngine(..., floor_rules=...)``, ``build_engine(..., floor_rules=ID)``).
Without one, behavior is exactly as before: there is no queue, ``Speak`` is unscheduled,
and every floor action (including the interrupt actions) is rejected with
``FLOOR_DISABLED`` in every mode.

**State** (``FloorState``): at most one ``holder``, a FIFO ``queue`` of actor IDs and the
``interrupts`` pending against the current holder. An actor appears at most once across
holder and queue, and has at most one pending interrupt request. State changes only
through accepted events, applied atomically with the event's append:

==========================  ===============================================================
Accepted action             Transition
==========================  ===============================================================
``request_floor``           proposer appended to the end of the queue
``withdraw_floor_request``  proposer removed from the queue; order of others unchanged
``release_floor``           holder cleared; queue unchanged (nobody is granted the floor);
                            pending interrupts discarded
``advance_floor``           holder (if any) ends; queue head becomes holder (strict FIFO);
                            pending interrupts discarded
``request_interrupt``       a pending interrupt ``(sequence, proposer)`` is appended; holder
                            and queue unchanged
``respond_to_interrupt``    ``denied``: that request is removed, nothing else changes.
                            ``granted``: the requester becomes holder (and leaves the queue
                            if queued); the interrupted holder is placed at the head of the
                            queue; all other pending interrupts are discarded
``move_phase`` (boundary)   when the phase actually changes: holder, queue and pending
                            interrupts cleared
anything else               no change (``speak`` never consumes or grants the floor)
==========================  ===============================================================

**Interrupt requests.** A pending request is identified by the sequence number of the
accepted ``request_interrupt`` event that created it: unique, deterministic and visible
to every actor, since accepted floor events are public. ``interrupts`` is ordered by that
sequence (arrival order); the judge answers requests explicitly, in any order, and
nothing is granted automatically. A request is directed at the holder of the floor when
it was accepted, so it is pending only while that holding lasts: any holder change
(release, advance, a granted interrupt) or phase boundary discards every pending request
in the same transition. A discarded, answered or never-pending sequence is *stale*; a
response naming it is rejected with ``FLOOR_INTERRUPT_NOT_PENDING``, the same finding
for every reason, so a response is never an oracle for withheld rejected attempts.
There is no withdrawal action for interrupt requests in this slice.

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
* ``FLOOR_INTERRUPT_NO_HOLDER``: ``request_interrupt`` while nobody holds the floor.
* ``FLOOR_INTERRUPT_HOLDER``: ``request_interrupt`` by the holder itself.
* ``FLOOR_DUPLICATE_INTERRUPT``: ``request_interrupt`` by an actor with a pending one.
* ``FLOOR_INTERRUPT_NOT_PENDING``: ``respond_to_interrupt`` naming a sequence that is not
  a pending interrupt request (see above).

Role checks live in ``indubio.core.authorization`` (also unconditional). Procedural
checks (e.g. speaking without the floor) belong to the versioned floor ruleset, which
only returns ``procedural`` findings: in strict mode they reject, in realistic mode the
event is recorded with its finding. A recorded-but-improper act is still not lawful, and
an accepted ``speak`` without the floor does not grant the floor. The demonstrator floor
pack adds no interrupt-specific rules; a pending or denied interrupter who speaks anyway
is an ordinary ``DEMO_FLOOR_SPEAK`` talk-over.

Phase boundaries are engine lifecycle, not procedure: pending requests, interrupts and
the floor do not carry over into the next phase.

The interrupt actions extend ``indubio.floor/1`` additively: they are new action kinds,
and every history without them has exactly the transitions it had before (discarding an
empty set of interrupts changes nothing), so earlier floor journals replay unchanged.

**One transition path.** ``transition`` is the only way state changes; it re-runs
``structural_findings`` and raises ``ValueError`` for an impossible step, so the engine
(which only calls it for accepted events) and ``derive_floor`` (which replays a history)
cannot disagree.
"""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from indubio.core.models import (
    AdvanceFloor,
    MovePhase,
    ReleaseFloor,
    RequestFloor,
    RequestInterrupt,
    RespondToInterrupt,
    RuleFinding,
    TrialEvent,
    WithdrawFloorRequest,
)

FLOOR_SEMANTICS = "indubio.floor/1"
FLOOR_ACTION_TYPES: tuple[type[BaseModel], ...] = (
    RequestFloor, WithdrawFloorRequest, ReleaseFloor, AdvanceFloor,
    RequestInterrupt, RespondToInterrupt,
)


class PendingInterrupt(BaseModel):
    """One pending interrupt request, identified by its accepted request event's sequence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_sequence: int = Field(ge=1)
    actor_id: str = Field(min_length=1)


class FloorState(BaseModel):
    """Immutable floor snapshot: holder, FIFO queue and interrupts pending against holder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    holder: str | None = Field(default=None, min_length=1)
    queue: tuple[str, ...] = ()
    interrupts: tuple[PendingInterrupt, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "FloorState":
        members = list(self.queue) + ([self.holder] if self.holder is not None else [])
        if len(set(members)) != len(members):
            raise ValueError("An actor may appear at most once in the floor state")
        if self.interrupts and self.holder is None:
            raise ValueError("Interrupt requests are pending only against a holder")
        sequences = [pending.request_sequence for pending in self.interrupts]
        if sequences != sorted(set(sequences)):
            raise ValueError("Pending interrupts must be in strictly ascending sequence order")
        requesters = [pending.actor_id for pending in self.interrupts]
        if len(set(requesters)) != len(requesters) or self.holder in requesters:
            raise ValueError("At most one pending interrupt per actor, never the holder's")
        return self

    def pending_interrupt(self, request_sequence: int) -> PendingInterrupt | None:
        for pending in self.interrupts:
            if pending.request_sequence == request_sequence:
                return pending
        return None


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
    if isinstance(action, RequestInterrupt):
        if state.holder is None:
            return [_security("FLOOR_INTERRUPT_NO_HOLDER", "Nobody holds the floor")]
        if actor_id == state.holder:
            return [_security("FLOOR_INTERRUPT_HOLDER", "Actor already holds the floor")]
        if any(pending.actor_id == actor_id for pending in state.interrupts):
            return [_security("FLOOR_DUPLICATE_INTERRUPT",
                              "Actor already has a pending interrupt request")]
    if (
        isinstance(action, RespondToInterrupt)
        and state.pending_interrupt(action.request_sequence) is None
    ):
        # One finding for unknown, rejected, answered and discarded sequences: no oracle.
        return [_security("FLOOR_INTERRUPT_NOT_PENDING",
                          "No pending interrupt request has this sequence")]
    return []


def transition(
    state: FloorState,
    actor_id: str,
    action: object,
    *,
    sequence: int,
    phase_changed: bool,
) -> FloorState:
    """The state after an *accepted* event at ``sequence``; the only state-change path.

    Raises ``ValueError`` if ``action`` has a structural floor finding against ``state``
    (an event the engine could not have accepted).
    """
    if structural_findings(state, actor_id, action):
        raise ValueError(f"Event {sequence} is an impossible floor transition")
    if isinstance(action, MovePhase) and phase_changed:
        return FloorState()
    if isinstance(action, RequestFloor):
        return state.model_copy(update={"queue": (*state.queue, actor_id)})
    if isinstance(action, WithdrawFloorRequest):
        return state.model_copy(
            update={"queue": tuple(a for a in state.queue if a != actor_id)}
        )
    if isinstance(action, ReleaseFloor):
        return FloorState(queue=state.queue)
    if isinstance(action, AdvanceFloor):
        return FloorState(holder=state.queue[0], queue=state.queue[1:])
    if isinstance(action, RequestInterrupt):
        pending = PendingInterrupt(request_sequence=sequence, actor_id=actor_id)
        return state.model_copy(update={"interrupts": (*state.interrupts, pending)})
    if isinstance(action, RespondToInterrupt):
        answered = state.pending_interrupt(action.request_sequence)
        assert answered is not None  # guaranteed by structural_findings above
        if action.decision == "denied":
            return state.model_copy(update={"interrupts": tuple(
                pending for pending in state.interrupts
                if pending.request_sequence != answered.request_sequence
            )})
        assert state.holder is not None  # pending interrupts imply a holder
        rest = tuple(a for a in state.queue if a != answered.actor_id)
        return FloorState(holder=answered.actor_id, queue=(state.holder, *rest))
    return state


def derive_floor(events: Iterable[TrialEvent]) -> FloorState:
    """Floor state after an ordered committed history of a floor-enabled run.

    Replays every *accepted* event through ``transition`` (rejected events never change
    state). This checks only floor structure: it raises ``ValueError`` if an accepted
    floor action is structurally impossible at its position (``FLOOR_*`` above). It
    trusts everything else about the history: sequence contiguity, role authorization,
    each event's recorded ``phase_before``/``phase_after`` (a phase boundary is taken
    from them), the acceptance decision and metadata. Callers that need those checked
    must check them separately (``build_projection`` checks contiguity; restoration
    regenerates every event through the engine).
    """
    state = FloorState()
    for event in events:
        if not event.accepted:
            continue
        state = transition(
            state, event.actor_id, event.proposal.action,
            sequence=event.sequence,
            phase_changed=event.phase_after != event.phase_before,
        )
    return state


__all__ = [
    "FLOOR_ACTION_TYPES",
    "FLOOR_SEMANTICS",
    "FloorState",
    "PendingInterrupt",
    "derive_floor",
    "is_floor_action",
    "structural_findings",
    "transition",
]
