# ADR-0003: Append-only historical record

**Status:** Accepted (architecture, 2026-11-24)

Events are appended, never overwritten. A legal correction, annulment, reversal or remittal appends a new event referencing prior judgment and record. Store source versions, agent/version metadata and visibility classification in future schemas. Starter SQLite persistence is append-only at application API level, not tamper-evident.
