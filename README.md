# Financial Claw

Extract consolidated financial statements from annual and interim PDF disclosures, normalize numbers to millions, validate roll-ups where possible, and emit three audited Excel artefacts per issuer.

The current algorithm package lives under `src/financial_claw/`:

- `extractor/`: PDF profiling, statement page location, coordinate table extraction, OCR fallback wiring, and Excel output.
- `pipeline/`: company PDF discovery and incremental ingest planning.
- `ocr/mineru/`: MinerU API helpers and markdown/HTML-table conversion.
- `llm/minimax/`: MiniMax image table extraction helpers for future model-based fallback.
- `core/`: shared config, cache, normalization, validation, warnings, and merge helpers.

## Expected layout

```text
companies/
  POSCO/
    Financial_Statements/
      *.pdf
    final_excel/
      CompanyName_financial_statements_final.xlsx
      CompanyName_source_tracking.xlsx
      CompanyName_extraction_warnings.xlsx
      .cache/
      .processed.json
```

## Environment setup (WSL + conda)

```bash
conda activate base
python -m pip install -r requirements.txt
python -m pip install -e .
```

### System dependencies

- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) for scanned tables
- [Poppler](https://poppler.freedesktop.org/) for `pdf2image`
- Java or Ghostscript (pick one) if you enable Camelot's lattice mode on tricky PDFs

Copy `.env.example` to `.env` and export the variables (or use `direnv`).

## CLI quickstart

Commands below assume the package has been installed with `python -m pip install
-e .`. For one-off runs without installing, prefix commands with
`PYTHONPATH=src`, for example:

```bash
PYTHONPATH=src python -m financial_claw.extractor.cli --help
```

Run an initial company ingest. This scans every PDF under
`companies/POSCO/Financial_Statements/`, computes file hashes, and extracts each
PDF in parallel with up to 8 workers. MinerU OCR fallback is enabled by default;
only low numeric-density candidate pages are rendered and submitted to MinerU.
By default, company init writes outputs under
`companies/POSCO/final_excel/`.

```bash
python -m financial_claw.pipeline.ingest POSCO init
```

Preview the initial ingest plan without extracting PDFs.

```bash
python -m financial_claw.pipeline.ingest POSCO init --plan-only
```

Plan an incremental company ingest. If `companies/POSCO/final_excel/` has no
Excel outputs yet, it behaves like `init`; otherwise it uses `.processed.json`
to report only new or explicitly selected PDFs.

```bash
python -m financial_claw.pipeline.ingest POSCO update
```

Extract one PDF using embedded PDF text and coordinate-based table parsing. The
`--debug` flag writes page text, statement candidates, and metadata alongside
the Excel workbook.

```bash
python -m financial_claw.extractor.cli --pdf "companies/GOODMAN/Financial_Statements/2 Goodman 2025 Annual Report.pdf" --debug
```

Extract one PDF with MinerU OCR fallback enabled. This keeps the normal embedded
text path first, then renders low numeric-density candidate pages and sends only
those pages to MinerU precision mode.

```bash
python -m financial_claw.extractor.cli --pdf "companies/POSCO/Financial_Statements/POSCO Holdings_consolidated_FY25 1Q.pdf" --debug --ocr-provider mineru --mineru-mode precision --ocr-language en
```

Single-PDF extraction writes Excel and debug outputs under `outputs/` by default.

Merge a newly extracted workbook into an existing workbook. The command requires
both workbooks to contain exactly `Balance Sheet`, `Income Statement`, and
`Cash Flow Statement`; it writes a new file and leaves both inputs unchanged.

```bash
python -m financial_claw.core.workbook_merge \
  companies/LGENSO/final_excel/excel/LGENSO_234Q_LGES_Audit_Report_CONFS_en_statements.xlsx \
  companies/LGENSO/final_excel/excel/LGENSO_2024_LGES_Audit_Report_Consolidated_FS_ENG_statements.xlsx \
  -o companies/LGENSO/final_excel/LGENSO_merged.xlsx
```

## Tests

```bash
pytest
```

The project uses a `src/` layout. Install the package in editable mode or set `PYTHONPATH=src` before running tests.

## Excel tab naming note

Excel limits worksheet titles to 31 characters. The cash-flow + comprehensive income sheet uses `Cash Flow &Comprehensive Income` (31 chars). The rendered sheet still contains the full section headings described in the product spec.

## LLM hooks

Enable optional repair / matcher stages with:

```bash
export FA_ENABLE_LLM_TABLE_REPAIR=1
export FA_ENABLE_LLM_LINEITEM_MATCH=1
export OPENAI_API_KEY=...
```

MiniMax table-extraction settings live in `src/financial_claw/llm/minimax/minimax_api.py`.
