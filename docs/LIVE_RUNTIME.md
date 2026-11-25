# Contextual interruptions, speech and real-time hearings — design proposal

**Status: PROPOSED, explicitly post-MVP.** Interactive human support and deterministic turn-taking come before autonomous real-time interruption.

## Goal
An actor with standing, personality, stakes, memory, partial knowledge and evolving conversational context may *request* to interrupt when a credible trigger occurs; it should not randomly blurt merely because the feature exists. Disorderly interruption may be a deliberate actor behavior. The floor arbiter, not an LLM, resolves requests and records legal consequences.

## Proposed event architecture
```
speaker utterance / partial transcript / context event
  -> permissioned perspective projection
  -> cheap eligible-trigger detection (rule heuristics)
  -> optional low-latency decision scorer (Jev/d1/small classifier)
  -> policy: cooldown, timing, stamina, intervention budget, seeded sampling
  -> typed InterruptIntent(actor, target, reason, urgency, confidence)
  -> deterministic floor arbiter and jurisdiction rules
  -> grant / defer / reject / talk-over (if realism config)
  -> append timestamped attempt + audio/text events
```

### Candidate triggers
Specific allegation touching personal stake; direct challenge to testimony; perceived factual misstatement; contradiction with actor's own memory; rights issue counsel detects; unexpected evidence or ruling; invitation to respond; rising emotional pressure; deliberate disturbance. Silence, frustration and impulsivity alone should **not** force an interruption.

### Trait-conditioned scoring
Use actor-private, scenario-authorized context: role, stakes, temperament, impulsivity, restraint, fear, emotional arousal, trust in counsel, past objections, recent interruptions and perceived procedural risk. A calibrated model may score `none | request_floor | object | consult | interject | disrupt`. Keep a rule-based baseline and an optional model adapter behind the same typed contract. A model's reported probabilities are not guaranteed psychologically calibrated; evaluate on annotated synthetic human-reviewed sequences. Use seeded draws, trigger thresholds, cooldowns and maximum frequency for replayability.

**Do not sample an independent probability each audio frame/token:** this causes probability accumulation and near-certain interruptions in long utterances. Re-evaluate on meaningful semantic events or throttled windows. The model judges *plausibility*, not legal permission; the ruleset determines procedural consequences.

### Real-time transport (later)
Start with text + explicit request-to-speak. Later use streaming text and TTS; optional ASR, voice activity detection (VAD) and real-time audio transport. For an MVP transport candidate, FastAPI WebSockets support async text send/receive/disconnect; real deployment needs session identities, per-subscriber access, backpressure and ordered event delivery.

Streaming model output is a **provisional draft**: text/audio chunks must be cancellable, versioned and never automatically committed as sworn testimony until actually uttered/confirmed. Separately persist speaker, begin/end timestamps, overlaps, interruptions, completed utterances, uncertain ASR words, corrected transcript and TTS provenance. Do not treat text generated after being interrupted as spoken.

A human's `pause/stop/mute/skip` must preempt agent audio. Handle VAD end-of-turn ambiguity, noisy rooms, echo cancellation, TTS/ASR feedback loops and staggered participant latencies. TTS voices should be disclosed as synthetic and not imitate real persons without authorization. Real case voice recordings are sensitive data.

### Floor arbiter decisions
For `InterruptIntent`, choose `granted`, `queued`, `denied` or `actual_talk_over` per jurisdiction and configured realism. Procedurally improper talk-over can be recorded and trigger judicial admonition, sanctions or later relevance, without allowing security bypass or forced disclosure of another person's private context. Humans can voluntarily interject; their action is logged and treated under the same procedural semantics.

### Determinism and measurement
Keep model/adapter version, decision input snapshot digest, candidate options, scores, seed, sample, time and arbitration result. Full replay uses recorded decisions, never assumes calling a live stochastic model again produces identical timing. Benchmarks: interruption precision judged by blinded reviewers, false interjections per simulated minute, missed salient opportunities, jitter/latency, human perceived control and privacy incidents.

## Implementation gates
- [ ] Text-only manual interruption request and floor queue with tests (partial: opt-in FIFO floor queue in `indubio.core.floor`; interruption request/response not yet).
- [ ] Semantic trigger fixtures and rule-based scorer.
- [ ] Optional decision-model adapter with calibration and throttling tests.
- [ ] Streaming text with cancellable output and audience filtering.
- [ ] TTS and optional ASR/VAD, speech interruption, transcript reconciliation.
- [ ] Human participation usability, consent and safety tests before public deployments.

## Open questions
What is the baseline jurisdiction/courtroom control policy? Should spontaneous nonverbal reactions be distinct typed actions? How should model/personality data be sourced, consented to and calibrated? Should one agent hear a low-latency partial ASR transcript while another receives only a finalized public transcript?
