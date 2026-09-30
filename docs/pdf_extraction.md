# Detailed PDF extraction

This milestone captures source information before building or judging research. It does not compile an example report into a fixed analytical workflow. A future research task chooses its questions, methods, model, and exhibits according to the company and assignment. Source traceability, explicit uncertainty, and independently checked arithmetic remain shared requirements.

## Install and run

Fixture mode still has no runtime dependencies. PDF capture uses an optional pinned dependency set; development installs it for the invented-PDF tests.

```powershell
uv sync --locked --extra pdf
uv run --frozen --offline python -m research_lab ingest --input report_examples --role discovery
uv run --frozen --offline python -m research_lab extract-pdf --document DOCUMENT_ID
uv run --frozen --offline python -m research_lab dissect --document DOCUMENT_ID
uv run --frozen --offline python -m research_lab audit-extraction --document DOCUMENT_ID
```

Use `--root PATH` before the command to choose local storage. Intake remains capped at 64 MiB per source. PDF capture accepts at most 500 pages and renders at 300 DPI by default; `--dpi` accepts 96-300. A renderer/parser geometry disagreement stops capture rather than assigning incorrect coordinates. Incomplete attempts remain local and are not admitted as generator evidence.

`--ocr auto` prefers the local Windows English OCR engine, then a locally installed Tesseract with English traineddata. It makes no hosted calls or automatic OCR-model downloads. `--ocr windows` or `--ocr tesseract` requires that route and reports an error if unavailable. `--ocr none` retains native text and page images and explicitly marks OCR as not run. Windows OCR uses a child Windows PowerShell process with a process-scoped `RemoteSigned` execution policy; machine and user policy settings are not modified.

OCR covers full pages and additional enlarged crops of substantial embedded images. Small logos remain in the page render and image inventory. Crops can improve recognition but cannot recover detail absent from the original image. The host manages OCR language models; their exact model version is not exposed by the Windows API. The recipe records the OS build, language, adapter hash, parser versions, and settings. Use `--force` to capture again after a host-model change; previous captures are preserved.

## Captured information

Each source has a distinct extraction directory under ignored `data/derived/DOCUMENT_ID/EXTRACTION_ID/`:

| Artifact | Information |
| --- | --- |
| `manifest.json` | Source hash, extraction identity, recipe/code hashes, package versions, counts, limitations, and artifact-integrity inventory |
| `source.json` | Original corpus metadata; publication/availability remain unknown unless explicitly supported |
| `pages.jsonl` and `pages/page_NNN.json` | Native text; native and OCR words; fonts; normalized word boxes; OCR confidence when provided; image and drawing geometry; hyperlinks; heading and printed-page-label candidates; review flags |
| `spans.jsonl` | Unverified word and line observations compatible with `EvidenceSpan`, with source hash, zero-based page index, bounding box, method, and stable identifiers |
| `tables.jsonl` | Native table candidates, cells, raw transcriptions, coordinates, and links to source word IDs; merged headers and semantics remain unassigned |
| `pages/*.png` | Every rendered page and substantial image-region crops when OCR runs; retains charts, diagrams, captions, and unlabeled graphical information |
| `extraction.txt` | Page-separated native and OCR transcriptions; repeated observations intentionally retained |
| `review.html` and `pages/*.html` | Local inspection index and source images with switchable native/OCR overlays and selectable word IDs |

Native text and OCR are separate observations. They can disagree, repeat information, concatenate columns, or omit small glyphs. Font-size candidates are not verified section headings. Ambiguous footer labels remain candidates rather than an assumed page offset. OCR confidence is not a correctness probability or a fact-verification status.

The extractor does not silently create financial facts, interpret table headers, resolve conflicting sources, infer private analyst reasoning, or reconstruct unlabeled chart-series values. The full visual evidence is retained for later task-specific extraction and review. `dissect` exposes the captured evidence and structural candidates and returns no inferred rules for real PDFs.

## Cache and evidence boundary

An extraction is reused only when its recipe matches and its files pass integrity checks. The corpus stores a hash of the manifest in SQLite, outside the derived artifact directory. Changing both a cached file and its self-reported manifest does not make the cache authoritative. Source bytes are rechecked, registered file inventories are checked, and evidence span IDs, source hashes, and page bounds are validated before admission. Forced or changed-recipe captures create separate directories and registrations.

The generator continues to receive only `EvidenceView`. Corpus role and availability checks occur before reading PDF content or its extraction. Discovery captures do not become development evidence by copying an extraction file. These remain application boundaries, not an OS sandbox for arbitrary Python or cryptographic protection against a user editing the trusted corpus database.

## Separate extraction evaluation

`audit-extraction` verifies the registered capture and saves a separate evaluation in ignored `exports/`. Without a reference, it reports integrity and coverage and leaves quality unassessed. A private reference can test exact transcriptions at bounded source locations:

```json
{
  "schema_version": "1.0",
  "document_sha256": "ACTUAL_SOURCE_SHA256",
  "review_status": "draft",
  "checks": [
    {
      "check_id": "invented_sales_cell",
      "page_index": 0,
      "expected_text": "123,456",
      "bbox": [0.3, 0.1, 0.6, 0.3]
    }
  ]
}
```

```powershell
uv run --frozen --offline python -m research_lab audit-extraction --document DOCUMENT_ID --reference private_eval/extraction_reference.json
```

The extractor never reads that reference. Each check reports matching evidence IDs or a missing observation. A `draft` reference cannot produce the `reference_checks_passed` label reserved for a declared `reviewed` reference. Reviewer status is a supplied declaration, not independently authenticated approval.

Located text presence is only a component check. It does not verify numerical correctness, header/period/unit association, merged-cell structure, citation entailment, completeness of an analytical argument, or research usefulness. Build independent human-reviewed critical cells and claim/evidence relationships before claiming evaluator accuracy. Keep the report-specific references and corrections outside Git.

## Next work

Measure OCR and table errors across representative source regions, preserve reviewer corrections as explicit source-linked records, and choose task-specific evaluation criteria from the actual research question. Improve extraction where evidence is missing before adding report generation. Keep flexible analytical choices; any future reusable rule must be an optional, scoped hypothesis with review and counterexamples.
