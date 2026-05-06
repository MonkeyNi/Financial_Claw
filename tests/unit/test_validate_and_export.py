from fa.export import build_main_workbook
from fa.validate import within_tolerance
from fa.warnings_log import WarningCollector


def test_rounding_aware_tolerance_default():
    assert within_tolerance(reported=100.0, calculated=100.4, tolerance=0.5) is True
    assert within_tolerance(reported=100.0, calculated=100.6, tolerance=0.5) is False


def test_build_main_workbook_sheet_names():
    wb = build_main_workbook()
    titles = {ws.title for ws in wb.worksheets}
    assert titles == {
        "Balance Sheet",
        "Income Statement",
        "Cash Flow & Comprehensive Income",
    }


def test_warning_collector_appends_record():
    log = WarningCollector()
    log.add(severity="Info", issue_type="ocr", message="used ocr")
    assert len(log.records) == 1
    assert log.records[0].issue_type == "ocr"
