from __future__ import annotations

from pathlib import Path
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .cleaning_config import CELL_TEXT_REPLACEMENTS
from .models import ExtractionResult, PageProfile, StatementCandidate

DEFAULT_FONT = Font(name="Arial", size=10, color="000000")
HEADER_FONT = Font(name="Arial", size=10, bold=True, color="000000")
HEADER_FILL = PatternFill(fill_type="solid", fgColor="D9E1F2")
YELLOW_ASSUMPTION_FILL = PatternFill(fill_type="solid", fgColor="FFF200")
INTEGER_FORMAT = '#,##0;(#,##0);"-"'
DECIMAL_FORMAT = '#,##0.00;(#,##0.00);"-"'
SCORE_FORMAT = '0.0000;(-0.0000);"-"'

NUMBER_TOKEN_RE = re.compile(r"^\(?-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\)?$|^-$")


def write_workbook(
    output_path: Path,
    metadata: dict[str, str],
    profiles: list[PageProfile],
    candidates: list[StatementCandidate],
    results: list[ExtractionResult],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    records: list[dict[str, str]] = []

    used_names: set[str] = set()
    type_counts = _statement_type_counts(results)
    type_seen: dict[str, int] = {}
    for idx, result in enumerate(results, start=1):
        statement_type = result.candidate.statement_type
        type_seen[statement_type] = type_seen.get(statement_type, 0) + 1
        name = _sheet_name(result.candidate, type_seen[statement_type], type_counts[statement_type], used_names)
        used_names.add(name)
        out_ws = wb.create_sheet(name)
        note_columns = _note_columns(result.rows)
        for row in result.rows:
            out_ws.append(
                [
                    _coerce_excel_cell_value(cell, force_text=(col_idx in note_columns))
                    for col_idx, cell in enumerate(row)
                ]
            )
        _style_statement_sheet(out_ws)
        records.append(_record_row(output_path, metadata, result, name))
    if not wb.sheetnames:
        no_statement_ws = wb.create_sheet("NoStatements")
        no_statement_ws["A1"] = "No statements extracted."
        _style_statement_sheet(no_statement_ws)
    wb.save(output_path)
    write_extraction_record(output_path.with_name(f"{output_path.stem}_extraction_record.xlsx"), records)


def write_extraction_record(output_path: Path, records: list[dict[str, str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "extraction_record"
    headers = [
        "output_workbook",
        "sheet_name",
        "statement_type",
        "source_pdf",
        "source_pages",
        "page_start",
        "page_end",
        "extraction_method",
        "title",
        "score",
        "warnings",
    ]
    ws.append(headers)
    for record in records:
        ws.append([_coerce_excel_cell_value(record.get(header, "")) for header in headers])
    _style_record_sheet(ws)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def _record_row(
    output_workbook: Path,
    metadata: dict[str, str],
    result: ExtractionResult,
    sheet_name: str,
) -> dict[str, str]:
    candidate = result.candidate
    return {
        "output_workbook": str(output_workbook),
        "sheet_name": sheet_name,
        "statement_type": candidate.statement_type,
        "source_pdf": metadata.get("source_pdf", ""),
        "source_pages": ", ".join(str(page) for page in candidate.source_pages),
        "page_start": str(candidate.page_start),
        "page_end": str(candidate.page_end),
        "extraction_method": candidate.extraction_method,
        "title": candidate.title,
        "score": str(candidate.score),
        "warnings": "; ".join(result.warnings),
    }


def _statement_type_counts(results: list[ExtractionResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        statement_type = result.candidate.statement_type
        counts[statement_type] = counts.get(statement_type, 0) + 1
    return counts


def _sheet_name(candidate: StatementCandidate, sequence: int, total_for_type: int, used_names: set[str]) -> str:
    base = {
        "balance_sheet": "Balance Sheet",
        "income_statement": "Income Statement",
        "cash_flow": "Cash Flow Statement",
    }.get(candidate.statement_type, candidate.statement_type)
    title = f"{base} {sequence:02d}" if total_for_type > 1 else base
    title = re.sub(r"[\[\]:*?/\\]", "_", title)[:31]
    while title in used_names:
        sequence += 1
        suffix = f" {sequence:02d}"
        title = f"{base[:31-len(suffix)]}{suffix}"
    return title


def _note_columns(rows: list[list[str]]) -> set[int]:
    note_columns: set[int] = set()
    for row in rows[:8]:
        for idx, cell in enumerate(row):
            if isinstance(cell, str) and cell.strip().lower() in {"note", "notes"}:
                note_columns.add(idx)
    return note_columns


def _coerce_excel_cell_value(value: object, force_text: bool = False) -> object:
    if value is None:
        return ""
    if not isinstance(value, str):
        return value

    raw_text = value.strip()
    if re.fullmatch(r"[¥￦]\s*\d{1,2}", raw_text):
        return raw_text

    text = _apply_cell_text_replacements(value).strip()
    if not text:
        return ""
    if force_text:
        return text
    if re.fullmatch(r"\d{4}", text):
        return text
    normalized_number = _normalize_number_text(text)
    if not NUMBER_TOKEN_RE.match(normalized_number):
        return text
    if text in {"-", "–"}:
        return text

    negative = normalized_number.startswith("(") and normalized_number.endswith(")")
    cleaned = normalized_number.strip("()").replace(",", "")
    try:
        number = float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        return text
    return -number if negative else number


def _apply_cell_text_replacements(text: str) -> str:
    for old, new in CELL_TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def _normalize_number_text(text: str) -> str:
    cleaned = text.replace("$", "").strip()
    if cleaned.startswith("W "):
        cleaned = cleaned[2:].strip()
    if cleaned.endswith(" W"):
        cleaned = cleaned[:-2].strip()
    return cleaned


def _style_statement_sheet(ws) -> None:
    if ws.max_row == 0 or ws.max_column == 0:
        return
    ws.freeze_panes = "A2"
    _apply_base_style(ws)
    _format_numeric_cells(ws)
    _autofit_columns(ws)


def _style_record_sheet(ws) -> None:
    if ws.max_row == 0:
        return
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    _apply_base_style(ws)
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    _highlight_attention_columns(ws)
    _format_numeric_cells(ws)
    _autofit_columns(ws)


def _apply_base_style(ws) -> None:
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            cell.font = DEFAULT_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _highlight_attention_columns(ws) -> None:
    headers = [str(cell.value or "") for cell in ws[1]]
    for key in ("warnings",):
        if key not in headers:
            continue
        col = headers.index(key) + 1
        ws.cell(row=1, column=col).fill = YELLOW_ASSUMPTION_FILL


def _format_numeric_cells(ws) -> None:
    score_col = _find_column_by_header(ws, "score")
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            if isinstance(cell.value, int):
                cell.number_format = INTEGER_FORMAT
                cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
            elif isinstance(cell.value, float):
                cell.number_format = SCORE_FORMAT if cell.column == score_col else DECIMAL_FORMAT
                cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)


def _find_column_by_header(ws, header_name: str) -> int | None:
    if ws.max_row < 1:
        return None
    for idx, cell in enumerate(ws[1], start=1):
        if str(cell.value or "").strip().lower() == header_name:
            return idx
    return None


def _autofit_columns(ws) -> None:
    for col_idx in range(1, ws.max_column + 1):
        max_len = 0
        for row_idx in range(1, ws.max_row + 1):
            value = ws.cell(row=row_idx, column=col_idx).value
            if value is None:
                continue
            lines = str(value).splitlines() or [""]
            length = max(len(part) for part in lines)
            if length > max_len:
                max_len = length
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max(10, min(60, max_len + 2))
