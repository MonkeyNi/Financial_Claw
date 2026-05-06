from typer.testing import CliRunner

from fa.cli import app


def test_init_command_invokes_without_error():
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--company", "POSCO", "--dry-run"])
    assert result.exit_code == 0
    assert "POSCO" in result.stdout


def test_update_accepts_explicit_files_flag():
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "update",
            "--company",
            "POSCO",
            "--dry-run",
            "--files",
            "path/a.pdf",
            "--files",
            "path/b.pdf",
        ],
    )
    assert result.exit_code == 0
    assert "path/a.pdf" in result.stdout
