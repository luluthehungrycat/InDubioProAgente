# Roadmap — narrow executable increments

## Phase 0 — initial seed (this branch)
- [x] Vision, architectural contracts, threats and ADRs
- [x] Python package, typed actions, illustrative strict/realistic checks
- [x] Offline scripted demo, evidence visibility helper and SQLite append-only baseline
- [x] Basic unit tests
- [ ] Run automated CI and inspect results (workflow not guaranteed to run in all GitHub environments)

## Phase 1 — deterministic courtroom kernel
- [ ] Explicit per-role action permissions, speaking queue and interrupt/response actions
- [ ] Scenario manifests, sealed truth and scoped evidence registry with disclosure events (partial: immutable scoped `EvidenceRegistry` with sealed hidden truth; no manifests or disclosure events yet)
- [ ] Ruleset interface with source provenance and time-effective versions (partial: versioned `JurisdictionRuleset` protocol and metadata; demonstrator pack only, no effective-date selection)
- [ ] Independent perspective projection for each actor, including confidential consultations (partial: deterministic redacted per-actor projections over committed events and the scoped evidence registry; no confidential consultation channels or disclosure events yet)
- [ ] Persist actor state and replay deterministically; concurrency tests
- [ ] **Proposed:** source/provenance and event-time schema for imported cases; distinguish source material, extracted claims, synthetic supplements and hindsight-only outcome
- [ ] **Proposed:** typed version-pinned legal lookup contract separating court normative rules from actors' fallible legal research

## Phase 2 — German criminal sandbox
- [ ] Scoped Amtsgericht court type(s), judicial composition under GVG, StPO hearing stages
- [ ] Source-backed German legal conformance fixtures reviewed by a human
- [ ] Defendant silence, motions, witnesses and applicable testimony protection
- [ ] Synthetic key-reseller case with legal characterization explicitly verified
- [ ] Typed initial judgment and findings; distinguish guilt facts from legal rulings
- [ ] **Proposed:** case-data import proof of concept with independently verifiable public documents and disclosure timeline
- [ ] **Proposed:** independent german-legal-rag service adapter with source-backed statutes, effective dates and verified references

## Phase 3 — agent/human runtime
- [ ] Scripted, native LLM, Hermes-profile and human adapters sharing contract
- [ ] Runtime isolation, identity/authentication, per-actor memory and prompt injection tests
- [ ] Human UX: consent, pacing, private counsel, pause/exit, accessibility and feedback
- [ ] Budget limits, reviewable logs, replay and model-version recording
- [ ] **Proposed (after basic text session works):** event-triggered interrupt requests; personality-conditioned scoring and cooldowns; deterministic floor arbitration
- [ ] **Proposed (non-MVP):** streaming text, TTS, optional ASR/VAD, cancellable audio, human-first interruption/stop controls and synchronized evidence-aware transcript

## Phase 4 — review and contested procedure
- [ ] Appeal/revision rules and standing/admissibility; preservation questions
- [ ] Review on appellate record, independent decision-maker, remittal and finality
- [ ] Granular rule-violation settings and probabilistic error injection
- [ ] Correct and incorrect appellate outcomes with independent evaluation

## Phase 5 — expansion
- [ ] German civil/ZPO model and distinct evidentiary assumptions
- [ ] Lay judges, chamber composition, multiple counsel, jury systems
- [ ] Jurisdiction comparison, experimental evaluations, user scenario editor

## Design proposals awaiting decision
- [Case data and disclosure plan](CASE_DATA.md)
- [Legal knowledge service / german-legal-rag](LEGAL_KNOWLEDGE.md)
- [Interruptions, streaming speech and human participation](LIVE_RUNTIME.md)

**Next recommended PR:** a synthetic scenario manifest and explicit evidence disclosure events built on the projection API. Avoid claiming StPO accuracy before official-source verification.
