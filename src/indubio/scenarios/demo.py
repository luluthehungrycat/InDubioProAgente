"""Deterministic offline walkthroughs over the bundled synthetic manifest.

``run_scenario_demo``: evidence disclosure, unscheduled (no floor control).
``run_floor_demo``: the opt-in speaking queue and floor lifecycle (``indubio.core.floor``).
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
