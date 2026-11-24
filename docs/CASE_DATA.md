# Case data, provenance and perspective seeding — design proposal

**Status: PROPOSED, not implemented; awaiting project-owner review.** Do not treat public judgments as a complete case record. Real cases are optional: synthetic cases remain the safe default for tests.

## Goal
Ingest publicly obtainable case records, reconstruct what was known or available at a **specified point in time**, and provide each authorized simulation participant with a distinct starting perspective. Documentary availability, epistemic knowledge and lawful disclosure are separate dimensions.

## Source candidates and caveats
- German official decisions: https://www.rechtsprechung-im-internet.de/ and available decisions from state judiciary websites. Published reasons often report findings **after** the trial, not contemporaneous evidence.
- Open Legal Data: https://de.openlegaldata.io/ (API, bulk dumps); https://huggingface.co/datasets/openlegaldata/court-decisions-germany . Generally decisions, not full evidence bundles.
- US CourtListener/RECAP: https://www.courtlistener.com/recap/ (some filed motions, dockets, pleadings and exhibits; incomplete, authentication and redistribution rules vary).
- Public inquiry archives, official releases and legitimately reusable reporting may be case-specific. Reporting and editorial transcripts cannot be silently treated as official evidence.
- No attempt to obtain sealed files, breach accounts, impersonate litigants, or evade restrictions.

## Data pipeline
```
Source catalog + license/privacy review
   -> fetch approved documents (URL, retrieval timestamp, digest)
   -> parse/OCR only when needed; retain original and confidence
   -> document classification + timeline + chain-of-provenance
   -> extracted claims with citation, uncertainties and contradictions
   -> provenance/rights and human review
   -> dated disclosure events / actor-specific knowledge projections
   -> immutable scenario manifest and deterministic case replay
```

### Required conceptual fields
`source_id`, URL/authority, collection/retrieval dates, hash, redistribution status, privacy flags, case-id, document date, case event date, *availability date*, disclosure date per actor/role, text spans/pages, extraction method/confidence, authenticity status, existence-known vs contents-known, and sealed evaluator-only status.

Model distinctions:
1. Objective historical facts **not automatically knowable**; in a reconstruction, often unknown.
2. Allegations and observations with contested status.
3. Documents and exhibits existing by cutoff, separately indexed from documents *disclosed* by cutoff.
4. Participant knowledge/memory: personal experience and prior disclosures; witness may know a fact without having seen the case file.
5. Trial-admitted evidence, legally established findings and post-trial judgment.
6. Later events and appeal outcomes: excluded from opening-day agent contexts.

A missing document means **unknown/unavailable**, not proof of its nonexistence. Never manufacture a historically real witness statement or exhibit without prominently marking it as synthetic. Permit a case to be graded as *insufficient publicly available evidence for faithful reconstruction*.

## Disclosure and access rules
A jurisdiction-specific rule pack determines legal entitlement, disclosed materials and exceptions. A role label alone is insufficient: defense counsel, defendant, prosecution, judge, witness and expert may have different legal rights and actual knowledge. Confidential consultations and protected identities are isolated. A public case-file article should not be automatically provided to all participants. Publicity and legal accessibility are different from realistic preloaded knowledge.

## Privacy and redistribution
Court records can contain personally identifying information, medical facts and information about victims/minors. Public availability is not blanket authorization to republish or simulate sensitive content. Assess GDPR, personality rights, licensing/usage terms, retention and redaction; default to anonymized or synthetic material and refrain from automatic external sharing.

## Initial thin slice
Use *one* hand-curated, non-sensitive public document plus synthetic supplemental evidence with unambiguous labels. Freeze a date and test that defense receives a permitted disclosure, witness does not receive internal prosecution notes, and nobody gets a future judgment. Do not ingest entire real case records initially.

## Open questions
What is the project policy for identifiable real participants? Which jurisdictions and data sources permit redistribution? Can licensed/private datasets be used in a restricted local mode? Who reviews factual characterization before publication?
