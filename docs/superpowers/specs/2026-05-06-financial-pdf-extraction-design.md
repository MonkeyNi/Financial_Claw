# Financial PDF Extraction Design

Date: 2026-05-06
Status: Approved for planning
Language: Python

## 1. Goal

Build a Python system that extracts consolidated financial statements from annual and quarterly PDF reports, normalizes values to millions (preserving original currency), validates financial logic, and generates standardized Excel outputs per company.

The system must support:
- initialization from all existing PDFs;
- incremental update from newly added PDFs;
- conservative extraction behavior with warnings instead of silent risky merges.

## 2. Scope and Constraints

### 2.1 In Scope

- Input format: PDF only.
- Statements to extract:
  - Consolidated Balance Sheet / Statement of Financial Position
  - Consolidated Income Statement / Profit or Loss
  - Consolidated Cash Flow Statement
  - Consolidated Comprehensive Income Statement (if available)
- Output files per company:
  - `<Company>_financial_statements_final.xlsx`
  - `<Company>_source_tracking.xlsx`
  - `<Company>_extraction_warnings.xlsx`
- Currency preserved, no FX conversion.
- Unit normalization to millions.
- Union-based line-item merge across periods.
- Validation coloring in Excel.
- Incremental update with conflict columns.

### 2.2 Out of Scope

- Non-PDF input types.
- Global accounting taxonomy standardization for all line items.
- FX conversion.
- Reprocessing all historical files during incremental mode unless explicitly requested.

## 3. Directory and Data Layout

Canonical layout (as chosen):

```text
companies/
  GOODMAN/
    Financial_Statements/
      *.pdf
    final_excel/
  LGENSO/
    Financial_Statements/
    final_excel/
  POSCO/
    Financial_Statements/
    final_excel/
  SKHYNIX/
    Financial_Statements/
    final_excel/
```

Notes:
- Existing data may require one-time reorganization into this structure.
- Ignore legacy paths and scripts during implementation:
  - `Financial_Statment/tmp`
  - `extract_financial_statements.py`
  - `Financial_Statment/GOODMAN`
  - `Financial_Statment/LGENSO`
  - `Financial_Statment/POSCO`
  - `Financial_Statment/SKHYNIX`

## 4. Architecture

### 4.1 Package Structure

```text
fa/
  cli.py
  config.py
  models.py
  ingest.py
  classify.py
  locate.py
  extract/
    text.py
    ocr.py
    repair.py
  normalize.py
  merge.py
  validate.py
  export.py
  incremental.py
  cache.py
  warnings_log.py
  llm/
    client.py
    matcher.py
    vision.py
```

### 4.2 Pipeline

1. Discover PDFs for a company (`ingest.py`).
2. Classify each report (annual/quarterly + period).
3. Locate consolidated statement pages by keyword/layout rules.
4. Extract tables:
   - text path first (`pdfplumber` + `camelot`);
   - OCR fallback (`pytesseract`) when text extraction is unavailable;
   - vision-LLM table repair for low-confidence OCR/table outputs.
5. Normalize:
   - parse numeric strings and signs;
   - parse currency and unit;
   - convert all amounts to millions.
6. Merge line items across periods (union-based).
7. Apply validation rules with rounding-aware tolerance.
8. Export 3 Excel files with formatting and traceability.

### 4.3 Caching Strategy

- Disk cache at `companies/<Company>/final_excel/.cache/`.
- Cache per step and per input file hash.
- Reuse intermediate artifacts when source hash and config fingerprint are unchanged.
- `--rebuild` bypasses cache.

## 5. LLM Integration Design

LLM interfaces are reserved and optional.

### 5.1 Enabled Hook Points

1. Table extraction repair (hook #3):
   - Trigger only on low-confidence OCR/table extraction cases.
   - Input: page image/text + statement context.
   - Output: structured table JSON.

2. Line-item equivalence judgment (hook #5):
   - Trigger only for ambiguous near-matches after deterministic/fuzzy rules.
   - Input: candidate pair + section/hierarchy/neighbor context.
   - Output: equivalent/not equivalent + score + reason.

### 5.2 Provider Abstraction

- OpenAI-compatible API interface.
- Configurable via environment variables:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`
  - `OPENAI_VISION_MODEL`
- No-op implementations are available so the pipeline runs without LLM keys.

## 6. Extraction and Normalization Rules

### 6.1 Extraction Priority

- Always prefer consolidated statements.
- If not found, emit warning and continue.

### 6.2 Quarterly Rule

- Prefer single-quarter values.
- If only YTD is available, warn and use fallback only when necessary.

### 6.3 Number Parsing

- Parentheses indicate negative values.
- Footnote markers are stripped.
- Dashes are interpreted as zero or blank using explicit report context rules; ambiguous cases become blank with warning.

### 6.4 Unit and Currency

- Parse from headers/footnotes/surrounding text.
- Convert all numeric values to millions.
- Preserve source currency.
- If multiple currencies across reports for one company, continue and mark workbook metadata accordingly.

## 7. Line Item Merge Strategy

### 7.1 Matching Order

1. Exact normalized text match.
2. High-confidence fuzzy match with statement/section context.
3. LLM decision for gray-zone candidates only.
4. If still uncertain, keep separate rows and emit warning.

### 7.2 Naming and Ordering

- Use union of all line items across periods.
- Missing values stay blank.
- Merged line-item display name uses latest available report naming.
- Default row order follows latest available report; orphan earlier-only rows are inserted at nearest logical location or appended within section.
- Preserve hierarchy depth for indentation in Excel.

## 8. Validation Design

### 8.1 Rule Engine

- Validation rules are declarative and statement-specific.
- Apply only when component rows are clearly present.
- Skip non-checkable cells (no pass/fail color).

### 8.2 Tolerance Policy

- Use rounding-aware tolerance in millions (not strict zero).
- Deterministic formula:
  - tolerance = max(0.5, 0.5 * 10^(-decimals_kept_after_conversion))
  - default `decimals_kept_after_conversion = 0`, so default tolerance is `0.5` million.
- This value is configurable through CLI/config to support stricter validation when needed.
- Purpose: avoid false failures from unit-conversion rounding.

### 8.3 Visual Marking

- Pass: green highlight.
- Fail: red highlight.
- Non-checkable: uncolored.

## 9. Excel Output Design

### 9.1 Main Workbook Sheets

- `Balance Sheet`
- `Income Statement`
- `Cash Flow & Comprehensive Income`

In `Cash Flow & Comprehensive Income`, comprehensive income is placed below cash flow.

### 9.2 Column Layout

- Annual columns on left, oldest to newest.
- One blank separator column.
- Quarterly columns on right, oldest to newest.

### 9.3 Top Metadata

Each sheet contains:
- Currency info (`Multiple currencies detected` when applicable)
- Unit info (`millions`)

### 9.4 Formatting

- Freeze top metadata/header region and first column.
- Bold headers, subtotals, totals.
- Keep indentation hierarchy.
- Number format: `#,##0;(#,##0);-`

## 10. Incremental Update Design

Two input selection modes are supported:

1. Auto-detect mode:
   - Use manifest at `companies/<Company>/final_excel/.processed.json`.
   - Process only files whose content hash is unseen.

2. Explicit file mode:
   - CLI `--files` list overrides auto-detect selection.

Conflict handling:
- If `(statement, line_item, period)` already exists with a different value, insert conflict column:
  - `2024 Conflict - <ReportName>.pdf`
  - `Q1 2024 Conflict - <ReportName>.pdf`
- Keep original value untouched.
- Record warning event.

## 11. Traceability Artifacts

### 11.1 Source Tracking

`<Company>_source_tracking.xlsx` includes:
- company name
- source PDF name
- report type
- fiscal year/quarter
- statement type
- extracted page number
- original currency
- original unit
- converted unit
- extraction timestamp
- OCR used
- warnings summary

### 11.2 Warning File

`<Company>_extraction_warnings.xlsx` includes:
- company name
- source PDF
- severity (`Info`, `Warning`, `Critical`)
- statement type
- period
- page number
- issue type
- issue description
- suggested action
- timestamp

## 12. CLI Contract

Planned commands:

```bash
python -m fa init --company POSCO
python -m fa update --company POSCO
python -m fa update --company POSCO --files "path/a.pdf" "path/b.pdf"
python -m fa init --company POSCO --rebuild
python -m fa update --company POSCO --dry-run
```

## 13. Dependencies

`requirements.txt` will include at least:

- Core/config/CLI:
  - `pydantic`
  - `PyYAML`
  - `python-dateutil`
  - `typer`
  - `rich`
- PDF/table extraction:
  - `pdfplumber`
  - `camelot-py`
  - `pypdf`
- OCR:
  - `pytesseract`
  - `pdf2image`
  - `Pillow`
- Data processing:
  - `pandas`
  - `numpy`
- Excel:
  - `openpyxl`
  - `XlsxWriter`
- Matching:
  - `rapidfuzz`
- LLM/API:
  - `openai`
  - `httpx`
  - `tenacity`
- Utility/testing:
  - `orjson`
  - `pytest`
  - `pytest-cov`

System-level runtime prerequisites to document in README:
- Tesseract OCR binary
- Poppler tools (for PDF image conversion)
- Camelot runtime prerequisites depending on extraction mode

## 14. README Requirements

`README.md` must document:
- project purpose and scope;
- folder layout and file naming conventions;
- install steps (Python + system dependencies);
- environment variables and LLM toggle behavior;
- init/update command usage;
- interpretation of warning/source-tracking files;
- validation behavior and tolerance;
- troubleshooting guidance;
- test commands.

## 15. Testing Strategy

### 15.1 Unit Tests

- number parsing and sign handling;
- unit conversion to millions;
- period sorting and column generation;
- merge and conflict-column insertion logic;
- validation formula calculations and tolerance behavior.

### 15.2 Integration Tests

- text-based PDF happy path;
- OCR-required page path;
- LLM disabled path;
- LLM-enabled ambiguous match/repair path.

## 16. Delivery Sequence

1. Scaffold package, models, and CLI.
2. Implement text extraction path.
3. Implement normalize/merge/export baseline.
4. Add validation engine.
5. Add OCR fallback path.
6. Add LLM hooks (#3 and #5).
7. Add incremental update manifest + explicit file mode.
8. Complete tests, docs, and dependency lock-in.

## 17. Risks and Mitigations

- Scanned table quality risk:
  - Mitigation: OCR confidence thresholds + vision-LLM repair path + warning traceability.
- Over-merge risk for similar line names:
  - Mitigation: conservative 3-tier matching with LLM only in gray zone and explicit warning on uncertainty.
- Runtime cost risk:
  - Mitigation: cache intermediates and keep LLM calls sparse.
- Reproducibility risk from LLM:
  - Mitigation: log prompt fingerprints/model identifiers in warning metadata for auditable decisions.

## 18. Acceptance Confirmation

This design reflects the agreed decisions:
- Python implementation;
- OpenAI-compatible LLM API abstraction;
- LLM reserved for table repair fallback and line-item ambiguity handling;
- clear dependency declaration (`requirements.txt`) and project usage documentation (`README.md`);
- ignore legacy locations listed in Section 3 notes during implementation.
