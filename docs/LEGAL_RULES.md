# Legal rules, error simulation and appellate semantics

## Three-plane model
1. **Normative:** source-backed legal requirements, which can be mandatory, discretionary, disputed, or unknown.
2. **Actual:** observed attempted/accepted/contested actions; a court can commit a legal error without breaking the environment's security.
3. **Consequences:** contemporaneous challenges and later remedies; procedural violations do not automatically lead to reversal.

## Rule pack manifest (target)
```yaml
id: de-criminal-stpo
country: DE
court_type: amtsgericht-strafrichter
instance: first
valid_on: "YYYY-MM-DD"
source:
  authority: "official consolidated statute"
  uri: "https://www.gesetze-im-internet.de/stpo/"
  section: "explicit specific provision needed"
  retrieved_on: "YYYY-MM-DD"
review:
  status: unverified
  reviewer: null
```

Every executable rule requires coverage constraints, applicability, temporal validity, exact provenance, interpretation, priority/conflict handling, examples and regression tests. Link official current statutes rather than fabricated holdings: [StPO](https://www.gesetze-im-internet.de/stpo/), [GVG](https://www.gesetze-im-internet.de/gvg/), [ZPO](https://www.gesetze-im-internet.de/zpo/), [StGB](https://www.gesetze-im-internet.de/stgb/).

**No generic cross-examination abstraction.** German and US/UK procedures differ substantially; roles and questioning limits are pack-defined.

## Distinct dispositions
Model an initial judgment, an appeal filed, admissibility checked, record gathered, review conducted, outcome announced, possible remittal and finality as *separate* events. A judgment's factual correctness, legal validity and operative effect are distinct. Higher courts cannot automatically see sealed evaluator truth and can be mistaken.

German law distinguishes **Berufung** (normally a new factual/legal review in relevant cases) from **Revision** (review for errors of law under applicable standards); availability depends on the court and case. Details of StPO §§ 312 ff. and 333 ff. and § 354 must be verified against primary sources with effective dates before coding. Do not simplify to an always-available full retrial.

## Violation taxonomy
- Possible violation / disputed interpretation / acknowledged violation
- Actor mistake vs willful misconduct (intent is not inferred solely from output)
- Harmless, cured, preserved, forfeited or unknown effects
- Trial error, evidence treatment error, reasoning deficiency, denied right and reviewer error
- Security denial (cannot be bypassed) vs legal anomaly (may be enacted)

## Hard rule for implementers
The initial kernel's phase ordering and motion checks are **illustrations only**. They are not authoritative StPO or GVG translations.
