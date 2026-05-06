from __future__ import annotations

import typer

app = typer.Typer(help="Financial statement PDF extraction tooling")


@app.command()
def init(
    company: str = typer.Option(..., "--company", help="Company folder key under ./companies/"),
    rebuild: bool = typer.Option(False, help="Bypass caches and regenerate intermediates."),
    dry_run: bool = typer.Option(False, help="Show actions without touching outputs."),
):
    """Process every PDF discovered under Financial_Statements/."""
    if dry_run:
        typer.echo(f"[dry-run] init company={company!r} rebuild={rebuild}")
        return
    raise NotImplementedError("Full pipeline orchestration arrives in iteration 2")


@app.command()
def update(
    company: str = typer.Option(..., "--company", help="Company folder key under ./companies/"),
    dry_run: bool = typer.Option(False, help="Preview which PDFs would be ingested."),
    files: list[str] | None = typer.Option(
        None,
        "--files",
        help="Explicit PDF paths; bypasses incremental manifest filtering.",
    ),
):
    """Add newly discovered (or explicit) PDFs to the consolidated workbook."""
    if dry_run:
        typer.echo(f"[dry-run] update company={company!r} files={files or []}")
        return
    raise NotImplementedError("Full pipeline orchestration arrives in iteration 2")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
