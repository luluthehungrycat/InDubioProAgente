# Threat model and privacy requirements

## Trust boundaries
Model prompts, testimony, transcripts, documents, citations, tool descriptions, repositories and Hermes handoffs are untrusted. Agents may intentionally or accidentally attempt prompt injection, exfiltration, impersonation, privilege escalation or cross-actor memory leakage.

## Invariants (even in experimental violation mode)
- Enforce actor identity, authorization and evidence ACL in deterministic code.
- No direct agent access to another actor's memory, sealed scenario truth, secret/API key material or full persistent database.
- No unreviewed shell execution or filesystem/network powers via a simulation action.
- Apply budget/rate/turn limits; terminate runaway loops; audit every tool call.
- Treat external law text as cited data, not a system prompt.
- Partition confidential counsel communications and use need-to-know disclosure.
- Restrict real personal/medical/traumatic case data by default, with deletion/retention options before human deployments.
- Do not expose human private messages to public transcript or the opposing party.
- Never allow an 'unsafe realism' flag to override these requirements.

## Current limitations
This repository is an architectural starter, **not a security-hardened multi-user service**. SQLite and basic ACL tests do not provide isolation across processes or authenticated users. Do not connect it to public networks or production legal files. Security review, sandboxing and real identity management are prerequisites for external adapters.
