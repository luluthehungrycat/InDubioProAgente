# Architecture

## Layered design

```text
   Synthetic case authoring / sealed evaluator truth
                       |
          Evidence & disclosure registry
                       |
    +------------------+--------------------+
    | Agent runtime    | Human participant  |
    | LLM/Hermes/etc.  | web/CLI future     |
    +------------------+--------------------+
                       |
               typed action proposal
                       |
             Security and ACL gate   <-- NON-OVERRIDABLE
                       |
         Normative rule evaluator    <-- versioned jurisdiction pack
                       |
  strict: block | realistic: log + permit | experimental: controlled injection
                       |
       Actual event / state transition
                       |
            Append-only event log
                       |
           Findings and remedies
          / appeal / revision (future)
                       |
        Independent benchmark analysis
```

## Fundamental domains
- **Case truth:** evaluator-only facts; must not be sent to participants.
- **Actor perspective:** observed facts, independent memory, authorized disclosures, confidence and misunderstandings.
- **Evidence:** provenance, chain of custody, knowledge, disclosure, admission, fact-finding and review record are distinct states.
- **Normative model:** source-backed rule expectations and citations, with uncertain or disputed interpretation first-class.
- **Actual proceedings:** immutable recorded behavior; mistakes are neither erased nor automatically legalized.
- **Consequences:** objections, cure, forfeiture, harmless-error analysis, reversal, remittal, finality and retrial as jurisdiction-specific potential outcomes.

## State and event contracts
`Proposal` is an actor-attributed request. A fixed security layer rejects unauthorized operations in all modes. A rule evaluator returns findings without claiming to be a judicial decision. The engine determines allowed state transitions for the selected simulation mode and appends `TrialEvent` including accepted status, before/after phase and findings. An event can represent a rejected *attempt*; it must not be mistaken for an accepted act. Each rule and simulator version should be recorded for future replay/migrations.

### Implemented seams (Phase 1, offline)
- **`JurisdictionRuleset`** (`indubio.jurisdictions.base`): a protocol with frozen `RulesetMetadata` (id, version, validation status, optional effective date and sources) and `evaluate(RuleContext, action) -> list[RuleFinding]`. The ruleset receives a frozen snapshot and a copy of the action, may return *procedural* findings only, and never mutates state or decides acceptance. The engine resolves rulesets by `SimulationConfig.jurisdiction` and fails on unknown IDs rather than falling back. Events record `ruleset`, `ruleset_version` and `ruleset_validation`.
- The only registered pack is `de-criminal-demo-unvalidated` (`indubio.jurisdictions.demo`): the original schematic phase/motion checks, marked `unvalidated_demonstrator`, with no legal sources. It is **not** StPO procedure.
- The engine keeps actor authorization, evidence ACL and structural reference checks itself; they run before and independently of the ruleset in every mode.
- **`EvidenceRegistry`** (`indubio.evidence.registry`): immutable, deep-copied snapshot of `EvidenceRecord`s with actor-scoped views. `HIDDEN_TRUTH` records never appear in any view and are never submittable. When a registry is passed to the engine, the evidence ACL is derived from these scoped views; the legacy `available_evidence` mapping (ID grants without records) is still accepted, snapshotted and type-checked, but the two cannot be combined.

## Planned runtime adapters
- **Native LLM:** provider-agnostic structured outputs and model/version metadata, cost limits, schema validation, retries with bounded budgets.
- **Hermes Agent:** separate profiles / SOUL.md / memory backends; strict scoped capabilities, ephemeral credentials, least privilege and prompt-injection defenses.
- **Human:** same proposal contract, interactive private consultations, consent, suspend/exit and accessible controls.
- **Scripted:** deterministic fixtures used for CI and baseline tests.

Adapters never gain direct write access to the shared case database or private peer memory. The simulation scheduler supplies only allowed perspective and current legal context; a public transcript is not identical to every actor's full internal state.

## Persistence
SQLite append-only baseline. Later: immutable audit/hash chain, actor-private encrypted storage, transcript vs semantic event projections, replay with schema migrations and model provenance. The current starter does not provide cryptographic guarantees or validated replay.

## Future UI and API
Optional FastAPI + WebSocket service with view permissions, synchronized live session, clear role switching and privacy-safe transcripts. Authentication, real-case data and deployment hardening must precede network exposure.

## Architectural decisions
See ADR-0001 for strict security vs fallible law, ADR-0002 for adapter separation and ADR-0003 for append-only event lineage.
