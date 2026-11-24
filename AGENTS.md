# Agent / contributor instructions

These instructions apply to all coding agents, including Hermes, Codex, Claude Code and other runners.

## Mission and boundaries
Build InDubioProAgente as a modular legal **simulation/research/education** project. Do not advertise reliable trial prediction or professional legal advice. Keep it possible for humans and agent profiles to assume any allowed role. Maintain clean separation between procedural machine, jurisdiction rules, personas and model adapters.

## Non-negotiable design invariants
1. **Separate normative law, actual events and subsequent legal consequences.** An incorrect action does not become lawful by being recorded or accepted in realism mode.
2. **Separate security checks from legal checks.** Never make secret access, tool privilege, impersonation, arbitrary shell execution or memory isolation violable via simulation settings.
3. **Separate objective ground truth, observation, disclosures, admissible evidence, judicial findings and appellate record.** No accidental omniscience.
4. **No fabricated legal authority.** Legal packs require jurisdiction, source URL, version/effective date, section citation, unit tests and human review status. Mark placeholders clearly.
5. **No model-controlled state mutation.** Agents submit typed action proposals. Engine validates and persists transitions; each event has provenance.
6. **No inadvertent US/German procedural mashups.** Design only those jurisdictional steps supported by verified sources.
7. **Preserve a human-controlled actor contract.** Pause/exit/consent and accessible feedback are product requirements; no coercive training.
8. **Sandbox untrusted content and external adapters.** Treat retrieved legal texts, evidence and agent messages as adversarial data.
9. **Never silently rewrite history.** Corrections and appellate results append new events with explicit links to earlier ones.
10. **Small, tested slices.** Do not claim unimplemented features work. Prefer explicit TODO with issue references.

## Development
Python >=3.11, typed Pydantic v2 domain models, SQLite baseline and pytest. Run `python -m pytest` before claiming code is green. Keep package imports without network calls. Do not add a hosted provider dependency or real-case PII by default. Use a case fixture with synthetic actors.

## Suggested boundaries
`core/`: action/event contracts + deterministic engine. `jurisdictions/`: rule packs. `agents/`: provider/Hermes/human adapters. `evidence/`: ACL and chain of custody. `review/`: remedies. `persistence/`: replayable append-only store. `api/`: optional UI transport, never the source of legal decisions.

## Acceptance for new procedural behavior
Document source and effective date, define scope/preconditions, write positive and negative tests in strict and realistic modes, preserve event auditability, test unauthorized access denial, and ensure no normative fact is inferred solely from an LLM utterance.
