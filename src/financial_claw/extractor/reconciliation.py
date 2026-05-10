from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from .models import ExtractionResult


TOLERANCE = Decimal("1")
FAILED_RECONCILIATION_CELLS_KEY = "_failed_reconciliation_cells"


def apply_reconciliation_checks(results: list[ExtractionResult]) -> list[ExtractionResult]:
    for result in results:
        checks = _checks_for_statement(result)
        result.warnings.extend(check.message for check in checks)
        failed_cells = sorted({cell for check in checks for cell in check.cells})
        if failed_cells:
            setattr(result, FAILED_RECONCILIATION_CELLS_KEY, failed_cells)
    return results


class ReconciliationIssue:
    def __init__(self, message: str, cells: list[tuple[int, int]]) -> None:
        self.message = message
        self.cells = cells


def _checks_for_statement(result: ExtractionResult) -> list[ReconciliationIssue]:
    if result.candidate.statement_type == "balance_sheet":
        return _balance_sheet_checks(result.rows)
    if result.candidate.statement_type == "income_statement":
        return _income_statement_checks(result.rows)
    if result.candidate.statement_type == "cash_flow":
        return _cash_flow_checks(result.rows)
    return []


def _balance_sheet_checks(rows: list[list[str]]) -> list[ReconciliationIssue]:
    warnings: list[ReconciliationIssue] = []
    total_assets = _find_row_values(rows, r"^total assets$")
    total_liabilities = _find_row_values(rows, r"^total liabilities$")
    total_equity = _find_row_values(rows, r"^total equity$")
    total_liabilities_and_equity = _find_row_values(rows, r"^total liabilities and equity$")
    current_assets = _find_row_values(rows, r"^total current assets$")
    non_current_assets = _find_row_values(rows, r"^total non-current assets$")
    current_liabilities = _find_row_values(rows, r"^total current liabilities$")
    non_current_liabilities = _find_row_values(rows, r"^total non-current liabilities$")

    warnings.extend(_compare_rows("total assets", total_assets, "total liabilities and equity", total_liabilities_and_equity))
    warnings.extend(_sum_rows("total assets", total_assets, [("total liabilities", total_liabilities), ("total equity", total_equity)]))
    warnings.extend(_sum_rows("total assets", total_assets, [("total current assets", current_assets), ("total non-current assets", non_current_assets)]))
    warnings.extend(_sum_rows("total liabilities", total_liabilities, [("total current liabilities", current_liabilities), ("total non-current liabilities", non_current_liabilities)]))
    return warnings


def _income_statement_checks(rows: list[list[str]]) -> list[ReconciliationIssue]:
    warnings: list[ReconciliationIssue] = []
    revenue = _find_row_values(rows, r"^(?:revenue|sales)$")
    cost_of_sales = _find_row_values(rows, r"^cost of sales$")
    gross_profit = _find_row_values(rows, r"^gross profit$")
    warnings.extend(_gross_profit_check(revenue, cost_of_sales, gross_profit))
    return warnings


def _cash_flow_checks(rows: list[list[str]]) -> list[ReconciliationIssue]:
    warnings: list[ReconciliationIssue] = []
    operating = _find_row_values(rows, r"^net cash (?:provided by|used in) operating activities$")
    investing = _find_row_values(rows, r"^net cash (?:provided by|used in) investing activities$")
    financing = _find_row_values(rows, r"^net cash (?:provided by|used in) financing activities$")
    fx_effect = _find_row_values(rows, r"^effect of exchange rate")
    net_change = _find_row_values(rows, r"^net (?:increase|decrease) in cash")
    opening_cash = _find_row_values(rows, r"^cash and cash equivalents at beginning")
    held_for_sale_change = _find_row_values(rows, r"^changes in cash classified as assets held for sale$")
    closing_cash = _find_row_values(rows, r"^cash and cash equivalents at end")

    warnings.extend(_cash_flow_section_checks(rows))
    warnings.extend(
        _sum_rows(
            "net increase/decrease in cash",
            net_change,
            [
                ("operating cash flow", operating),
                ("investing cash flow", investing),
                ("financing cash flow", financing),
            ]
            + ([("exchange-rate effect", fx_effect)] if fx_effect else []),
        )
    )
    warnings.extend(
        _sum_rows(
            "cash and cash equivalents at end",
            closing_cash,
            [
                ("opening cash", opening_cash),
                ("net increase/decrease in cash", net_change),
            ]
            + ([("held-for-sale cash change", held_for_sale_change)] if held_for_sale_change else []),
        )
    )
    return warnings


def _cash_flow_section_checks(rows: list[list[str]]) -> list[ReconciliationIssue]:
    warnings: list[ReconciliationIssue] = []
    warnings.extend(
        _cash_flow_section_sum_check(
            rows,
            section_pattern=r"^cash flows from operating activities$",
            subtotal_pattern=r"^net cash (?:provided by|used in) operating activities$",
            section_name="operating activities",
        )
    )
    warnings.extend(
        _cash_flow_section_sum_check(
            rows,
            section_pattern=r"^cash flows from investing activities$",
            subtotal_pattern=r"^net cash (?:provided by|used in) investing activities$",
            section_name="investing activities",
        )
    )
    warnings.extend(
        _cash_flow_section_sum_check(
            rows,
            section_pattern=r"^cash flows from financing activities$",
            subtotal_pattern=r"^net cash (?:provided by|used in) financing activities$",
            section_name="financing activities",
        )
    )
    return warnings


def _cash_flow_section_sum_check(
    rows: list[list[str]],
    *,
    section_pattern: str,
    subtotal_pattern: str,
    section_name: str,
) -> list[ReconciliationIssue]:
    section_idx = _find_label_row_idx(rows, section_pattern)
    subtotal_idx = _find_label_row_idx(rows, subtotal_pattern, start=(section_idx + 1 if section_idx is not None else 0))
    if section_idx is None or subtotal_idx is None or subtotal_idx <= section_idx:
        return []

    subtotal = _row_values(rows[subtotal_idx], subtotal_idx)
    addends = [
        (row_idx, values)
        for row_idx in range(section_idx + 1, subtotal_idx)
        if (values := _cash_flow_line_item_values(rows[row_idx], row_idx))
    ]
    if not addends:
        return []

    warnings: list[ReconciliationIssue] = []
    for col_idx in sorted(subtotal):
        present = [(values[col_idx][0], values[col_idx][1]) for _, values in addends if col_idx in values]
        if not present:
            continue
        subtotal_value, subtotal_cell = subtotal[col_idx]
        calculated = sum((value for value, _ in present), Decimal("0"))
        if _within_tolerance(subtotal_value, calculated):
            continue
        cells = [subtotal_cell] + [cell for _, cell in present]
        warnings.append(
            _issue(
                f"net cash from {section_name}",
                subtotal_value,
                f"sum of {section_name} line items",
                calculated,
                col_idx,
                cells,
            )
        )
    return warnings


def _find_row_values(rows: list[list[str]], label_pattern: str) -> dict[int, tuple[Decimal, tuple[int, int]]]:
    pattern = re.compile(label_pattern, re.I)
    for row_idx, row in enumerate(rows):
        if not row:
            continue
        label = _normalize_label(str(row[0]))
        if pattern.search(label):
            return {
                idx: (value, (row_idx, idx))
                for idx, cell in enumerate(row[1:], start=1)
                if (value := _parse_number(cell)) is not None
            }
    return {}


def _find_label_row_idx(rows: list[list[str]], label_pattern: str, *, start: int = 0) -> int | None:
    pattern = re.compile(label_pattern, re.I)
    for row_idx in range(start, len(rows)):
        row = rows[row_idx]
        if not row:
            continue
        if pattern.search(_normalize_label(str(row[0]))):
            return row_idx
    return None


def _row_values(row: list[str], row_idx: int) -> dict[int, tuple[Decimal, tuple[int, int]]]:
    return {
        col_idx: (value, (row_idx, col_idx))
        for col_idx, cell in enumerate(row[1:], start=1)
        if (value := _parse_number(cell)) is not None
    }


def _cash_flow_line_item_values(row: list[str], row_idx: int) -> dict[int, tuple[Decimal, tuple[int, int]]]:
    if not row:
        return {}
    label = _normalize_label(str(row[0]))
    if not label:
        return {}
    if label == "continue":
        return {}
    if label.startswith("cash flows from "):
        return {}
    if label.startswith("net cash "):
        return {}
    if label.startswith("cash and cash equivalents "):
        return {}
    if label.startswith("net increase") or label.startswith("net decrease"):
        return {}
    return _row_values(row, row_idx)


def _compare_rows(
    left_name: str,
    left: dict[int, tuple[Decimal, tuple[int, int]]],
    right_name: str,
    right: dict[int, tuple[Decimal, tuple[int, int]]],
) -> list[ReconciliationIssue]:
    warnings: list[ReconciliationIssue] = []
    for col_idx in sorted(set(left) & set(right)):
        left_value, left_cell = left[col_idx]
        right_value, right_cell = right[col_idx]
        if _within_tolerance(left_value, right_value):
            continue
        warnings.append(_issue(left_name, left_value, right_name, right_value, col_idx, [left_cell, right_cell]))
    return warnings


def _sum_rows(
    target_name: str,
    target: dict[int, tuple[Decimal, tuple[int, int]]],
    addends: list[tuple[str, dict[int, tuple[Decimal, tuple[int, int]]]]],
    *,
    allow_missing_addends: bool = False,
) -> list[ReconciliationIssue]:
    warnings: list[ReconciliationIssue] = []
    for col_idx in sorted(target):
        present = [(name, values[col_idx]) for name, values in addends if col_idx in values]
        if not present:
            continue
        if not allow_missing_addends and len(present) != len(addends):
            continue
        target_value, target_cell = target[col_idx]
        calculated = sum((value for _, (value, _) in present), Decimal("0"))
        if _within_tolerance(target_value, calculated):
            continue
        formula_name = " + ".join(name for name, _ in present)
        cells = [target_cell] + [cell for _, (_, cell) in present]
        warnings.append(_issue(target_name, target_value, formula_name, calculated, col_idx, cells))
    return warnings


def _gross_profit_check(
    revenue: dict[int, tuple[Decimal, tuple[int, int]]],
    cost_of_sales: dict[int, tuple[Decimal, tuple[int, int]]],
    gross_profit: dict[int, tuple[Decimal, tuple[int, int]]],
) -> list[ReconciliationIssue]:
    warnings: list[ReconciliationIssue] = []
    for col_idx in sorted(set(revenue) & set(cost_of_sales) & set(gross_profit)):
        revenue_value, revenue_cell = revenue[col_idx]
        cost, cost_cell = cost_of_sales[col_idx]
        gross_profit_value, gross_profit_cell = gross_profit[col_idx]
        calculated = revenue_value + cost if cost < 0 else revenue_value - cost
        if _within_tolerance(gross_profit_value, calculated):
            continue
        warnings.append(
            _issue(
                "gross profit",
                gross_profit_value,
                "revenue less cost of sales",
                calculated,
                col_idx,
                [gross_profit_cell, revenue_cell, cost_cell],
            )
        )
    return warnings


def _parse_number(value: object) -> Decimal | None:
    text = str(value or "").strip()
    if not text or text in {"-", "鈥?"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.strip("()").replace(",", "").replace("$", "").replace("₩", "").replace("W", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        return None
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -number if negative else number


def _normalize_label(label: str) -> str:
    normalized = re.sub(r"\s+", " ", label.strip().lower())
    normalized = normalized.replace("–", "-").replace("—", "-")
    return normalized


def _within_tolerance(reported: Decimal, calculated: Decimal) -> bool:
    return abs(reported - calculated) <= TOLERANCE


def _issue(
    left_name: str,
    left: Decimal,
    right_name: str,
    right: Decimal,
    col_idx: int,
    cells: list[tuple[int, int]],
) -> ReconciliationIssue:
    message = (
        "Reconciliation check failed: "
        f"{left_name} != {right_name} at column {col_idx + 1} "
        f"({left} vs {right}; difference={left - right})."
    )
    return ReconciliationIssue(message, cells)
