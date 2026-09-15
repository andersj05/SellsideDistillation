# Data contracts (schema 1.0)

The runtime validates direct dataclass construction as well as decoded JSON: types, enum values, unknown fields, versions, decimal strings, dates, source hashes, and core invariants. JSON rejects duplicate keys and non-finite constants. Unsupported objects are not coerced into strings. Schema versions other than 1.0 fail explicitly; there is no silent migration.

| Record | Meaning |
| --- | --- |
| Document | Immutable content identity, first filename, corpus role, publication/availability evidence, parser/review status |
| EvidenceSpan | Parent document/hash, exact extracted text, excerpt, extraction method, stable source locator |
| Fact | Entity, metric, Decimal-compatible value, original display value, units/scale, period, basis, actual/forecast/assumption classification, source spans, availability |
| Claim | Text, fact/forecast/assumption/judgment/unknown type, observed/inferred/proposed origin, verification, materiality, evidence and calculation links, qualifiers/gaps |
| Calculation | Registered formula/version, named input fact IDs, exact outputs, output units, display policy and tolerance |
| Rule | Version, scope, exceptions, actions/checks, missing-input behavior, supporting discovery locations, review status and alternatives |
| Task | Neutral question, entity, cutoff, source ID/hash allowlist, required sections and output budget. No evaluator paths or answers. |
| RunRecord | Route/configuration, task/protocol/playbook/code/lock/source hashes, budget, usage, status, stop reason and timestamps |

## Locations

Text locators are one-based original lines, including skipped blank lines in the numbering: `line:7`. CSV locators are one-based **logical data records**, excluding the header: `record:2`. Quoted CSV fields may span several physical lines; record IDs avoid confusing those with line numbers.

PDF fields reserve a zero-based page index, printed page label, and normalized top-left bounding box `[x0, y0, x1, y1]`. They remain null for native text and CSV; the current intake does not invent PDF coordinates.

Evidence IDs combine the document SHA-256 identity and locator. Normalized fact IDs derive from their evidence span. Different vintages and conflicting rows remain separate records.

## Curated financial CSV

Every financial input row requires these columns:

```csv
entity_id,metric,value,displayed_value,unit,scale,period_start,period_end,period_type,accounting_basis,value_type,scenario,available_at
```

Example:

```csv
synthetic_company,revenue,1200,"1,200",USD,million,2026-01-01,2026-12-31,fiscal_year,synthetic_adjusted_diluted_v1,forecast,base,2026-02-20T07:00:00-05:00
```

Values are decimal strings. Ratios use `0.20` for 20%; the original `displayed_value` can retain `20%`. Intake does not automatically parse financial punctuation or infer scale from a footnote. Ordinary CSV remains inspectable without being treated as normalized facts.

The fixture decimal grammar accepts optional sign, decimal point, and scientific exponent. It limits input strings to 96 characters, coefficients to 64 digits, adjusted exponent to at most 48, and stored exponent to at least -64. Whitespace and digit separators are rejected. Arithmetic uses a private 64-digit, half-even context; display quantizes to cents with half-up rounding. Equivalent decimal spellings compare by value.

Supported units: `USD`, `shares`, `ratio`, `multiple`. Supported scales: `one`, `million`, `billion`. The initial operation requires USD millions and diluted shares in millions. It deliberately rejects individual-share inputs until an explicit normalization step is available.

The operation accepts matching entity, period, period type, accounting basis, and metric-definition version. Historical actuals, guidance, and consensus cannot silently replace fixture forecasts/assumptions. Negative pretax income is outside the deliberately simple tax model.

## Availability and corpus roles

Roles are `discovery`, `development`, `locked_evaluation`, and `archive`. The current generator tool boundary permits only explicitly allowlisted development sources. Discovery note content feeds the playbook compilation stage; evaluator references never enter the task or evidence capability.

Publication and first availability are distinct fields. Missing availability stays null and is excluded. The source document and each fact must be available by the timezone-aware task cutoff. Rejected content is not returned through direct span reads, search, or financial-fact queries.

## Interpretation of verification

`observed` means present in the source; it does not mean true. `inferred` means a reconstruction hypothesis. `proposed` means a lab procedure or newly calculated analytical statement. Verification is a separate dimension.

The fixture's verified forecast claims mean that the displayed arithmetic and closed-form statements were checked against invented inputs. They are not verified predictions. Human review, broad citation entailment, analytical usefulness, and correction effort remain pending.

Passing the closed fixture grader requires all three scenarios and 15 numerical outputs, supported claims for all required questions, and complete matching fact/span/calculation lineage. Unknown claims remain unresolved. Evaluations record their grader version, grader source hash, and oracle hash. Every regrade is a distinct derivative artifact.
