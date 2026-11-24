"""Deterministic offline disclosure walkthrough over the bundled synthetic manifest."""

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    DiscloseEvidence,
    Mode,
    MovePhase,
    Phase,
    Proposal,
    SubmitEvidence,
)
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
