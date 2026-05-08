from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from loguru import logger
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


EXPECTED_SHEETS = ["Balance Sheet", "Income Statement", "Cash Flow Statement"]

# Excel presentation (xlsx / financial table conventions)
_FONT_FAMILY = "Arial"
_FONT_SIZE = 10
_HEADER_FILL = "1F4E78"
_HEADER_FONT_COLOR = "FFFFFF"
_ANNUAL_FILL = "D9EAF7"
_QUARTER_FILL = "E2F0D9"
_SECTION_FILL = "F2F2F2"
_TOTAL_FILL = "EAF2F8"
_BORDER_COLOR = "D9E2F3"
_STRONG_BORDER_COLOR = "7F7F7F"
_NUM_FORMAT_INT = '#,##0;(#,##0);"-"'
_NUM_FORMAT_FLOAT = '#,##0.0;(#,##0.0);"-"'


@dataclass(frozen=True)
class Period:
    label: str
    kind: Literal["annual", "quarter"]
    year: int
    quarter: int = 0

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.year, self.quarter)


@dataclass
class ParsedSheet:
    title: str
    periods: dict[int, Period]
    rows: list["StatementRow"]


@dataclass
class StatementRow:
    label: str
    key: str
    values: dict[str, object] = field(default_factory=dict)


def merge_workbooks(excel_1: Path, excel_2: Path, output_path: Path) -> Path:
    wb1 = load_workbook(excel_1, data_only=True)
    wb2 = load_workbook(excel_2, data_only=True)
    _validate_workbook(wb1, excel_1)
    _validate_workbook(wb2, excel_2)

    out_wb = Workbook()
    out_wb.remove(out_wb.active)

    for sheet_name in EXPECTED_SHEETS:
        logger.info("Merging sheet: {}", sheet_name)
        left = parse_statement_sheet(wb1[sheet_name])
        right = parse_statement_sheet(wb2[sheet_name])
        merged_rows = merge_statement_rows(left.rows, right.rows)
        periods = _merge_periods(left, right)
        write_merged_sheet(out_wb, sheet_name, merged_rows, periods)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_wb.save(output_path)
    logger.info("Merged workbook saved: {}", output_path)
    return output_path


def _validate_workbook(wb, path: Path) -> None:
    names = wb.sheetnames
    if names != EXPECTED_SHEETS:
        raise ValueError(f"{path} must contain exactly these sheets in order: {EXPECTED_SHEETS}; got {names}")


def parse_statement_sheet(ws) -> ParsedSheet:
    header_row, periods = _find_period_header(ws)
    title = str(ws.cell(row=1, column=1).value or ws.title)
    rows: list[StatementRow] = []
    seen: dict[str, int] = {}

    for row_idx in range(header_row + 1, ws.max_row + 1):
        label = _row_label(ws, row_idx, periods)
        if not label:
            continue
        key_base = normalize_item_label(label)
        if not key_base:
            continue
        seen[key_base] = seen.get(key_base, 0) + 1
        key = f"{key_base}#{seen[key_base]}"
        values = {
            period.label: ws.cell(row=row_idx, column=col_idx).value
            for col_idx, period in periods.items()
        }
        rows.append(StatementRow(label=label, key=key, values=values))
    return ParsedSheet(title=title, periods=periods, rows=rows)


def _find_period_header(ws) -> tuple[int, dict[int, Period]]:
    best_row = 0
    best_periods: dict[int, Period] = {}
    for row_idx in range(1, min(ws.max_row, 12) + 1):
        periods: dict[int, Period] = {}
        for col_idx in range(1, ws.max_column + 1):
            period = parse_period(ws.cell(row=row_idx, column=col_idx).value)
            if period is not None:
                periods[col_idx] = period
        if len(periods) > len(best_periods):
            best_row = row_idx
            best_periods = periods
    if not best_periods:
        raise ValueError(f"Could not find period header row in sheet {ws.title!r}")
    return best_row, best_periods


def parse_period(value: object) -> Period | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))

    quarter_match = re.search(r"\bQ([1-4])\s*(20\d{2})\b", normalized, re.I)
    if not quarter_match:
        quarter_match = re.search(r"\b(20\d{2})\s*Q([1-4])\b", normalized, re.I)
        if quarter_match:
            year = int(quarter_match.group(1))
            quarter = int(quarter_match.group(2))
            return Period(label=f"Q{quarter} {year}", kind="quarter", year=year, quarter=quarter)
    else:
        quarter = int(quarter_match.group(1))
        year = int(quarter_match.group(2))
        return Period(label=f"Q{quarter} {year}", kind="quarter", year=year, quarter=quarter)

    fy_quarter_match = re.search(r"\bFY(\d{2})\s*([1-4])Q\b", normalized, re.I)
    if fy_quarter_match:
        year = 2000 + int(fy_quarter_match.group(1))
        quarter = int(fy_quarter_match.group(2))
        return Period(label=f"Q{quarter} {year}", kind="quarter", year=year, quarter=quarter)

    year_match = re.search(r"\b(20\d{2})\b", normalized)
    if year_match:
        year = int(year_match.group(1))
        return Period(label=str(year), kind="annual", year=year)
    return None


def _row_label(ws, row_idx: int, periods: dict[int, Period]) -> str:
    period_cols = set(periods)
    label_parts: list[str] = []
    first_period_col = min(period_cols)
    for col_idx in range(1, first_period_col):
        value = ws.cell(row=row_idx, column=col_idx).value
        if value is None:
            continue
        text = str(value).strip()
        if not text or _is_note_cell(text):
            continue
        label_parts.append(text)
    return " ".join(label_parts).strip()


def _is_note_cell(text: str) -> bool:
    normalized = text.strip()
    return bool(re.fullmatch(r"\d+(?:\s*,\s*\d+)*(?:\s*\([a-z]\))?", normalized, re.I))


def normalize_item_label(label: str) -> str:
    text = label.lower()
    text = text.replace("&", "and")
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(total|net)\b", r" \1 ", text)
    return re.sub(r"\s+", " ", text).strip()


def merge_statement_rows(rows_1: list[StatementRow], rows_2: list[StatementRow]) -> list[StatementRow]:
    merged: list[StatementRow] = []
    used_right: set[int] = set()
    right_keys = {row.key: idx for idx, row in enumerate(rows_2)}

    for left in rows_1:
        right_idx = right_keys.get(left.key)
        if right_idx is None:
            right_idx = _find_conservative_match(left, rows_2, used_right)
        if right_idx is None:
            merged.append(StatementRow(label=left.label, key=left.key, values=dict(left.values)))
            continue

        right = rows_2[right_idx]
        used_right.add(right_idx)
        values = dict(left.values)
        values.update(right.values)
        merged.append(StatementRow(label=right.label, key=left.key, values=values))

    for idx, right in enumerate(rows_2):
        if idx in used_right:
            continue
        merged.append(StatementRow(label=right.label, key=right.key, values=dict(right.values)))
    return merged


def _find_conservative_match(
    left: StatementRow,
    rows_2: list[StatementRow],
    used_right: set[int],
) -> int | None:
    best_idx: int | None = None
    best_score = 0.0
    left_base = left.key.rsplit("#", 1)[0]
    for idx, right in enumerate(rows_2):
        if idx in used_right:
            continue
        right_base = right.key.rsplit("#", 1)[0]
        score = SequenceMatcher(None, left_base, right_base).ratio()
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx if best_score >= 0.96 else None


def _merge_periods(left: ParsedSheet, right: ParsedSheet) -> list[Period]:
    by_label: dict[str, Period] = {}
    for parsed in (left, right):
        for period in parsed.periods.values():
            by_label[period.label] = period
    annual = sorted((p for p in by_label.values() if p.kind == "annual"), key=lambda p: p.sort_key)
    quarter = sorted((p for p in by_label.values() if p.kind == "quarter"), key=lambda p: p.sort_key)
    return annual + quarter


def write_merged_sheet(wb: Workbook, sheet_name: str, rows: list[StatementRow], periods: list[Period]) -> None:
    ws = wb.create_sheet(sheet_name)
    annual = [p for p in periods if p.kind == "annual"]
    quarter = [p for p in periods if p.kind == "quarter"]

    headers = ["Item"] + [p.label for p in annual]
    blank_col = None
    if quarter:
        blank_col = len(headers) + 1
        headers.append("")
        headers.extend(p.label for p in quarter)
    ws.append(headers)

    ordered_periods = annual + quarter
    for row in rows:
        values = [row.label]
        values.extend(row.values.get(p.label, "") for p in annual)
        if quarter:
            values.append("")
            values.extend(row.values.get(p.label, "") for p in quarter)
        ws.append(values)

    _style_sheet(ws, blank_col)


def _is_numeric_cell_value(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float, Decimal))


def _number_format_for_value(value: int | float | Decimal) -> str:
    if isinstance(value, float) and not value.is_integer():
        return _NUM_FORMAT_FLOAT
    if isinstance(value, Decimal) and (value % 1) != 0:
        return _NUM_FORMAT_FLOAT
    return _NUM_FORMAT_INT


def _style_sheet(ws, blank_col: int | None) -> None:
    thin = Side(style="thin", color=_BORDER_COLOR)
    strong = Side(style="thin", color=_STRONG_BORDER_COLOR)
    grid_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    table_right_border = Border(left=thin, right=strong, top=thin, bottom=thin)
    total_border = Border(left=thin, right=thin, top=strong, bottom=thin)
    total_right_border = Border(left=thin, right=strong, top=strong, bottom=thin)
    header_right_border = Border(left=thin, right=strong, top=thin, bottom=thin)
    header_font = Font(name=_FONT_FAMILY, size=_FONT_SIZE, bold=True, color=_HEADER_FONT_COLOR)
    header_fill = PatternFill(fill_type="solid", fgColor=_HEADER_FILL)
    body_font = Font(name=_FONT_FAMILY, size=_FONT_SIZE, color="000000")
    body_numeric_font = Font(name=_FONT_FAMILY, size=_FONT_SIZE, color="000000")
    section_font = Font(name=_FONT_FAMILY, size=_FONT_SIZE, bold=True, color="000000")
    total_font = Font(name=_FONT_FAMILY, size=_FONT_SIZE, bold=True, color="000000")
    total_numeric_font = Font(name=_FONT_FAMILY, size=_FONT_SIZE, bold=True, color="000000")
    section_fill = PatternFill(fill_type="solid", fgColor=_SECTION_FILL)
    total_fill = PatternFill(fill_type="solid", fgColor=_TOTAL_FILL)
    annual_fill = PatternFill(fill_type="solid", fgColor=_ANNUAL_FILL)
    quarter_fill = PatternFill(fill_type="solid", fgColor=_QUARTER_FILL)

    for col_idx, cell in enumerate(ws[1], start=1):
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = header_right_border if col_idx == ws.max_column else grid_border
        if col_idx != 1 and (not blank_col or col_idx != blank_col):
            cell.fill = quarter_fill if blank_col and col_idx > blank_col else annual_fill
            cell.font = Font(name=_FONT_FAMILY, size=_FONT_SIZE, bold=True, color="000000")
        if blank_col and col_idx == blank_col:
            cell.fill = PatternFill(fill_type=None)
            cell.border = Border()

    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 22

    max_row = ws.max_row
    max_col = ws.max_column
    for row_idx in range(2, max_row + 1):
        row_label = str(ws.cell(row=row_idx, column=1).value or "").strip()
        is_section = _is_section_row(ws, row_idx, blank_col)
        is_total = _is_total_row_label(row_label)
        for col_idx in range(1, max_col + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = table_right_border if col_idx == max_col else grid_border
            val = cell.value
            if is_section:
                cell.fill = section_fill
                cell.font = section_font
                cell.alignment = Alignment(horizontal="left" if col_idx == 1 else "right", vertical="top", wrap_text=True)
                continue
            if is_total:
                cell.fill = total_fill
                cell.border = total_right_border if col_idx == max_col else total_border
            if col_idx == 1:
                cell.font = total_font if is_total else body_font
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                continue
            if blank_col and col_idx == blank_col:
                cell.font = body_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.fill = PatternFill(fill_type=None)
                cell.border = Border()
                continue
            if _is_numeric_cell_value(val):
                cell.font = total_numeric_font if is_total else body_numeric_font
                cell.number_format = _number_format_for_value(val)
                cell.alignment = Alignment(horizontal="right", vertical="top")
            else:
                cell.font = total_font if is_total else body_font
                cell.alignment = Alignment(horizontal="right", vertical="top")

    if blank_col:
        ws.column_dimensions[ws.cell(row=1, column=blank_col).column_letter].width = 4
    for col_idx in range(1, ws.max_column + 1):
        if blank_col and col_idx == blank_col:
            continue
        max_len = 0
        for row_idx in range(1, ws.max_row + 1):
            value = ws.cell(row=row_idx, column=col_idx).value
            if value is None:
                continue
            parts = str(value).splitlines() or [""]
            max_len = max(max_len, max(len(part) for part in parts))
        letter = ws.cell(row=1, column=col_idx).column_letter
        if col_idx == 1:
            ws.column_dimensions[letter].width = max(36, min(70, max_len + 2))
        else:
            ws.column_dimensions[letter].width = max(14, min(18, max_len + 2))


def _is_section_row(ws, row_idx: int, blank_col: int | None) -> bool:
    values = [
        ws.cell(row=row_idx, column=col_idx).value
        for col_idx in range(2, ws.max_column + 1)
        if not blank_col or col_idx != blank_col
    ]
    return bool(ws.cell(row=row_idx, column=1).value) and all(value in (None, "") for value in values)


def _is_total_row_label(label: str) -> bool:
    normalized = label.strip().lower()
    if not normalized:
        return False
    return normalized.startswith(
        (
            "total ",
            "net ",
            "gross profit",
            "operating profit",
            "profit for",
            "profit before",
            "cash and cash equivalents at end",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge one extracted financial statement workbook into another.")
    parser.add_argument("excel_1", help="Base workbook.")
    parser.add_argument("excel_2", help="Workbook to merge into the base workbook.")
    parser.add_argument("-o", "--output", required=True, help="Merged output workbook path.")
    args = parser.parse_args()

    merge_workbooks(Path(args.excel_1), Path(args.excel_2), Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
