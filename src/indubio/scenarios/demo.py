"""Deterministic offline walkthroughs over the bundled synthetic manifest.

``run_scenario_demo``: evidence disclosure, unscheduled (no floor control).
``run_floor_demo``: the opt-in speaking queue and floor lifecycle (``indubio.core.floor``).
``run_interrupt_demo``: explicit interrupt requests and judge responses on that floor.
"""

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    AdvanceFloor,
    DiscloseEvidence,
    Mode,
    MovePhase,
    Phase,
    Proposal,
    ReleaseFloor,
    RequestFloor,
    RequestInterrupt,
    RespondToInterrupt,
    Speak,
    SubmitEvidence,
    WithdrawFloorRequest,
)
from indubio.jurisdictions.demo.floor import DEMO_FLOOR_RULESET_ID
from indubio.scenarios.manifest import build_engine, load_bundled_manifest

# Each step is scripted, typed input; nothing here is model-generated.
SCENARIO_DEMO_SCRIPT: tuple[Proposal, ...] = (
    # 1 accepted: prosecution discloses its vendor log to defense counsel.
    Proposal(actor_id="pros", action=DiscloseEvidence(
        evidence_id="pros-vendor-log", recipient_actor_id="def")),
    # 2 rejected in every mode: defense does not hold the note; witnesses cannot receive.
    Proposal(actor_id="def", action=DiscloseEvidence(
        evidence_id="pros-internal-note", recipient_actor_id="wit")),
    # 3 rejected in every mode: sealed truth is never accessible, so never disclosable.
    Proposal(actor_id="pros", action=DiscloseEvidence(
        evidence_id="sealed-origin", recipient_actor_id="judge")),
    # 4
    Proposal(actor_id="judge", action=MovePhase(destination=Phase.EVIDENCE)),
    # 5 accepted; redacted for actors without access *at this event*.
    Proposal(actor_id="def", action=SubmitEvidence(evidence_id="def-chat-export")),
    # 6 accepted: defense now holds the vendor log through event 1.
    Proposal(actor_id="def", action=SubmitEvidence(evidence_id="pros-vendor-log")),
    # 7 accepted: prosecution receives the chat export; event 5 stays redacted for it.
    Proposal(actor_id="def", action=DiscloseEvidence(
        evidence_id="def-chat-export", recipient_actor_id="pros")),
    # 8
    Proposal(actor_id="judge", action=MovePhase(destination=Phase.CLOSING)),
    # 9 late: strict rejects (no grant); realistic records it with DEMO_DISCLOSURE_PHASE.
    Proposal(actor_id="pros", action=DiscloseEvidence(
        evidence_id="pros-vendor-log", recipient_actor_id="judge")),
)


def run_scenario_demo(mode: Mode = Mode.STRICT) -> SimulationEngine:
    engine = build_engine(load_bundled_manifest(), mode)
    for proposal in SCENARIO_DEMO_SCRIPT:
        engine.propose(proposal)
    return engine


# Scripted, typed input over the same synthetic manifest, with floor control enabled.
FLOOR_DEMO_SCRIPT: tuple[Proposal, ...] = (
    # 1, 2 accepted: queue is [pros, def] (FIFO, arrival order).
    Proposal(actor_id="pros", action=RequestFloor()),
    Proposal(actor_id="def", action=RequestFloor()),
    # 3 rejected in every mode: pros is already queued.
    Proposal(actor_id="pros", action=RequestFloor()),
    # 4 strict rejects (DEMO_FLOOR_SPEAK); realistic records the talk-over, no floor change.
    Proposal(actor_id="def", action=Speak(text="Synthetic remark out of turn")),
    # 5 accepted: the judge grants the floor to the queue head, pros.
    Proposal(actor_id="judge", action=AdvanceFloor()),
    # 6 accepted: pros holds the floor.
    Proposal(actor_id="pros", action=Speak(text="Synthetic statement on the floor")),
    # 7 rejected in every mode: the passive observer cannot queue.
    Proposal(actor_id="obs", action=RequestFloor()),
    # 8 accepted: pros gives up the floor; nobody holds it, def still waits.
    Proposal(actor_id="pros", action=ReleaseFloor()),
    # 9 accepted: queue is [def, wit].
    Proposal(actor_id="wit", action=RequestFloor()),
    # 10 accepted: def holds the floor, queue is [wit].
    Proposal(actor_id="judge", action=AdvanceFloor()),
    # 11 accepted.
    Proposal(actor_id="def", action=Speak(text="Synthetic reply on the floor")),
    # 12 accepted phase boundary: holder and queue are cleared.
    Proposal(actor_id="judge", action=MovePhase(destination=Phase.EVIDENCE)),
    # 13 rejected in every mode: wit's request did not survive the boundary.
    Proposal(actor_id="wit", action=WithdrawFloorRequest()),
    # 14 rejected in every mode: nobody is queued.
    Proposal(actor_id="judge", action=AdvanceFloor()),
)


def run_floor_demo(mode: Mode = Mode.STRICT) -> SimulationEngine:
    engine = build_engine(load_bundled_manifest(), mode, floor_rules=DEMO_FLOOR_RULESET_ID)
    for proposal in FLOOR_DEMO_SCRIPT:
        engine.propose(proposal)
    return engine


# Scripted, typed input: interrupt requests and explicit judge responses on the floor.
# Nothing is granted automatically; every grant or denial is a scripted judge act.
INTERRUPT_DEMO_SCRIPT: tuple[Proposal, ...] = (
    # 1-3 accepted: pros holds the floor, def waits in the queue.
    Proposal(actor_id="pros", action=RequestFloor()),
    Proposal(actor_id="def", action=RequestFloor()),
    Proposal(actor_id="judge", action=AdvanceFloor()),
    # 4 accepted.
    Proposal(actor_id="pros", action=Speak(text="Synthetic statement on the floor")),
    # 5, 6 accepted: pending interrupts #5 (wit) and #6 (def), in sequence order.
    Proposal(actor_id="wit", action=RequestInterrupt()),
    Proposal(actor_id="def", action=RequestInterrupt()),
    # 7-9 rejected in every mode: duplicate (wit), the holder itself (pros), observer role.
    Proposal(actor_id="wit", action=RequestInterrupt()),
    Proposal(actor_id="pros", action=RequestInterrupt()),
    Proposal(actor_id="obs", action=RequestInterrupt()),
    # 10 rejected in every mode: only the judge answers interrupt requests.
    Proposal(actor_id="def", action=RespondToInterrupt(request_sequence=6, decision="granted")),
    # 11 accepted: the judge denies #5; holder and queue unchanged, #6 still pending.
    Proposal(actor_id="judge", action=RespondToInterrupt(request_sequence=5, decision="denied")),
    # 12 strict rejects (DEMO_FLOOR_SPEAK); realistic records the talk-over, no floor change.
    Proposal(actor_id="wit", action=Speak(text="Synthetic remark despite denial")),
    # 13 rejected in every mode: #7 was a rejected attempt, never a pending request.
    Proposal(actor_id="judge", action=RespondToInterrupt(request_sequence=7, decision="granted")),
    # 14 accepted: #6 granted; def holds the floor, the interrupted pros heads the queue.
    Proposal(actor_id="judge", action=RespondToInterrupt(request_sequence=6, decision="granted")),
    # 15 accepted.
    Proposal(actor_id="def", action=Speak(text="Synthetic interjection on the floor")),
    # 16 rejected in every mode: #6 was already answered.
    Proposal(actor_id="judge", action=RespondToInterrupt(request_sequence=6, decision="denied")),
    # 17 accepted: pending interrupt #17 (acc) against def.
    Proposal(actor_id="acc", action=RequestInterrupt()),
    # 18 accepted: def releases; the holding ends, so #17 is discarded (stale).
    Proposal(actor_id="def", action=ReleaseFloor()),
    # 19 rejected in every mode: #17 is stale.
    Proposal(actor_id="judge", action=RespondToInterrupt(request_sequence=17, decision="granted")),
    # 20, 21 accepted: pros resumes; pending interrupt #21 (acc) against pros.
    Proposal(actor_id="judge", action=AdvanceFloor()),
    Proposal(actor_id="acc", action=RequestInterrupt()),
    # 22 accepted phase boundary: holder, queue and pending interrupts are cleared.
    Proposal(actor_id="judge", action=MovePhase(destination=Phase.EVIDENCE)),
    # 23 rejected in every mode: #21 did not survive the boundary.
    Proposal(actor_id="judge", action=RespondToInterrupt(request_sequence=21, decision="granted")),
)


def run_interrupt_demo(mode: Mode = Mode.STRICT) -> SimulationEngine:
    engine = build_engine(load_bundled_manifest(), mode, floor_rules=DEMO_FLOOR_RULESET_ID)
    for proposal in INTERRUPT_DEMO_SCRIPT:
        engine.propose(proposal)
    return engine
