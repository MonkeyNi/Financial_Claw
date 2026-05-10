# Financial Claw

Pipeline for extracting consolidated financial statements from issuer PDFs (annual and interim), emitting structured Excel workbooks with traceability and optional OCR (MinerU) and LLM-sidecar tooling.

---

## Scope

| Concern | Behavior |
|--------|----------|
| Input | Disclosure PDFs under per-company `Financial_Statements/` |
| Primary output | Statement sheets (`Balance Sheet`, `Income Statement`, `Cash Flow Statement`) plus per-PDF extraction records |
| Merge | Sequence of extracted workbooks merged into a single rolling workbook with aligned periods |

---

## Environment

**Runtime**

- Python >= 3.11
- Install: `pip install -r requirements.txt` and `pip install -e .`
- Core PDF stack: PyMuPDF (text geometry, page rasterization)

**External services (optional)**

- MinerU: API token for precision OCR; see `src/financial_claw/ocr/mineru/.env.example` (`MINERU_API_TOKEN`)
- LLM toggles: root `.env.example` - `ENABLE_LLM_TABLE_REPAIR`, `ENABLE_LLM_LINEITEM_MATCH`, `OPENAI_*`
- MiniMax helpers: `src/financial_claw/llm/minimax/.env.example`

**Local execution without editable install**

```bash
PYTHONPATH=src python -m financial_claw.extractor.cli --help
```

---

## Capabilities

| Capability | Role |
|------------|------|
| Company ingest | Discover PDFs, skip processed SHA-256s from company config, parallel extraction (max 8 workers), merge successful runs into company final workbook |
| Incremental update | Existing final workbook + new or changed PDFs -> extract selected PDFs -> rebuild master in chronological column order |
| Single-PDF CLI | Full locate -> extract -> Excel for one file (`--debug`, `--ocr-provider mineru`, etc.) |
| Workbook merge | Union two or more compliant workbooks on shared sheet names and period semantics |

### Company Ingest

- **Inputs:** `companies/<Company>/Financial_Statements/*.pdf`
- **Outputs:** `companies/<Company>/final_excel/excel/*_statements.xlsx`, debug under `final_excel/debug/`
- **Company config:** `companies/<Company>/<Company>_config.json`
- **Final merge:** `companies/<Company>/<Company>_financial_statements_final.xlsx`

The normal command only needs the company name. The pipeline resolves whether the run is a first-time init or an incremental update.
It skips reports already recorded in the company config by SHA-256.
If no final workbook exists, it performs an initial build.
If a final workbook exists, it processes only new or changed PDFs.
After each successful run, `processed_reports` in the company config is updated.

```bash
python -m financial_claw.pipeline.ingest POSCO
python -m financial_claw.pipeline.ingest POSCO --plan-only
```

Legacy explicit modes are still accepted for compatibility: `init`, `update`, and `run`.
Default logs show only core progress at `INFO`; implementation details such as paths, hashes, page candidates, OCR fallback pages, and merge internals are emitted at `DEBUG`.

Run all companies from the repository root:

```powershell
.\tests\run_all_company_init.ps1
```

```bash
bash tests/run_all_company_init.sh
```

### Windows Desktop UI

A simple WPF desktop shell is available at `desktop/FinancialClaw.Desktop/`.
It is intended for non-technical Windows users:

- scans the repository `companies/` folder
- runs the unified company update command for each company
- shows per-company progress
- shows the save folder
- keeps detailed run output in the details panel

The desktop shell uses WPF with the `WPF-UI` component package for modern Windows-style controls.

Build/run from a machine with the .NET 6 SDK installed:

```powershell
dotnet run --project desktop\FinancialClaw.Desktop\FinancialClaw.Desktop.csproj
```

Or use the Windows launcher from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_financial_claw.ps1
```

For double-click launch without a console window, use `start_financial_claw.vbs`.
`start_financial_claw.bat` is kept for command-line troubleshooting.

The UI calls the existing Python pipeline, so Python dependencies must still be installed:

```powershell
pip install -r requirements.txt
pip install -e .
```

Company config shape:

```json
{
  "config_version": 1,
  "statement_keywords": {
    "balance_sheet": ["consolidated statements of financial position"],
    "income_statement": ["consolidated statements of profit or loss"],
    "cash_flow": ["consolidated statements of cash flows"]
  },
  "processed_reports": [
    {
      "file_name": "example.pdf",
      "source_path": "Financial_Statements/example.pdf",
      "sha256": "...",
      "mtime": 1778373821.0,
      "output_workbook": "final_excel/excel/COMPANY_example_statements.xlsx",
      "processed_at": "2026-05-10T00:00:00+00:00"
    }
  ]
}
```

### Single-PDF Extraction

- Default output root: `outputs/` (overridden when invoked from ingest)

```bash
python -m financial_claw.extractor.cli --pdf "companies/GOODMAN/Financial_Statements/example.pdf" --debug
python -m financial_claw.extractor.cli --pdf "companies/POSCO/Financial_Statements/example.pdf" \
  --debug --ocr-provider mineru --mineru-mode precision --ocr-language en
```

### Workbook Merge

- **Constraint:** Each workbook must contain exactly these sheets, in order: `Balance Sheet`, `Income Statement`, `Cash Flow Statement`

```bash
python -m financial_claw.core.workbook_merge \
  path/to/first_statements.xlsx \
  path/to/second_statements.xlsx \
  -o path/to/merged.xlsx
```

---

## Repository Layout (`src/financial_claw/`)

| Path | Responsibility |
|------|------------------|
| `extractor/` | PDF profiling, statement localization, table extraction, Excel writer |
| `pipeline/` | Discovery, ingest planning, parallel company run orchestration |
| `ocr/mineru/` | MinerU client, markdown/HTML table conversion |
| `llm/minimax/` | MiniMax API utilities for image/table experiments |
| `core/` | Normalization, validation, workbook merge, caches |

---

## Typical Workspace Tree

```text
companies/
  POSCO/
    Financial_Statements/
      *.pdf
    POSCO_config.json
    POSCO_financial_statements_final.xlsx
    final_excel/
      excel/
        *_statements.xlsx
      debug/
```

---

## Data Format

- **Scale:** Numeric monetary columns are normalized to **millions** when units are identifiable.
- **Sheet layout:** Annual periods occupy the left column block; quarterly periods occupy the right block, with a blank column separator when both blocks exist.
- **Quarter labels:** Duration-specific interim columns use labels such as `3-Month Q3 2024` or `9-Month Q3 2024`; if no duration is explicit, labels use `Q3 2024`.
- **Chronology:** Within annual and quarterly blocks, columns are ordered earliest -> latest, left -> right.
- **Merge ordering:** Input workbooks are composed so resulting period columns preserve that temporal ordering across sources.
