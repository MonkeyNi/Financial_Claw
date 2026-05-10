from __future__ import annotations

from financial_claw.extractor.table_extractor import _align_continuation_rows
from financial_claw.extractor.table_extractor import _merge_multiline_headers


def test_drops_ocr_helper_currency_column_from_continuation_page() -> None:
    rows = [
        ["(in millions of Won)", "Notes", "", "September 30, 2025(unaudited)", "December 31,2024"],
        ["Trade accounts and notes payable", "21,33", "KRW", "5,239,219", "6,159,127"],
        ["Total liabilities", "", "", "40,544,452", "41,953,831"],
    ]

    aligned = _align_continuation_rows(rows, [["label", "notes", "current", "prior"]])

    assert aligned == [
        ["(in millions of Won)", "Notes", "September 30, 2025(unaudited)", "December 31,2024"],
        ["Trade accounts and notes payable", "21,33", "5,239,219", "6,159,127"],
        ["Total liabilities", "", "40,544,452", "41,953,831"],
    ]


def test_currency_mojibake_amount_does_not_merge_data_row_into_header() -> None:
    rows = [
        ["(in millions of Won, except per share information)", "Notes", "2024", "2023"],
        ["Revenue", "28,29,37", "鈧?72,688,143", "77,127,197"],
        ["Cost of sales", "29,31,34", "(67,275,205)", "(70,710,292)"],
    ]

    assert _merge_multiline_headers(rows) == rows
