from __future__ import annotations

from decimal import Decimal

from financial_claw.extractor.excel_writer import (
    _coerce_excel_cell_value,
    _is_non_monetary_row,
    _million_scale_for_rows,
    _normalize_unit_text_to_millions,
)


def test_detects_existing_million_unit() -> None:
    rows = [["(in millions of Won)", "Notes", "2024"], ["Revenue", "", "1,234"]]

    assert _million_scale_for_rows(rows) == Decimal("1")


def test_explicit_million_column_unit_overrides_broad_currency_phrase() -> None:
    rows = [
        ["(expressed in Australian dollars)", "Note", "2025\n$M", "2024\n$M"],
        ["Cash and cash equivalents", "", "777.9", "478.1"],
    ]
    scale = _million_scale_for_rows(rows)

    assert scale == Decimal("1")
    assert _coerce_excel_cell_value("777.9", million_scale=scale) == Decimal("777.9")


def test_converts_thousands_to_millions() -> None:
    rows = [["Amounts in thousands of U.S. dollars", "2024"], ["Revenue", "1,234"]]
    scale = _million_scale_for_rows(rows)

    assert scale == Decimal("0.001")
    assert _coerce_excel_cell_value("1,234", million_scale=scale) == Decimal("1.234")


def test_converts_base_currency_to_millions() -> None:
    rows = [["Expressed in Korean won", "2024"], ["Cash", "1,234,000"]]
    scale = _million_scale_for_rows(rows)

    assert scale == Decimal("0.000001")
    assert _coerce_excel_cell_value("1,234,000", million_scale=scale) == Decimal("1.234")


def test_converts_billions_to_millions() -> None:
    rows = [["Amounts in billions of won", "2024"], ["Assets", "12.5"]]
    scale = _million_scale_for_rows(rows)

    assert scale == Decimal("1000")
    assert _coerce_excel_cell_value("12.5", million_scale=scale) == 12500


def test_identifies_per_share_rows_as_non_monetary() -> None:
    assert _is_non_monetary_row(["Basic earnings per share", "12.34"])


def test_normalizes_unit_header_to_millions() -> None:
    assert _normalize_unit_text_to_millions("Amounts in thousands of U.S. dollars") == "Amounts in millions of U.S. dollars"
    assert _normalize_unit_text_to_millions("Expressed in Korean won") == "Expressed in millions of Korean won"
