from typer.testing import CliRunner

from fa.cli import app
from fa.export import build_main_workbook


def test_workbook_exports_three_required_tabs():
    workbook = build_main_workbook()
    assert workbook.sheetnames == [
        "Balance Sheet",
        "Income Statement",
        "Cash Flow &Comprehensive Income",
    ]


def test_cli_commands_exit_zero_in_dry_run_mode():
    runner = CliRunner()
    assert runner.invoke(app, ["init", "--company", "TESTCO", "--dry-run"]).exit_code == 0
    assert runner.invoke(app, ["update", "--company", "TESTCO", "--dry-run"]).exit_code == 0
