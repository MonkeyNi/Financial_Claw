# Financial Analysis — PDF Consolidation Toolkit

Extract consolidated financial statements from annual and interim PDF disclosures, normalize numbers to millions, validate roll-ups where possible, and emit three audited Excel artefacts per issuer.

Implementation currently covers **data contracts, CLI wiring, cache/manifest helpers, validation primitives, and workbook skeletons**. Full PDF extraction and merge orchestration will land in follow-up iterations that map directly to `docs/superpowers/specs/2026-05-06-financial-pdf-extraction-design.md`.

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
```

### System dependencies

- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) for scanned tables
- [Poppler](https://poppler.freedesktop.org/) for `pdf2image`
- Java or Ghostscript (pick one) if you enable Camelot's lattice mode on tricky PDFs

Copy `.env.example` to `.env` and export the variables (or use `direnv`).

## CLI quickstart

```bash
python -m fa init --company POSCO --dry-run
python -m fa update --company POSCO --dry-run
python -m fa update --company POSCO --files path/to/new.pdf --dry-run
python -m fa update --company POSCO --files path/to/first.pdf --files path/to/second.pdf --dry-run
```

Non-dry runs raise `NotImplementedError` until the orchestration layer is finished.

## Tests

```bash
pytest
```

`pytest.ini` injects the local package path so you do not need `PYTHONPATH`.

## Excel tab naming note

Excel limits worksheet titles to 31 characters. The cash-flow + comprehensive income sheet uses `Cash Flow &Comprehensive Income` (31 chars). The rendered sheet still contains the full section headings described in the product spec.

## LLM hooks

Enable optional repair / matcher stages with:

```bash
export FA_ENABLE_LLM_TABLE_REPAIR=1
export FA_ENABLE_LLM_LINEITEM_MATCH=1
export OPENAI_API_KEY=...
```

The OpenAI-compatible client settings live in `fa/llm/client.py`.
