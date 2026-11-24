# InDubioProAgente ⚖️

**An open-source multi-agent courtroom simulation and legal-reasoning laboratory.**

_In dubio pro agente_ is a playful riff on _in dubio pro reo_, not a legal maxim.

> **Status:** architectural seed / experimental Python kernel. NOT a legally validated simulator, legal adviser, prediction tool, or a substitute for qualified representation.

## Vision

Simulate courtroom proceedings using autonomous LLM agents, externally hosted Hermes Agent profiles, and/or human-controlled participants. Each role has its own instructions, private knowledge, memory, decisions and behavioral traits. A deterministic procedural engine manages turn-taking, authority, evidence access, event logging and versioned jurisdiction rules.

**Foundational distinction:** (1) what the law requires; (2) what participants actually do, potentially unlawfully; (3) how alleged errors are challenged, reviewed and remedied. The simulator must not automatically correct a legally wrong act in realism mode.

## MVP

A **German Amtsgericht criminal-court sandbox** with a single professional judge, prosecutor, defense lawyer, defendant and witness; synthetic facts, an explicit phase machine, typed actions, separate perspectives, rule findings and a reproducible SQLite event log. The starter code implements a small **jurisdiction-agnostic educational kernel**, *not* the full German StPO or a working LLM courtroom. The German rule pack is an interface/placeholder pending primary-source validation.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python -m indubio demo
```

The demo runs entirely offline with scripted actions and prints a JSON event transcript. No API keys required. LLM and Hermes adapters are design seams, not yet operational.

## Principles

- **Deterministic enforcement, fallible simulated participants.** Security boundaries are always enforced; procedural violations may be blocked or logged and allowed depending on mode.
- **Truth ≠ disclosed evidence ≠ legally established findings.** The evaluator's hidden facts do not leak to court agents.
- **Role-specific epistemic boundaries.** Confidential attorney–client communications and private memories never appear in global agent context by default.
- **Jurisdiction-specific procedures.** German criminal/civil and other systems must not be blended into a generic courtroom script.
- **Review is its own proceeding.** Berufung, Revision and other remedies depend on jurisdiction, instance, dates, standing, scope and preservation requirements.
- **Humans are first-class actors.** Pause, consent, accessibility and optional structured feedback matter as much as realism.
- **Research integrity.** Seeded trials, model/version metadata, immutable histories and human legal review before strong claims.
- **Untrusted input.** Evidence, testimony, legal documents and external agent outputs are data, not instructions.

## Project map

- [Vision](docs/VISION.md) · [Architecture](docs/ARCHITECTURE.md) · [Specification](docs/SPEC.md)
- [Roadmap](docs/ROADMAP.md) · [Legal rule design](docs/LEGAL_RULES.md)
- [Human participation](docs/HUMAN_PARTICIPATION.md) · [Security](docs/SECURITY.md)
- [Contributing](CONTRIBUTING.md) · [Agent instructions](AGENTS.md)

## License

MIT, as supplied by the repository owner; the license may change for future versions. Existing released copies remain under their applicable grant. No legal citations in this repo should be treated as verified without checking official, effective-date sources.
