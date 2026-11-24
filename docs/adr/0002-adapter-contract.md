# ADR-0002: Independent participant adapters

**Status:** Accepted (architecture, 2026-11-24)

Adapters return typed action proposals; they may be scripted, direct-API agents, Hermes profiles or humans. Never couple the core engine to a single vendor, model, SOUL.md format or network backend. Adapter-private memory stays private. Provider failure does not mutate case state.
