# ADR-0003: Append-only historical record

**Status:** Accepted (architecture, 2026-11-24)

Events are appended, never overwritten. A legal correction, annulment, reversal or remittal appends a new event referencing prior judgment and record. Store source versions, agent/version metadata and visibility classification in future schemas. Starter SQLite persistence is append-only at application API level, not tamper-evident.

Scenario-built engines stamp `ScenarioProvenance` (identity plus a deterministic setup digest, see `indubio.core.provenance`) on every event. The field is optional and omitted when absent, so pre-provenance journals still load unchanged.

Restoration (`indubio.scenarios.restore`) never trusts recorded state: it rebuilds the engine from the matching manifest and re-proposes each recorded proposal, refusing the journal unless every regenerated event (rejected events included) equals the recorded one. Unstamped journals stay load-only (`LegacyJournalError`). This checks consistency, not authenticity; it is not tamper evidence.
