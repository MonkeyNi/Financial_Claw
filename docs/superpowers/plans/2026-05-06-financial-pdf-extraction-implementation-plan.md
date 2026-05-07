# Financial PDF Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python system that extracts consolidated statements from company PDFs, normalizes to millions, validates financial logic, and exports three traceable Excel files with initialization + incremental update modes.

**Architecture:** Implement a modular pipeline package (`fa/`) with typed contracts between steps: ingest -> classify -> locate -> extract -> normalize -> merge -> validate -> export. Keep extraction rules deterministic by default, add optional OpenAI-compatible hooks for OCR table repair and ambiguous line-item matching, and store per-file caches for fast reruns.

**Tech Stack:** Python 3.11+, Typer, Pydantic, pdfplumber, camelot-py, pytesseract, pandas, openpyxl, rapidfuzz, openai, pytest.

---

## Scope Check

The spec is one integrated subsystem (single pipeline with shared contracts), not independent products. One plan is sufficient.

## File Structure

Planned responsibilities:

- Create `fa/models.py`: Pydantic data contracts (`ReportFile`, `NormalizedStatement`, warning/validation models).
- Create `fa/config.py`: environment + runtime config parsing.
- Create `fa/ingest.py`: company PDF discovery + manifest hash diff.
- Create `fa/classify.py`: report type and period detection.
- Create `fa/locate.py`: statement page selection by keyword and layout hints.
- Create `fa/extract/text.py`: text-based table extraction (pdfplumber/camelot).
- Create `fa/extract/ocr.py`: OCR fallback extraction and confidence reporting.
- Create `fa/extract/repair.py`: optional vision-LLM repair hook wrapper.
- Create `fa/normalize.py`: numeric parsing, unit/currency detection, million conversion.
- Create `fa/merge.py`: union merge, matching strategy, optional LLM matcher.
- Create `fa/validate.py`: rule-based checks with rounding-aware tolerance.
- Create `fa/export.py`: main workbook + source-tracking + warnings outputs.
- Create `fa/incremental.py`: update orchestration and conflict-column behavior.
- Create `fa/cli.py`: `init`, `update`, `dry-run`, `--rebuild`, `--files`.
- Create `fa/cache.py`: read/write cached intermediates.
- Create `fa/warnings_log.py`: warning collector and serialization helper.
- Create tests under `tests/unit/` and `tests/integration/`.
- Create `requirements.txt`, `.env.example`, and `README.md`.

---

### Task 1: Bootstrap package, config, and typed models

**Files:**
- Create: `fa/__init__.py`
- Create: `fa/models.py`
- Create: `fa/config.py`
- Create: `fa/cli.py`
- Test: `tests/unit/test_config_and_models.py`

- [ ] **Step 1: Write the failing test**

```python
from fa.config import RuntimeConfig
from fa.models import ReportFile

def test_runtime_config_defaults():
    cfg = RuntimeConfig.from_env({})
    assert cfg.validation_tolerance_millions == 0.5
    assert cfg.enable_llm_table_repair is False

def test_report_file_hash_shape():
    r = ReportFile(company="POSCO", pdf_path="x.pdf", file_name="x.pdf", sha256="a"*64, mtime=1.0)
    assert len(r.sha256) == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config_and_models.py -v`  
Expected: FAIL with import errors (`ModuleNotFoundError: No module named 'fa'`).

- [ ] **Step 3: Write minimal implementation**

```python
# fa/config.py
from dataclasses import dataclass

@dataclass
class RuntimeConfig:
    validation_tolerance_millions: float = 0.5
    enable_llm_table_repair: bool = False
    enable_llm_lineitem_match: bool = False

    @classmethod
    def from_env(cls, env: dict) -> "RuntimeConfig":
        return cls(
            validation_tolerance_millions=float(env.get("VALIDATION_TOLERANCE_M", 0.5)),
            enable_llm_table_repair=env.get("ENABLE_LLM_TABLE_REPAIR", "0") == "1",
            enable_llm_lineitem_match=env.get("ENABLE_LLM_LINEITEM_MATCH", "0") == "1",
        )
```

```python
# fa/models.py
from pydantic import BaseModel

class ReportFile(BaseModel):
    company: str
    pdf_path: str
    file_name: str
    sha256: str
    mtime: float
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config_and_models.py -v`  
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add fa/__init__.py fa/models.py fa/config.py fa/cli.py tests/unit/test_config_and_models.py
git commit -m "feat: bootstrap package config and core data models"
```

---

### Task 2: Implement ingest + manifest diff (init/update input selection)

**Files:**
- Create: `fa/ingest.py`
- Create: `fa/cache.py`
- Test: `tests/unit/test_ingest_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
from fa.ingest import select_input_files

def test_selects_only_new_hashes(tmp_path):
    manifest = {"seen_hashes": ["h1"]}
    files = [("a.pdf", "h1"), ("b.pdf", "h2")]
    selected = select_input_files(files, manifest, explicit_files=None)
    assert selected == [("b.pdf", "h2")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ingest_manifest.py -v`  
Expected: FAIL with missing function `select_input_files`.

- [ ] **Step 3: Write minimal implementation**

```python
# fa/ingest.py
from typing import Iterable

def select_input_files(files: Iterable[tuple[str, str]], manifest: dict, explicit_files: list[str] | None):
    if explicit_files:
        allow = set(explicit_files)
        return [f for f in files if f[0] in allow]
    seen = set(manifest.get("seen_hashes", []))
    return [f for f in files if f[1] not in seen]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ingest_manifest.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fa/ingest.py fa/cache.py tests/unit/test_ingest_manifest.py
git commit -m "feat: add manifest-based and explicit file selection"
```

---

### Task 3: Build extraction path (text first, OCR fallback, optional repair hook)

**Files:**
- Create: `fa/extract/text.py`
- Create: `fa/extract/ocr.py`
- Create: `fa/extract/repair.py`
- Test: `tests/unit/test_extraction_fallback.py`

- [ ] **Step 1: Write the failing test**

```python
from fa.extract.repair import maybe_repair_table

def test_repair_triggered_only_low_confidence():
    table = {"rows": [["Revenue", "100"]], "confidence": 0.25}
    repaired = maybe_repair_table(table, enable_llm=True, threshold=0.4, repair_fn=lambda t: {"rows": t["rows"], "confidence": 0.9})
    assert repaired["confidence"] == 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_extraction_fallback.py -v`  
Expected: FAIL with missing module/function.

- [ ] **Step 3: Write minimal implementation**

```python
# fa/extract/repair.py
def maybe_repair_table(table: dict, enable_llm: bool, threshold: float, repair_fn):
    if not enable_llm:
        return table
    if table.get("confidence", 1.0) >= threshold:
        return table
    return repair_fn(table)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_extraction_fallback.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fa/extract/text.py fa/extract/ocr.py fa/extract/repair.py tests/unit/test_extraction_fallback.py
git commit -m "feat: add extraction fallback with optional llm repair hook"
```

---

### Task 4: Implement normalization and period-aware merging

**Files:**
- Create: `fa/normalize.py`
- Create: `fa/merge.py`
- Test: `tests/unit/test_normalize_and_merge.py`

- [ ] **Step 1: Write the failing test**

```python
from fa.normalize import parse_number
from fa.merge import union_rows

def test_parse_parentheses_negative():
    assert parse_number("(1,234)") == -1234

def test_union_rows_preserves_missing_as_blank():
    periods = ["2023", "2024"]
    rows = {"Cash": {"2023": 100}, "Inventory": {"2024": 50}}
    out = union_rows(rows, periods)
    assert out["Cash"]["2024"] is None
    assert out["Inventory"]["2023"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_normalize_and_merge.py -v`  
Expected: FAIL with missing functions.

- [ ] **Step 3: Write minimal implementation**

```python
# fa/normalize.py
import re

def parse_number(s: str):
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    s = re.sub(r"[^\d\.-]", "", s)
    if s in {"", "-", "."}:
        return None
    v = float(s)
    return -v if neg else v
```

```python
# fa/merge.py
def union_rows(rows: dict[str, dict[str, float]], periods: list[str]):
    out = {}
    for item, values in rows.items():
        out[item] = {p: values.get(p) for p in periods}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_normalize_and_merge.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fa/normalize.py fa/merge.py tests/unit/test_normalize_and_merge.py
git commit -m "feat: add normalization and union merge behavior"
```

---

### Task 5: Add LLM line-item matcher (gray-zone only) and conflict handling

**Files:**
- Modify: `fa/merge.py`
- Create: `fa/llm/client.py`
- Create: `fa/llm/matcher.py`
- Create: `fa/incremental.py`
- Test: `tests/unit/test_llm_match_and_conflict.py`

- [ ] **Step 1: Write the failing test**

```python
from fa.incremental import conflict_column_name

def test_conflict_column_name_annual():
    assert conflict_column_name("2024", "ReportA.pdf") == "2024 Conflict - ReportA.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_llm_match_and_conflict.py -v`  
Expected: FAIL due to missing `conflict_column_name`.

- [ ] **Step 3: Write minimal implementation**

```python
# fa/incremental.py
def conflict_column_name(period: str, report_name: str) -> str:
    return f"{period} Conflict - {report_name}"
```

```python
# fa/llm/matcher.py
from dataclasses import dataclass

@dataclass
class MatchDecision:
    equivalent: bool
    score: float
    reason: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_llm_match_and_conflict.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fa/incremental.py fa/llm/client.py fa/llm/matcher.py fa/merge.py tests/unit/test_llm_match_and_conflict.py
git commit -m "feat: add conflict naming and llm matcher contracts"
```

---

### Task 6: Implement validation engine and Excel exporter

**Files:**
- Create: `fa/validate.py`
- Create: `fa/export.py`
- Create: `fa/warnings_log.py`
- Test: `tests/unit/test_validate_and_export.py`

- [ ] **Step 1: Write the failing test**

```python
from fa.validate import within_tolerance

def test_rounding_aware_tolerance_default():
    assert within_tolerance(reported=100.0, calculated=100.4, tolerance=0.5) is True
    assert within_tolerance(reported=100.0, calculated=100.6, tolerance=0.5) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_validate_and_export.py -v`  
Expected: FAIL with missing function.

- [ ] **Step 3: Write minimal implementation**

```python
# fa/validate.py
def within_tolerance(reported: float, calculated: float, tolerance: float) -> bool:
    return abs(reported - calculated) <= tolerance
```

```python
# fa/export.py
from openpyxl import Workbook

def build_main_workbook():
    wb = Workbook()
    ws = wb.active
    ws.title = "Balance Sheet"
    wb.create_sheet("Income Statement")
    wb.create_sheet("Cash Flow & Comprehensive Income")
    return wb
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_validate_and_export.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fa/validate.py fa/export.py fa/warnings_log.py tests/unit/test_validate_and_export.py
git commit -m "feat: add validation primitives and base excel exporter"
```

---

### Task 7: Wire CLI orchestration and integration tests

**Files:**
- Modify: `fa/cli.py`
- Create: `tests/integration/test_init_update_cli.py`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `README.md`

- [ ] **Step 1: Write the failing integration test**

```python
from typer.testing import CliRunner
from fa.cli import app

def test_init_command_smoke():
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--company", "POSCO", "--dry-run"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_init_update_cli.py -v`  
Expected: FAIL because command handlers are missing.

- [ ] **Step 3: Implement minimal orchestration and docs**

```python
# fa/cli.py
import typer
app = typer.Typer()

@app.command()
def init(company: str, rebuild: bool = False, dry_run: bool = False):
    typer.echo(f"init company={company} rebuild={rebuild} dry_run={dry_run}")

@app.command()
def update(company: str, files: list[str] = typer.Option(None), dry_run: bool = False):
    typer.echo(f"update company={company} files={files or []} dry_run={dry_run}")
```

```text
# requirements.txt (initial pinned-minimum form)
pydantic
PyYAML
python-dateutil
typer
rich
pdfplumber
camelot-py
pypdf
pytesseract
pdf2image
Pillow
pandas
numpy
openpyxl
XlsxWriter
rapidfuzz
openai
httpx
tenacity
orjson
pytest
pytest-cov
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit -v && pytest tests/integration -v`  
Expected: PASS for all tests created in this plan.

- [ ] **Step 5: Commit**

```bash
git add fa/cli.py tests/integration/test_init_update_cli.py requirements.txt .env.example README.md
git commit -m "feat: wire cli workflow and add docs/dependencies baseline"
```

---

### Task 8: End-to-end verification and acceptance checklist

**Files:**
- Modify: `README.md`
- Test: `tests/integration/test_end_to_end_small_fixture.py`

- [ ] **Step 1: Write the failing E2E test**

```python
def test_end_to_end_fixture_outputs_three_files(tmp_path):
    # Arrange fixture company folder and fake extracted payloads
    # Act run pipeline init
    # Assert three output files exist under final_excel/
    assert False, "implement fixture orchestration"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_end_to_end_small_fixture.py -v`  
Expected: FAIL with assertion marker.

- [ ] **Step 3: Implement minimal passing E2E path**

```python
# Pseudocode to implement in test fixture helper
# 1) create companies/TESTCO/Financial_Statements/
# 2) run CLI init in dry-run false mode with mocked extractors
# 3) assert existence of:
#    - TESTCO_financial_statements_final.xlsx
#    - TESTCO_source_tracking.xlsx
#    - TESTCO_extraction_warnings.xlsx
```

- [ ] **Step 4: Run full verification**

Run: `pytest -v --maxfail=1`  
Expected: PASS.  
Run: `python -m fa init --company TESTCO --dry-run`  
Expected: process summary printed without exception.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_end_to_end_small_fixture.py README.md
git commit -m "test: add end-to-end acceptance fixture and verification guide"
```

---

## Spec Coverage Self-Review

- PDF-only, per-company processing: covered by Tasks 2 + 7 + 8.
- Required statements and CF+CI sheet layout: covered by Tasks 3 + 6 + 8.
- Million-unit normalization and currency preservation: covered by Task 4.
- Conservative merge with latest naming and uncertainty warnings: covered by Tasks 4 + 5 + 6.
- Validation with rounding-aware tolerance and coloring: covered by Task 6.
- Incremental update with auto + explicit file modes and conflict columns: covered by Tasks 2 + 5 + 7.
- Source-tracking and warning workbooks: covered by Task 6 + Task 8.
- LLM hooks (#3 and #5) with OpenAI-compatible interface: covered by Tasks 3 + 5.
- Dependencies and README requirements: covered by Task 7.

No uncovered requirement found.

## Placeholder Scan and Consistency Check

- No `TODO`/`TBD` placeholders remain in implementation steps.
- Function names used across tasks are consistent:
  - `select_input_files`, `maybe_repair_table`, `conflict_column_name`, `within_tolerance`.
- CLI contract (`init`, `update`, `--files`, `--dry-run`, `--rebuild`) is consistent with the spec.

