from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Iterable, Literal

from loguru import logger

try:
    from financial_claw.core.models import ReportFile
    from financial_claw.extractor.cli import PdfExtractionConfig, PdfExtractionSummary, run_pdf_extraction
except ModuleNotFoundError:  # allows direct script execution from repo root
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from financial_claw.core.models import ReportFile  # type: ignore[no-redef]
    from financial_claw.extractor.cli import (  # type: ignore[no-redef]
        PdfExtractionConfig,
        PdfExtractionSummary,
        run_pdf_extraction,
    )


def select_input_files(
    files: Iterable[tuple[str, str]],
    manifest: dict,
    explicit_files: list[str] | None,
) -> list[tuple[str, str]]:
    """Choose which (path, sha256) pairs to process.

    - If ``explicit_files`` is non-empty, return only entries whose path is in
      that list (order preserved from ``files``).
    - Otherwise return entries whose hash is not listed in
      ``manifest["seen_hashes"]``.
    """
    rows = list(files)
    if explicit_files:
        allow = set(explicit_files)
        return [f for f in rows if f[0] in allow]
    seen = set(manifest.get("seen_hashes", []))
    return [f for f in rows if f[1] not in seen]


def companies_root(default: str | Path = "companies") -> Path:
    return Path(default)


def company_dir(company: str, *, root: str | Path = "companies") -> Path:
    return companies_root(root) / company


def financial_statements_dir(company: str, *, root: str | Path = "companies") -> Path:
    return company_dir(company, root=root) / "Financial_Statements"


def final_excel_dir(company: str, *, root: str | Path = "companies") -> Path:
    return company_dir(company, root=root) / "final_excel"


def manifest_path(company: str, *, root: str | Path = "companies") -> Path:
    return final_excel_dir(company, root=root) / ".processed.json"


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def discover_company_pdfs(
    company: str,
    *,
    root: str | Path = "companies",
) -> list[ReportFile]:
    """Find all PDFs under companies/<Company>/Financial_Statements.

    This function only discovers file metadata (path/hash/mtime); it does not
    parse or extract content.
    """
    fs_dir = financial_statements_dir(company, root=root)
    if not fs_dir.exists():
        return []

    pdf_paths = sorted(
        (p for p in fs_dir.glob("*.pdf") if p.is_file()),
        key=lambda p: p.name.lower(),
    )
    out: list[ReportFile] = []
    for p in pdf_paths:
        st = p.stat()
        out.append(
            ReportFile(
                company=company,
                pdf_path=str(p),
                file_name=p.name,
                sha256=_sha256_file(p),
                mtime=st.st_mtime,
            )
        )
    return out


def load_manifest(company: str, *, root: str | Path = "companies") -> dict:
    """Load incremental manifest from final_excel/.processed.json.

    Returns a dict containing at least:
      - seen_hashes: list[str]
    """
    mp = manifest_path(company, root=root)
    if not mp.exists():
        return {"seen_hashes": []}
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return {"seen_hashes": []}
    if not isinstance(data, dict):
        return {"seen_hashes": []}
    seen = data.get("seen_hashes", [])
    if not isinstance(seen, list):
        seen = []
    data["seen_hashes"] = [str(x) for x in seen]
    return data


def save_manifest(company: str, manifest: dict, *, root: str | Path = "companies") -> None:
    """Persist manifest to final_excel/.processed.json.

    Note: pipeline steps later should update the manifest; ingest only provides
    the IO layer.
    """
    mp = manifest_path(company, root=root)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def final_excel_is_empty(company: str, *, root: str | Path = "companies") -> bool:
    d = final_excel_dir(company, root=root)
    if not d.exists():
        return True
    # "Empty" means no Excel outputs yet. Keep it simple: any .xlsx means not empty.
    return not any(d.glob("*.xlsx"))


@dataclass(frozen=True)
class IngestPlan:
    mode: Literal["init", "update"]
    company: str
    companies_root: str
    financial_statements_dir: str
    final_excel_dir: str
    manifest_path: str
    inputs: list[ReportFile]


@dataclass(frozen=True)
class CompanyRunFailure:
    report: ReportFile
    error: str


@dataclass(frozen=True)
class CompanyRunSummary:
    company: str
    mode: Literal["init", "update"]
    succeeded: list[PdfExtractionSummary]
    failed: list[CompanyRunFailure]
    elapsed_s: float


def plan_init(company: str, *, root: str | Path = "companies") -> IngestPlan:
    reports = discover_company_pdfs(company, root=root)
    return IngestPlan(
        mode="init",
        company=company,
        companies_root=str(companies_root(root)),
        financial_statements_dir=str(financial_statements_dir(company, root=root)),
        final_excel_dir=str(final_excel_dir(company, root=root)),
        manifest_path=str(manifest_path(company, root=root)),
        inputs=reports,
    )


def run_company_init(
    plan: IngestPlan,
    *,
    output_dir: str | Path = "outputs",
    max_workers: int = 8,
    debug: bool = False,
    ocr_provider: Literal["none", "mineru"] = "mineru",
    mineru_mode: Literal["precision", "agent"] = "precision",
    ocr_language: str = "en",
    render_dpi: int = 220,
    max_continuation_pages: int = 3,
) -> CompanyRunSummary:
    if plan.mode != "init":
        raise ValueError(f"run_company_init requires an init plan, got {plan.mode!r}")

    run_start = perf_counter()
    worker_count = max(1, min(int(max_workers), 8, len(plan.inputs) or 1))
    output_root = Path(output_dir)
    logger.info(
        "[company-init] company={} pdfs={} max_workers={} output_dir={} ocr_provider={} mineru_mode={} debug={}",
        plan.company,
        len(plan.inputs),
        worker_count,
        output_root,
        ocr_provider,
        mineru_mode,
        debug,
    )

    succeeded: list[PdfExtractionSummary] = []
    failed: list[CompanyRunFailure] = []
    if not plan.inputs:
        elapsed_s = perf_counter() - run_start
        logger.warning("[company-init-done] company={} no PDFs found elapsed={:.2f}s", plan.company, elapsed_s)
        return CompanyRunSummary(plan.company, plan.mode, succeeded, failed, elapsed_s)

    def run_one(index: int, report: ReportFile) -> PdfExtractionSummary:
        logger.info("[pdf-start] {}/{} company={} file={}", index, len(plan.inputs), plan.company, report.file_name)
        pdf_start = perf_counter()
        summary = run_pdf_extraction(
            PdfExtractionConfig(
                pdf_path=Path(report.pdf_path),
                output_dir=output_root,
                company=plan.company,
                debug=debug,
                max_continuation_pages=max_continuation_pages,
                ocr_provider=ocr_provider,
                mineru_mode=mineru_mode,
                ocr_language=ocr_language,
                render_dpi=render_dpi,
            )
        )
        logger.info(
            "[pdf-done] {}/{} file={} elapsed={:.2f}s output={}",
            index,
            len(plan.inputs),
            report.file_name,
            perf_counter() - pdf_start,
            summary.output_path,
        )
        return summary

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="financial-claw-init") as executor:
        future_to_report = {
            executor.submit(run_one, idx, report): report
            for idx, report in enumerate(plan.inputs, start=1)
        }
        for future in as_completed(future_to_report):
            report = future_to_report[future]
            try:
                succeeded.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.exception("[pdf-failed] company={} file={} error={}", plan.company, report.file_name, exc)
                failed.append(CompanyRunFailure(report=report, error=str(exc)))

    elapsed_s = perf_counter() - run_start
    logger.info(
        "[company-init-done] company={} succeeded={} failed={} elapsed={:.2f}s",
        plan.company,
        len(succeeded),
        len(failed),
        elapsed_s,
    )
    if failed:
        for item in failed:
            logger.error("[company-init-failure] file={} error={}", item.report.file_name, item.error)
    return CompanyRunSummary(plan.company, plan.mode, succeeded, failed, elapsed_s)


def plan_update(
    company: str,
    *,
    root: str | Path = "companies",
    explicit_files: list[str] | None = None,
) -> IngestPlan:
    """Plan an incremental update for a company.

    Rules:
    - If companies/<Company>/final_excel is empty => behave like init (process all PDFs).
    - Otherwise select PDFs under Financial_Statements whose sha256 is not yet in manifest.
    - If explicit_files is provided, select only those PDFs (order preserved from discovery).
    """
    if final_excel_is_empty(company, root=root):
        return plan_init(company, root=root)

    manifest = load_manifest(company, root=root)
    reports = discover_company_pdfs(company, root=root)
    pairs = [(r.pdf_path, r.sha256) for r in reports]
    selected_pairs = select_input_files(pairs, manifest, explicit_files=explicit_files)
    allow_paths = {p for (p, _) in selected_pairs}
    selected_reports = [r for r in reports if r.pdf_path in allow_paths]

    return IngestPlan(
        mode="update",
        company=company,
        companies_root=str(companies_root(root)),
        financial_statements_dir=str(financial_statements_dir(company, root=root)),
        final_excel_dir=str(final_excel_dir(company, root=root)),
        manifest_path=str(manifest_path(company, root=root)),
        inputs=selected_reports,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Company-level financial statement ingestion.")
    parser.add_argument("company", nargs="?", default="GOODMAN")
    parser.add_argument("mode", nargs="?", choices=["init", "update"], default="update")
    parser.add_argument("--companies-root", default="companies")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--max-workers", type=int, default=8, help="Maximum parallel PDF extractions; capped at 8.")
    parser.add_argument("--debug", action="store_true", help="Write page text debug files for each PDF.")
    parser.add_argument("--ocr-provider", choices=["none", "mineru"], default="mineru")
    parser.add_argument("--mineru-mode", choices=["precision", "agent"], default="precision")
    parser.add_argument("--ocr-language", default="en")
    parser.add_argument("--render-dpi", type=int, default=220)
    parser.add_argument("--max-continuation-pages", type=int, default=3)
    parser.add_argument("--plan-only", action="store_true", help="Only print the ingest plan; do not extract PDFs.")
    args = parser.parse_args()

    cwd_root = Path(args.companies_root)
    plan = plan_init(args.company, root=cwd_root) if args.mode == "init" else plan_update(args.company, root=cwd_root)
    logger.info("mode={} company={}", plan.mode, plan.company)
    logger.info("financial_statements_dir={}", plan.financial_statements_dir)
    logger.info("final_excel_dir={}", plan.final_excel_dir)
    logger.info("manifest_path={}", plan.manifest_path)
    logger.info("inputs={}", len(plan.inputs))
    for r in plan.inputs[:20]:
        logger.info("- {} sha256={}... mtime={}", r.file_name, r.sha256[:12], r.mtime)

    if args.mode == "init" and not args.plan_only:
        summary = run_company_init(
            plan,
            output_dir=args.output_dir,
            max_workers=args.max_workers,
            debug=args.debug,
            ocr_provider=args.ocr_provider,
            mineru_mode=args.mineru_mode,
            ocr_language=args.ocr_language,
            render_dpi=args.render_dpi,
            max_continuation_pages=args.max_continuation_pages,
        )
        if summary.failed:
            raise SystemExit(1)
