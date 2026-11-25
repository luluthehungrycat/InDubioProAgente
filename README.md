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
python -m indubio scenario-demo --mode strict --perspective pros
python -m indubio floor-demo --mode realistic --perspective wit
```

The demo runs entirely offline with scripted actions and prints a JSON event transcript (the trusted, unredacted audit history). Add `--perspective defense` (or another demo actor ID) to also print that actor's redacted perspective projection. `scenario-demo` initializes actors and sealed/scoped evidence from the bundled synthetic manifest (`src/indubio/scenarios/fixtures/synthetic_disclosure_demo.json`) and runs a scripted sequence of accepted and rejected evidence disclosures (illustrative policy only, not StPO). Each `scenario-demo` event also carries trusted scenario provenance (scenario ID, version and a deterministic setup digest); it is never shown in perspective projections. `floor-demo` runs the same manifest with the opt-in demonstrator speaking queue (`indubio.core.floor`): FIFO floor requests, withdrawal, release, judge-only advance, phase-boundary clearing and rejected duplicate/structural attempts; without floor control, `demo` and `scenario-demo` stay unscheduled and unchanged. No API keys required. LLM and Hermes adapters are design seams, not yet operational.

### Restoring from a journal

```python
from indubio.core.models import Mode, MovePhase, Phase, Proposal
from indubio.persistence.sqlite import EventStore
from indubio.scenarios import load_bundled_manifest, restore_from_store
from indubio.scenarios.demo import run_scenario_demo

engine = run_scenario_demo(Mode.STRICT)
store = EventStore("journal.sqlite3")
for event in engine.events:
    store.append("demo-1", event)

# Fresh engine rebuilt from the manifest by re-proposing every journaled proposal; raises
# RestoreError (no engine) unless each regenerated event equals the recorded one.
restored = restore_from_store(store, "demo-1", load_bundled_manifest())
event = restored.propose(Proposal(actor_id="judge", action=MovePhase(destination=Phase.JUDGMENT)))
store.append("demo-1", event)  # sequence continues at len(engine.events) + 1
```

Restoration checks consistency against the scenario, ruleset version, mode and (for floor-enabled runs) the recorded floor ruleset, not authenticity: the journal is not tamper-evident. Journals without scenario provenance remain loadable with `EventStore.load` but raise `LegacyJournalError` on restore.

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
