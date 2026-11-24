# Versioned legal knowledge service — design proposal

**Status: PROPOSED; not implemented or legally validated.**

## Recommendation
Revive https://github.com/luluthehungrycat/german-legal-rag as an independently usable knowledge service, expose a typed client interface in InDubioProAgente. Do not merge source repositories or let RAG determine authoritative procedure.

## Evidence-based source shortlist (verify current terms before ingestion)
- Federal consolidated statutes: https://www.gesetze-im-internet.de/ ; daily TOC https://www.gesetze-im-internet.de/gii-toc.xml ; XML by act. Official federal portal states XML is intended for automated reuse; consolidated text is not the official promulgation.
- Federal official published acts: https://recht.bund.de/ . Check change history and effective dates.
- Federal Rechtsinformationen / NeuRIS testing portal: https://testphase.rechtsinformationen.bund.de/ (open API announced, incomplete beta coverage; check API and licensing/reliability before relying on it).
- Federal decisions: https://www.rechtsprechung-im-internet.de/ .
- Open Legal Data: https://de.openlegaldata.io/pages/api/ for decisions, statutes and data dumps; check ODbL attribution/share-alike obligations.
- State law: per-Land official publications, including historical versions where available; there is no assumption that federal sources cover police laws of all Länder.

## Two clients, different semantics
1. **Normative ruleset**: explicit, human-reviewed executable constraints with exact source, date, applicability and uncertainty. Does not delegate binding transitions to an LLM or search-ranking score.
2. **Actor research tool**: may search and quote official law and decisions, with latency limits, sources and fallible interpretation. It must not be treated as binding legal judgment. Actors may disagree, cite inapplicable provisions or omit a source; the independent evaluator identifies such issues.

## Lookup contract (target)
```json
{
  "operation": "get_provision",
  "jurisdiction": "DE",
  "state": null,
  "statute_id": "StPO",
  "section": "example",
  "valid_on": "2026-11-24",
  "known_as_of": "2026-11-24",
  "snapshot_id": "content-addressed-corpus-version"
}
```
Response contains exact canonical provision and subdivision identifiers, machine-normalized text, primary URL, title, effective interval, last verified timestamp, source/derivation, amendment links, text digest, reliability/coverage warnings. Use **two** time dimensions where possible: legally effective on date X vs published/knowable by date Y. Don't leak future cases, decisions or enactments into historical trial simulations.

## Retrieval hierarchy
1. Resolve exact statute, paragraph, article and subsection from primary content, not vector nearest neighbor.
2. Lexical/BM25 and vector search for concept exploration; rerank, then resolve exact normative span.
3. Retrieve cited case law with court, docket/ECLI, decision date, hierarchy, citation context and availability date.
4. Validate citations against the pinned corpus and report missing/ambiguous results; never silently fill missing statutory text from model memory.

Use source checksums, atomic snapshots, cache invalidation, backoff, offline fallback, and legal version diffing. A **live** update only produces a new corpus snapshot; it does not silently change rules during a running trial.

## Role competence vs access
Public law is generally accessible. Model `preloaded_knowledge`, `research_access`, `expertise`, `search_strategy`, `jurisdiction_familiarity` and `available_research_time` separately. Lawyers can use more sophisticated case-law and strategy research; police and medical roles may start with narrower professionally relevant sources; a lay witness can look up publicly available law where scenario permits, but should not be magically expert or have undisclosed case knowledge.

## Litigation strategy
Counsel agents should be allowed private, sandboxed preparation: issue spotting, possible counterarguments, adversarial self-critique, planned witnesses/exhibits, document requests and adaptive updates. Do not give agents omniscient access to opposing strategy or privileged communications. Preparation outputs are actor-private until deliberately submitted or disclosed.

## Existing german-legal-rag gaps to assess
The current repo uses HTML scraping for BGB, split text + FAISS, BAAI/bge-m3 embeddings, and basic Hermes/OpenCode/Vibe adapters. Before reuse, migrate deprecated LangChain imports, model paragraph identity and version provenance, replace naive fixed chunks for exact lookup, add real update/cache policy and regression fixtures.

## Initial thin slice
Integrate a mock `LegalLookupClient` in tests; independently build official XML ingestion for one current act and verify exact section retrieval. Validate licensing and effective dates before calling it a production law tool.
