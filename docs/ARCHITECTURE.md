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
- **`EvidenceRegistry`** (`indubio.evidence.registry`): immutable, deep-copied snapshot of `EvidenceRecord`s with actor-scoped views. `HIDDEN_TRUTH` records never appear in any view and are never submittable. When a registry is passed to the engine, the evidence ACL is derived from these scoped views; the legacy `available_evidence` mapping (ID grants without records) is still accepted, snapshotted and type-checked, but the two cannot be combined. The registry cannot be reinitialized, and the engine keeps its own snapshot so evidence views and the derived ACL always agree. Registry-wide iteration, `len`, `actor_ids()` and `snapshot()` are trusted setup APIs (iteration includes hidden-truth IDs); only `visible_to`/`accessible_ids` are actor-scoped.
- **Perspective projections** (`indubio.core.projection`, `SimulationEngine.perspective(actor_id)`): a deterministic, frozen, redacted view of the committed history for one known actor, derived only from engine-owned state (events, actor registry, evidence ACL, registry snapshot). It is a read-only view, never a source of legal decisions; `engine.events` and the SQLite journal stay the complete trusted audit history and are unchanged. Policy, conservative and fail-closed:
  - Unknown viewer → `PermissionError`; an event naming an unknown/inconsistent actor or a gapped/reordered history → `ValueError`, never a partial view.
  - Own events: full proposal (accepted or rejected); rule findings only on own *rejected* events, to explain the rejection.
  - Other actors' accepted events: author, role, phase change and action, by per-kind allowlist. A `SubmitEvidence` ID is shown only if the viewer may itself access that ID; otherwise the payload is withheld and `redacted_fields` says so. Unlisted action kinds are withheld from non-authors.
  - Other actors' rejected events: `withheld` — only the global sequence number and unchanged phase remain (author, kind, payload, findings hidden). The existence and position of a rejected attempt is therefore visible, as it is from sequence numbers.
  - Findings on accepted events (e.g. realistic-mode procedural findings) are evaluator/audit data and are not projected to any actor. Simulation mode, event metadata and `Actor.human_controlled` are not projected; ruleset ID, version and validation status are.
  - Projected evidence records omit `visible_to_actor_ids`; hidden truth never appears.
  - **Free-text trust boundary:** `Speak.text`, motion grounds, ruling reasons and objection grounds are untrusted actor-authored strings, passed through verbatim in public accepted events. Redaction is structural, not content-based; an actor who writes an ID or fact into public free text publishes it by its own act. Consumers must treat it as untrusted data.
  - **Legacy ID ACL boundary:** with the legacy `available_evidence` mapping there are no records; granted IDs are trusted caller-asserted setup input, projected as `accessible_evidence_ids` and used for redaction, with no record content and no epistemic-layer check. Use an `EvidenceRegistry` for sealed truth.
  - Not yet covered: confidential consultation channels, replay of engine state from the journal, authenticated viewers. The older `engine.evidence_view()` still returns full `EvidenceRecord`s including `visible_to_actor_ids`, and only the *scenario-initial* records (not records received by disclosure); projections use the narrower `ProjectedEvidence` and reflect current access.
- **Scenario manifests** (`indubio.scenarios`): `ScenarioManifest` (`schema_version: "indubio.scenario/1"`, `scenario_version`, `synthetic: true` required) declares synthetic actors and scenario-initial evidence (layer, per-actor visibility). Validation fails closed on unknown fields or schema versions, duplicate IDs, visibility naming unknown actors, and `hidden_truth` records that list any actor. `build_engine(manifest, mode)` builds the engine with an immutable registry; the ruleset ID must be registered. Bundled fixtures are loaded by allowlisted name. A manifest is trusted, author-written setup data, never actor input; it performs no network access. Real-case import is out of scope (see CASE_DATA.md). Scenario ID/version are not yet stamped on events.
- **Evidence disclosure events** (`DiscloseEvidence`, policy in `indubio.core.disclosure`; demonstrator only, not StPO): one evidence ID to one recipient. Structural checks, `security` severity, in every mode: discloser role ∈ {judge, prosecutor, defense} (`AUTH_DISCLOSE`); recipient a known other actor (`REFERENCE_ACTOR`) with role ∈ {judge, prosecutor, defense, defendant} (`AUTH_DISCLOSE_RECIPIENT`); discloser currently holds the ID (`ACL_EVIDENCE`, same wording for unknown, sealed and inaccessible IDs, so no existence oracle); ID backed by a non-hidden record (`DISCLOSE_RECORD_REQUIRED`, i.e. legacy bare-ID grants cannot be disclosed). Timing is procedural (`DEMO_DISCLOSURE_PHASE` outside opening/evidence in ruleset `0.2.0-demo`): strict rejects; realistic records the event as accepted with the finding kept in the audit record. Only accepted events grant access; rejections never change visibility. Redundant disclosure is accepted as a no-op rather than revealing other holders. Grants are derived from the trusted history (journal round trips reproduce them) and revalidated during projection; an impossible accepted disclosure raises `ValueError`. Records themselves are never mutated.
  - Projection: discloser `own`; recipient of an accepted disclosure `recipient` (author, role, action); everyone else, and the named recipient of a rejected one, `withheld`. Received records carry `disclosed_at_sequence`.
  - **Event-time versus current visibility:** `accessible_evidence_ids`/`evidence` are current; per-event redaction uses access from strictly earlier events. A later disclosure never retroactively un-redacts an earlier `SubmitEvidence` event.

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
