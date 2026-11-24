# Product and engineering specification (seed v0.1)

**Status:** requirements and implementation boundaries; only the small Python kernel is implemented. All broader provisions are targets, not completed capabilities.

## Actors
Judge(s), lay judges, prosecution, defense, accused, plaintiff/civil parties, witnesses, injured parties, jurors and observers are jurisdiction-specific roles. All may be LLM, Hermes or human adapters where appropriate. Every actor has instructions, model/backend, goals, temperament, independent memory and an authorized view. More than one person can occupy a legal role; co-counsel and judicial panels are future compositions.

Personality controls include impulsivity, stress, confidence, memory reliability, willingness to testify, counsel trust and procedural assertiveness. Such controls should vary behavior, **not automatically imply legal culpability or undermine procedural rights**. Exercise of silence must not count as guilt.

## Simulation controls
- **STRICT:** modeled procedural infractions are blocked; attempted acts remain visible as attempts.
- **REALISTIC:** security invariants remain enforced; modeled legally improper acts can still occur and are flagged without assuming an appellate disposition.
- **EXPERIMENTAL:** explicit bounded intervention rules and random seeds; never permits ACL bypass or arbitrary tool execution.
- Granular flags for judicial error, attorney error, witness behavior and review proceedings are configuration targets. Starter stores these fields but does not yet enforce all flags; do not advertise them as operational.

## Workflow
Case creation -> role assignment and disclosures -> courtroom phase machine -> questioning / motions / objections / evidence -> ruling and findings -> trial judgment -> optional post-trial remedies -> structured feedback. German and Anglo-American modules have separate workflow graphs.

## Acceptance: first runnable slice
- Pydantic typed proposals/events; invalid role access and disclosure blocked in *every* mode.
- Strict rejects a demonstrator out-of-order transition; realistic logs and accepts it.
- Sealed truth does not appear in actor evidence views.
- SQLite append-only journal reproduces accepted and rejected attempts.
- Offline demo and pytest run without APIs.
- README explicitly states legally unvalidated status.

## Acceptance: later German criminal MVP
- Versioned official rule sources, legal experts' review, court composition and dates.
- Hearing sequence, motions, objections, substantive-law question separation.
- Five independent participants + at least one optional human.
- No automatic endorsement of legal violations.
- Documented known coverage/limitations; legal conformance tests for each rule.

## Acceptance: appellate MVP
Separate Berufung vs Revision models, appealability/standing/deadlines, trial record restrictions, preserved objections where relevant, independent appellate agents, remand/reversal/affirmance, and ability for review courts themselves to err. Full event lineage.

## Observability / evaluation
Collect token cost, model IDs, seed, versions, actor turns, blocked security proposals, alleged violations, disagreement about findings, legal citations and confidence. Benchmark judge bias cautiously: simulator-model behaviors are not evidence of real-world judicial outcome rates.

## Safety
No real-case records by default. In rehearsal mode, informed opt-in and pause/stop; no compelled disclosures or undisclosed psychological profiling. See SECURITY and HUMAN_PARTICIPATION.
