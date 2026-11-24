# Roadmap — narrow executable increments

## Phase 0 — initial seed (this branch)
- [x] Vision, architectural contracts, threats and ADRs
- [x] Python package, typed actions, illustrative strict/realistic checks
- [x] Offline scripted demo, evidence visibility helper and SQLite append-only baseline
- [x] Basic unit tests
- [ ] Run automated CI and inspect results (workflow not guaranteed to run in all GitHub environments)

## Phase 1 — deterministic courtroom kernel
- [ ] Explicit per-role action permissions, speaking queue and interrupt/response actions
- [ ] Scenario manifests, sealed truth and scoped evidence registry with disclosure events
- [ ] Ruleset interface with source provenance and time-effective versions
- [ ] Independent perspective projection for each actor, including confidential consultations
- [ ] Persist actor state and replay deterministically; concurrency tests

## Phase 2 — German criminal sandbox
- [ ] Scoped Amtsgericht court type(s), judicial composition under GVG, StPO hearing stages
- [ ] Source-backed German legal conformance fixtures reviewed by a human
- [ ] Defendant silence, motions, witnesses and applicable testimony protection
- [ ] Synthetic key-reseller case with legal characterization explicitly verified
- [ ] Typed initial judgment and findings; distinguish guilt facts from legal rulings

## Phase 3 — agent/human runtime
- [ ] Scripted, native LLM, Hermes-profile and human adapters sharing contract
- [ ] Runtime isolation, identity/authentication, per-actor memory and prompt injection tests
- [ ] Human UX: consent, pacing, private counsel, pause/exit, accessibility and feedback
- [ ] Budget limits, reviewable logs, replay and model-version recording

## Phase 4 — review and contested procedure
- [ ] Appeal/revision rules and standing/admissibility; preservation questions
- [ ] Review on appellate record, independent decision-maker, remittal and finality
- [ ] Granular rule-violation settings and probabilistic error injection
- [ ] Correct and incorrect appellate outcomes with independent evaluation

## Phase 5 — expansion
- [ ] German civil/ZPO model and distinct evidentiary assumptions
- [ ] Lay judges, chamber composition, multiple counsel, jury systems
- [ ] Jurisdiction comparison, experimental evaluations, user scenario editor

**Next recommended PR:** extract a `JurisdictionRuleset` protocol and immutable evidence registry while maintaining existing security checks, with reference tests on one *illustrative* rule. Avoid claiming StPO accuracy before official-source verification.
