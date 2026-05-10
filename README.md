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

- Python ≥ 3.11
- Install: `pip install -r requirements.txt` and `pip install -e .`
- Core PDF stack: PyMuPDF (text geometry, page rasterization)

**External services (optional)**

- MinerU: API token for precision OCR; see `src/financial_claw/ocr/mineru/.env.example` (`MINERU_API_TOKEN`, …)
- LLM toggles: root `.env.example` — `ENABLE_LLM_TABLE_REPAIR`, `ENABLE_LLM_LINEITEM_MATCH`, `OPENAI_*`
- MiniMax helpers: `src/financial_claw/llm/minimax/.env.example`

**Local execution without editable install**

```bash
PYTHONPATH=src python -m financial_claw.extractor.cli --help
```

---

## Capabilities

| Capability | Role |
|------------|------|
| Company ingest | Discover PDFs, SHA-256 manifests, parallel extraction (≤ 8 workers), merge successful runs into company final workbook |
| Incremental update (target) | Existing summary workbook + new PDFs → extract each PDF → merge into master in chronological column order |
| Single-PDF CLI | Full locate → extract → Excel for one file (`--debug`, `--ocr-provider mineru`, …) |
| Workbook merge | Union two or more compliant workbooks on shared sheet names and period semantics |

### Company ingest

- **Inputs:** `companies/<Company>/Financial_Statements/*.pdf`
- **Outputs:** `companies/<Company>/final_excel/excel/*_statements.xlsx`, debug under `final_excel/debug/`; manifest `final_excel/.processed.json`
- **Final merge (init success):** `companies/<Company>/<Company>_financial_statements_final.xlsx`

```bash
python -m financial_claw.pipeline.ingest POSCO init
python -m financial_claw.pipeline.ingest POSCO init --plan-only
python -m financial_claw.pipeline.ingest POSCO update
```

### Single-PDF extraction

- Default output root: `outputs/` (overridden when invoked from ingest)

```bash
python -m financial_claw.extractor.cli --pdf "companies/GOODMAN/Financial_Statements/example.pdf" --debug
python -m financial_claw.extractor.cli --pdf "companies/POSCO/Financial_Statements/example.pdf" \
  --debug --ocr-provider mineru --mineru-mode precision --ocr-language en
```

### Workbook merge

- **Constraint:** Each workbook must contain exactly these sheets, in order: `Balance Sheet`, `Income Statement`, `Cash Flow Statement`

```bash
python -m financial_claw.core.workbook_merge \
  path/to/first_statements.xlsx \
  path/to/second_statements.xlsx \
  -o path/to/merged.xlsx
```

---

## Repository layout (`src/financial_claw/`)

| Path | Responsibility |
|------|------------------|
| `extractor/` | PDF profiling, statement localization, table extraction, Excel writer |
| `pipeline/` | Discovery, ingest planning, parallel init orchestration |
| `ocr/mineru/` | MinerU client, markdown/HTML table conversion |
| `llm/minimax/` | MiniMax API utilities for image/table experiments |
| `core/` | Normalization, validation, workbook merge, caches |

---

## Typical workspace tree

```text
companies/
  POSCO/
    Financial_Statements/
      *.pdf
    POSCO_financial_statements_final.xlsx
    final_excel/
      excel/
        *_statements.xlsx
      .processed.json
```

---

## Data format (merged outputs)

- **Scale:** Numeric columns follow disclosure units where identifiable (commonly **millions**); verify unit phrases in source PDFs and extraction metadata.
- **Sheet layout:** Annual periods occupy **left** column block; quarterly periods occupy **right** block (blank column separator when both blocks exist).
- **Chronology:** Within annual and within quarterly blocks, columns are ordered **earliest → latest** (left → right).
- **Merge ordering:** Input workbooks are composed so resulting period columns preserve that temporal ordering across sources.
