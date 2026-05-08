from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from loguru import logger

from financial_claw.llm.minimax.table_schema import CellStyle, TableCell, TableDocument, TableSheet


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _strip_code_fences(text: str) -> str:
    m = _FENCED_JSON_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_first_json_object(text: str) -> str | None:
    s = _strip_code_fences(text)
    # Try direct parse first
    try:
        json.loads(s)
        return s
    except Exception:
        pass

    # Heuristic: first {...} block
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start : i + 1].strip()
                try:
                    json.loads(candidate)
                    return candidate
                except Exception:
                    return None
    return None


def _parse_markdown_table(md: str) -> TableDocument | None:
    lines = [ln.rstrip() for ln in md.splitlines() if ln.strip()]
    # Find first table block
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("|") and ln.strip().endswith("|"):
            start = i
            break
    if start is None:
        return None

    table_lines = []
    for ln in lines[start:]:
        s = ln.strip()
        if s.startswith("|") and s.endswith("|"):
            table_lines.append(s)
        else:
            break

    if len(table_lines) < 2:
        return None

    def split_row(row: str) -> list[str]:
        inner = row.strip()[1:-1]
        return [c.strip() for c in inner.split("|")]

    rows: list[list[str]] = []
    for idx, row in enumerate(table_lines):
        cols = split_row(row)
        # Skip alignment row like | --- | --- |
        if idx == 1 and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cols):
            continue
        rows.append(cols)

    if not rows:
        return None

    cells: list[TableCell] = []
    for r_i, row in enumerate(rows, start=1):
        for c_i, v in enumerate(row, start=1):
            cells.append(TableCell(r=r_i, c=c_i, v=v))
    return TableDocument(sheets=[TableSheet(name="Sheet1", cells=cells)], meta={"source": "markdown"})


def parse_table_document_from_model_text(text: str) -> TableDocument:
    json_str = _extract_first_json_object(text)
    if json_str:
        raw = json.loads(json_str)
        return _table_document_from_json(raw)

    md_doc = _parse_markdown_table(text)
    if md_doc:
        return md_doc

    logger.warning("No JSON/Markdown table found; saving raw text into A1.")
    return TableDocument(
        sheets=[TableSheet(name="Sheet1", cells=[TableCell(r=1, c=1, v=text.strip()[:32000])])],
        meta={"source": "raw_text"},
    )


def _cellstyle_from_json(d: dict[str, Any] | None) -> CellStyle:
    if not isinstance(d, dict):
        return CellStyle()
    return CellStyle(
        bold=d.get("bold"),
        italic=d.get("italic"),
        align=d.get("align"),
        valign=d.get("valign"),
        number_format=d.get("number_format"),
        bg_color=d.get("bg_color"),
        font_color=d.get("font_color"),
    )


def _table_document_from_json(raw: Any) -> TableDocument:
    if not isinstance(raw, dict):
        raise ValueError("Expected top-level object JSON for table document.")

    sheets_raw = raw.get("sheets")
    if not isinstance(sheets_raw, list):
        raise ValueError("JSON missing 'sheets' list.")

    sheets: list[TableSheet] = []
    for sh in sheets_raw:
        if not isinstance(sh, dict):
            continue
        name = str(sh.get("name") or "Sheet1")
        cells_list = sh.get("cells") or []
        cells: list[TableCell] = []
        if isinstance(cells_list, list):
            for c in cells_list:
                if not isinstance(c, dict):
                    continue
                r = int(c.get("r"))
                col = int(c.get("c"))
                v = c.get("v", None)
                rowspan = int(c.get("rowspan", 1) or 1)
                colspan = int(c.get("colspan", 1) or 1)
                style = _cellstyle_from_json(c.get("style"))
                cells.append(TableCell(r=r, c=col, v=v, rowspan=rowspan, colspan=colspan, style=style))

        sheet = TableSheet(
            name=name,
            cells=cells,
            column_widths=sh.get("column_widths"),
            row_heights=sh.get("row_heights"),
        )
        sheets.append(sheet)

    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else None
    doc = TableDocument(sheets=sheets, meta=meta or {"source": "json"})

    # Small normalization: ensure at least one sheet/cell
    if not doc.sheets:
        notes = ""
        if doc.meta and isinstance(doc.meta.get("notes"), str):
            notes = doc.meta["notes"].strip()
        fallback = notes or "(empty sheets)"
        doc = replace(doc, sheets=[TableSheet(name="Sheet1", cells=[TableCell(r=1, c=1, v=fallback)])])
    return doc
