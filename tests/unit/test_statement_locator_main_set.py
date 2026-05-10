from __future__ import annotations

from financial_claw.extractor.models import PageProfile
from financial_claw.extractor.statement_locator import locate_statement_candidates


def _profile(page_number: int, text: str) -> PageProfile:
    return PageProfile(
        page_number=page_number,
        text=text,
        line_count=len(text.splitlines()),
        word_count=len(text.split()),
        has_embedded_text=bool(text.strip()),
        width=600,
        height=800,
    )


def test_ignores_later_complete_appendix_statement_set() -> None:
    pages = [_profile(idx, "Management discussion") for idx in range(1, 41)]
    pages[9] = _profile(10, "Consolidated statements of financial position\nas at 30 June 2025")
    pages[10] = _profile(11, "Consolidated income statements\nfor the year ended 30 June 2025")
    pages[12] = _profile(13, "Consolidated cash flow statements\nfor the year ended 30 June 2025")
    pages[24] = _profile(25, "Appendix\nAdditional financial information")
    pages[29] = _profile(30, "Consolidated statement of financial position\nas at 30 June 2025")
    pages[30] = _profile(31, "Consolidated statement of comprehensive income\nfor the year ended 30 June 2025")
    pages[32] = _profile(33, "Consolidated cash flow statement\nfor the year ended 30 June 2025")

    candidates = locate_statement_candidates(pages)

    assert [(candidate.statement_type, candidate.page_start) for candidate in candidates] == [
        ("balance_sheet", 10),
        ("income_statement", 11),
        ("cash_flow", 13),
    ]


def test_infers_titleless_statement_pages_from_table_labels() -> None:
    pages = [_profile(idx, "Management discussion") for idx in range(1, 8)]
    pages[0] = _profile(
        1,
        "ANNUAL REPORT 2023\n89\nGoodman\nGIT\nNote\n2023\n$M\n2022\n$M\n"
        "Current assets\nCash and cash equivalents\nTotal assets\n"
        "Current liabilities\nTotal liabilities\nEquity\nTotal equity",
    )
    pages[1] = _profile(
        2,
        "GOODMAN GROUP\n90\nGoodman\nGIT\nNote\n2023\n$M\n2022\n$M\n"
        "Revenue\nGross property income\nProperty expenses\nDevelopment expenses\n"
        "Profit for the year",
    )
    pages[5] = _profile(
        6,
        "GOODMAN GROUP\n94\nGoodman\nGIT\nNote\n2023\n$M\n2022\n$M\n"
        "Cash flows from operating activities\nProperty income received\n"
        "Cash flows from investing activities\nNet cash provided by operating activities",
    )

    candidates = locate_statement_candidates(pages)

    assert [(candidate.statement_type, candidate.page_start) for candidate in candidates] == [
        ("balance_sheet", 1),
        ("income_statement", 2),
        ("cash_flow", 6),
    ]


def test_does_not_match_statement_title_inside_note_prose() -> None:
    pages = [
        _profile(
            1,
            "CAPITAL MANAGEMENT\n"
            "Interest is recognised on an accruals basis and, if not received at the reporting date, "
            "is reflected in the consolidated statement of financial position as a receivable.\n"
            "Note\n2023\n$M\n2022\n$M\nFinance income\nInterest income",
        )
    ]

    assert locate_statement_candidates(pages) == []


def test_does_not_infer_statement_tables_inside_notes_disclosures() -> None:
    pages = [
        _profile(
            1,
            "LG Energy Solution, Ltd. and its subsidiaries\n"
            "Notes to the consolidated financial statements\n"
            "As of and for the years ended December 31, 2023 and 2022\n"
            "(2) The consolidated statements of financial position of subsidiaries whose non-controlling interests "
            "are material to the Group (before the elimination of intercompany transactions)\n"
            "Total assets\nCurrent assets\nNon-current assets\nTotal liabilities\nCurrent liabilities\n"
            "Non-current liabilities\nTotal equity",
        ),
        _profile(
            2,
            "LG Energy Solution, Ltd. and its subsidiaries\n"
            "Notes to the consolidated financial statements\n"
            "(4) The consolidated statements of cash flows of subsidiaries whose non-controlling interests "
            "are material to the Group are as follows\n"
            "Cash flows from operating activities\nCash flows from investing activities\n"
            "Cash flows from financing activities\nCash and cash equivalents at the end of the period",
        ),
    ]

    assert locate_statement_candidates(pages) == []


def test_accepts_interim_condensed_statement_headings() -> None:
    pages = [
        _profile(
            1,
            "POSCO HOLDINGS INC. and its subsidiaries\n"
            "Interim condensed consolidated statements of financial position\n"
            "as of September 30, 2024 (Unaudited) and December 31, 2023\n"
            "(in millions of Won)\nAssets\nCash and cash equivalents\nTotal assets",
        ),
        _profile(
            2,
            "POSCO HOLDINGS INC. and its subsidiaries\n"
            "Interim condensed consolidated statements of financial position, continued\n"
            "Liabilities\nCurrent liabilities\nTotal liabilities\nEquity\nTotal equity",
        ),
        _profile(
            3,
            "POSCO HOLDINGS INC. and its subsidiaries\n"
            "Interim condensed consolidated statements of comprehensive income\n"
            "Revenue\nCost of sales\nGross profit\nProfit for the period",
        ),
        _profile(
            6,
            "POSCO HOLDINGS INC. and its subsidiaries\n"
            "Interim condensed consolidated statements of cash flows\n"
            "Cash flows from operating activities\nNet cash provided by operating activities",
        ),
    ]

    candidates = locate_statement_candidates(pages, max_continuation_pages=2)

    assert [(candidate.statement_type, candidate.page_start) for candidate in candidates] == [
        ("balance_sheet", 1),
        ("income_statement", 3),
        ("cash_flow", 6),
    ]


def test_accepts_comprehensive_income_or_loss_heading_from_company_config() -> None:
    pages = [
        _profile(
            1,
            "POSCO HOLDINGS INC. and its subsidiaries\n"
            "Interim condensed consolidated statements of comprehensive income or loss\n"
            "Revenue\nCost of sales\nGross profit\nProfit for the period",
        )
    ]

    candidates = locate_statement_candidates(
        pages,
        locator_config={
            "statement_keywords": {
                "income_statement": ["consolidated statements of comprehensive income or loss"]
            }
        },
    )

    assert [(candidate.statement_type, candidate.page_start, candidate.reason) for candidate in candidates] == [
        ("income_statement", 1, "company_locator_config")
    ]


def test_accepts_comprehensive_income_loss_parenthetical_heading() -> None:
    pages = [
        _profile(
            1,
            "SK hynix Inc. and Subsidiaries\n"
            "Consolidated Statements of Comprehensive Income (Loss)\n"
            "Years ended December 31, 2024 and 2023\n"
            "Revenue\nCost of sales\nGross profit (loss)",
        )
    ]

    candidates = locate_statement_candidates(pages)

    assert [(candidate.statement_type, candidate.page_start) for candidate in candidates] == [
        ("income_statement", 1)
    ]


def test_drops_later_partial_duplicate_after_complete_main_set() -> None:
    pages = [_profile(idx, "Management discussion") for idx in range(1, 30)]
    pages[0] = _profile(
        1,
        "Goodman\nGIT\nNote\n2023\n$M\n2022\n$M\nCurrent assets\nTotal assets\n"
        "Current liabilities\nTotal liabilities\nEquity",
    )
    pages[1] = _profile(
        2,
        "Revenue\nProperty expenses\nDevelopment expenses\nProfit for the year",
    )
    pages[5] = _profile(
        6,
        "Cash flows from operating activities\nCash flows from investing activities\nNet cash",
    )
    pages[19] = _profile(
        20,
        "Current assets\nTotal assets\nCurrent liabilities\nTotal liabilities\nEquity",
    )

    candidates = locate_statement_candidates(pages)

    assert [(candidate.statement_type, candidate.page_start) for candidate in candidates] == [
        ("balance_sheet", 1),
        ("income_statement", 2),
        ("cash_flow", 6),
    ]


def test_income_continuation_stops_before_equity_statement_pages() -> None:
    pages = [_profile(idx, "Management discussion") for idx in range(1, 6)]
    pages[0] = _profile(
        1,
        "Revenue\nProperty expenses\nDevelopment expenses\nProfit for the year",
    )
    pages[1] = _profile(
        2,
        "Profit for the year\nOther comprehensive income for the year\n"
        "Income tax\nTotal comprehensive income for the year\n"
        "2023\n$M\n2022\n$M\n2023\n$M\n2022\n$M\n"
        "1,559.9\n3,414.0\n1,138.0\n2,067.6\n0.5\n5.6\n2.4\n15.9\n363.2\n1,920.6",
    )
    pages[2] = _profile(
        3,
        "Attributable to Securityholders\nIssued capital\nTotal reserves\n"
        "Retained earnings\nTotal\nBalance at 1 July 2021\n"
        "Total comprehensive income/(loss) for the year\nProfit for the year",
    )

    candidates = locate_statement_candidates(pages)

    assert len(candidates) == 1
    assert candidates[0].statement_type == "income_statement"
    assert candidates[0].page_start == 1
    assert candidates[0].page_end == 2
