from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from time import perf_counter, sleep
from typing import Iterable, Literal

from loguru import logger

COMPANY_CONFIG_VERSION = 1

try:
    from financial_claw.core.models import ReportFile
    from financial_claw.core.workbook_merge import merge_workbook_sequence
    from financial_claw.extractor.cli import PdfExtractionConfig, PdfExtractionSummary, run_pdf_extraction
    from financial_claw.extractor.providers import ConfigurationError, validate_mineru_configuration
except ModuleNotFoundError:  # allows direct script execution from repo root
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from financial_claw.core.models import ReportFile  # type: ignore[no-redef]
    from financial_claw.core.workbook_merge import merge_workbook_sequence  # type: ignore[no-redef]
    from financial_claw.extractor.cli import (  # type: ignore[no-redef]
        PdfExtractionConfig,
        PdfExtractionSummary,
        run_pdf_extraction,
    )
    from financial_claw.extractor.providers import (  # type: ignore[no-redef]
        ConfigurationError,
        validate_mineru_configuration,
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


def company_config_path(company: str, *, root: str | Path = "companies") -> Path:
    return company_dir(company, root=root) / f"{company}_config.json"


def legacy_locator_config_path(company: str, *, root: str | Path = "companies") -> Path:
    return company_dir(company, root=root) / "locator_config.json"


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
        (p for p in fs_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
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


def load_company_config(company: str, *, root: str | Path = "companies") -> dict:
    config_path = company_config_path(company, root=root)
    legacy_path = legacy_locator_config_path(company, root=root)
    data: dict = {}
    for path in (config_path, legacy_path):
        if not path.exists():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
            break
    data.setdefault("config_version", COMPANY_CONFIG_VERSION)
    data.setdefault("statement_keywords", {})
    processed = data.get("processed_reports", [])
    data["processed_reports"] = processed if isinstance(processed, list) else []
    return data


def save_company_config(company: str, config: dict, *, root: str | Path = "companies") -> None:
    path = company_config_path(company, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    config["config_version"] = COMPANY_CONFIG_VERSION
    config.setdefault("statement_keywords", {})
    config.setdefault("processed_reports", [])
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def final_company_workbook_exists(company: str, *, root: str | Path = "companies") -> bool:
    return (company_dir(company, root=root) / f"{company}_financial_statements_final.xlsx").exists()


@dataclass(frozen=True)
class IngestPlan:
    mode: Literal["init", "update"]
    company: str
    companies_root: str
    financial_statements_dir: str
    final_excel_dir: str
    config_path: str
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


def plan_company_run(company: str, *, root: str | Path = "companies") -> IngestPlan:
    return plan_update(company, root=root) if final_company_workbook_exists(company, root=root) else plan_init(company, root=root)


def plan_init(company: str, *, root: str | Path = "companies") -> IngestPlan:
    sync_existing_processed_reports(company, root=root)
    config = load_company_config(company, root=root)
    reports = discover_company_pdfs(company, root=root)
    selected_reports = select_unprocessed_reports(reports, config)
    return IngestPlan(
        mode="init",
        company=company,
        companies_root=str(companies_root(root)),
        financial_statements_dir=str(financial_statements_dir(company, root=root)),
        final_excel_dir=str(final_excel_dir(company, root=root)),
        config_path=str(company_config_path(company, root=root)),
        inputs=selected_reports,
    )


def run_company_init(
    plan: IngestPlan,
    *,
    output_dir: str | Path | None = None,
    max_workers: int = 8,
    debug: bool = False,
    ocr_provider: Literal["none", "mineru"] = "mineru",
    mineru_mode: Literal["precision", "agent"] = "precision",
    ocr_language: str = "en",
    render_dpi: int = 220,
    max_continuation_pages: int = 3,
    max_retries: int = 3,
) -> CompanyRunSummary:
    run_start = perf_counter()
    worker_count = max(1, min(int(max_workers), 8, len(plan.inputs) or 1))
    output_root = Path(output_dir) if output_dir is not None else Path(plan.final_excel_dir)
    succeeded: list[PdfExtractionSummary] = []
    failed: list[CompanyRunFailure] = []
    if not plan.inputs:
        elapsed_s = perf_counter() - run_start
        logger.info("[company-run-done] company={} no new reports elapsed={:.2f}s", plan.company, elapsed_s)
        return CompanyRunSummary(plan.company, plan.mode, succeeded, failed, elapsed_s)
    logger.info("[company-run-start] mode={} company={} reports={}", plan.mode, plan.company, len(plan.inputs))
    logger.debug("max_workers={} output_dir={} ocr_provider={} mineru_mode={} debug={} max_retries={}", worker_count, output_root, ocr_provider, mineru_mode, debug, max_retries)
    if ocr_provider == "mineru":
        validate_mineru_configuration(mode=mineru_mode)

    def run_one(index: int, report: ReportFile) -> PdfExtractionSummary:
        retries = max(0, int(max_retries))
        max_attempts = retries + 1
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            attempt_start = perf_counter()
            logger.info(
                "[pdf-start] {}/{} company={} file={}",
                index,
                len(plan.inputs),
                plan.company,
                report.file_name,
            )
            try:
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
                    "[pdf-done] {}/{} file={} elapsed={:.2f}s",
                    index,
                    len(plan.inputs),
                    report.file_name,
                    perf_counter() - attempt_start,
                )
                return summary
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "[pdf-attempt-failed] {}/{} file={} attempt={}/{} error={}",
                    index,
                    len(plan.inputs),
                    report.file_name,
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts:
                    retry_delay_s = min(2 ** (attempt - 1), 10)
                    logger.debug(
                        "[pdf-retry] file={} next_attempt={}/{} delay={}s",
                        report.file_name,
                        attempt + 1,
                        max_attempts,
                        retry_delay_s,
                    )
                    sleep(retry_delay_s)
        if last_error is None:
            raise RuntimeError(f"PDF extraction failed without an error: {report.file_name}")
        raise last_error

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="financial-claw-ingest") as executor:
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
        "[company-run-done] mode={} company={} succeeded={} failed={} elapsed={:.2f}s",
        plan.mode,
        plan.company,
        len(succeeded),
        len(failed),
        elapsed_s,
    )
    if failed:
        for item in failed:
            logger.error("[company-init-failure] file={} error={}", item.report.file_name, item.error)
    return CompanyRunSummary(plan.company, plan.mode, succeeded, failed, elapsed_s)


def final_company_workbook_path(company: str, *, root: str | Path = "companies") -> Path:
    return company_dir(company, root=root) / f"{company}_financial_statements_final.xlsx"


def merge_company_init_outputs(summary: CompanyRunSummary, *, root: str | Path = "companies") -> Path | None:
    if summary.failed:
        raise ValueError("Company init has failed PDF extractions; final merge is skipped.")
    workbook_paths = [item.output_path for item in summary.succeeded]
    if not workbook_paths:
        logger.warning("[company-merge-skip] company={} no extracted workbooks to merge", summary.company)
        return None

    output_path = final_company_workbook_path(summary.company, root=root)
    logger.info(
        "[company-merge-start] company={} workbooks={} output={}",
        summary.company,
        len(workbook_paths),
        output_path,
    )
    merged_path = merge_workbook_sequence(workbook_paths, output_path)
    logger.info("[company-merge-done] company={} output={}", summary.company, merged_path)
    return merged_path


def merge_company_processed_outputs(company: str, *, root: str | Path = "companies") -> Path | None:
    config = load_company_config(company, root=root)
    workbook_paths = processed_report_workbooks(company, config, root=root)
    if not workbook_paths:
        logger.warning("[company-merge-skip] company={} no processed workbooks to merge", company)
        return None
    output_path = final_company_workbook_path(company, root=root)
    logger.info("[company-merge-start] company={} workbooks={}", company, len(workbook_paths))
    merged_path = merge_workbook_sequence(workbook_paths, output_path)
    logger.info("[company-merge-done] company={} output={}", company, merged_path.name)
    return merged_path


def processed_report_workbooks(company: str, config: dict, *, root: str | Path = "companies") -> list[Path]:
    base = company_dir(company, root=root)
    paths: list[Path] = []
    for record in config.get("processed_reports", []):
        if not isinstance(record, dict):
            continue
        rel = record.get("output_workbook")
        if not isinstance(rel, str) or not rel:
            continue
        path = (base / rel).resolve()
        if path.exists() and path.suffix.lower() == ".xlsx" and not path.name.endswith("_extraction_record.xlsx"):
            paths.append(path)
    return sorted(set(paths), key=lambda path: path.name.lower())


def plan_update(
    company: str,
    *,
    root: str | Path = "companies",
    explicit_files: list[str] | None = None,
) -> IngestPlan:
    """Plan an incremental update for a company.

    Rules:
    - If companies/<Company>/<Company>_financial_statements_final.xlsx is missing => behave like init.
    - Otherwise select PDFs whose sha256 is not yet in <Company>_config.json processed_reports.
    - If explicit_files is provided, select only those PDFs (order preserved from discovery).
    """
    if not final_company_workbook_exists(company, root=root):
        return plan_init(company, root=root)

    sync_existing_processed_reports(company, root=root)
    config = load_company_config(company, root=root)
    reports = discover_company_pdfs(company, root=root)
    selected_reports = select_unprocessed_reports(reports, config, explicit_files=explicit_files)

    return IngestPlan(
        mode="update",
        company=company,
        companies_root=str(companies_root(root)),
        financial_statements_dir=str(financial_statements_dir(company, root=root)),
        final_excel_dir=str(final_excel_dir(company, root=root)),
        config_path=str(company_config_path(company, root=root)),
        inputs=selected_reports,
    )


def select_unprocessed_reports(
    reports: list[ReportFile],
    config: dict,
    explicit_files: list[str] | None = None,
) -> list[ReportFile]:
    if explicit_files:
        allow = set(explicit_files)
        return [report for report in reports if report.pdf_path in allow or report.file_name in allow]
    seen_hashes = {
        str(record.get("sha256"))
        for record in config.get("processed_reports", [])
        if isinstance(record, dict) and record.get("sha256")
    }
    return [report for report in reports if report.sha256 not in seen_hashes]


def sync_existing_processed_reports(company: str, *, root: str | Path = "companies") -> None:
    reports = discover_company_pdfs(company, root=root)
    if not reports:
        return
    config = load_company_config(company, root=root)
    changed = False
    records = list(config.get("processed_reports", []))
    seen_hashes = {str(record.get("sha256")) for record in records if isinstance(record, dict) and record.get("sha256")}
    for report in reports:
        if report.sha256 in seen_hashes:
            continue
        output_path = existing_report_workbook(company, report, root=root)
        if output_path is None:
            continue
        records = _upsert_processed_record(records, _processed_record(company, report, output_path, root=root))
        seen_hashes.add(report.sha256)
        changed = True
    if changed:
        config["processed_reports"] = records
        save_company_config(company, config, root=root)


def record_successful_reports(plan: IngestPlan, summary: CompanyRunSummary, *, root: str | Path = "companies") -> None:
    if summary.failed:
        return
    config = load_company_config(plan.company, root=root)
    records = list(config.get("processed_reports", []))
    reports_by_path = {Path(report.pdf_path).resolve(): report for report in plan.inputs}
    for item in summary.succeeded:
        report = reports_by_path.get(Path(item.pdf_path).resolve())
        if report is None:
            continue
        records = _upsert_processed_record(records, _processed_record(plan.company, report, item.output_path, root=root))
    config["processed_reports"] = records
    save_company_config(plan.company, config, root=root)


def existing_report_workbook(company: str, report: ReportFile, *, root: str | Path = "companies") -> Path | None:
    excel_dir = final_excel_dir(company, root=root) / "excel"
    safe_stem = _safe_name(Path(report.file_name).stem)
    pattern = f"{company}_{safe_stem}_statements*.xlsx"
    candidates = [
        path
        for path in excel_dir.glob(pattern)
        if path.is_file() and not path.name.endswith("_extraction_record.xlsx")
    ]
    return sorted(candidates, key=lambda path: path.name.lower())[0] if candidates else None


def _processed_record(company: str, report: ReportFile, output_path: Path, *, root: str | Path = "companies") -> dict:
    base = company_dir(company, root=root).resolve()
    try:
        output_rel = output_path.resolve().relative_to(base).as_posix()
    except ValueError:
        output_rel = str(output_path)
    try:
        source_rel = Path(report.pdf_path).resolve().relative_to(base).as_posix()
    except ValueError:
        source_rel = str(report.pdf_path)
    return {
        "file_name": report.file_name,
        "source_path": source_rel,
        "sha256": report.sha256,
        "mtime": report.mtime,
        "output_workbook": output_rel,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def _upsert_processed_record(records: list, record: dict) -> list:
    source_path = record.get("source_path")
    sha256 = record.get("sha256")
    kept = [
        item
        for item in records
        if not (
            isinstance(item, dict)
            and (item.get("source_path") == source_path or item.get("sha256") == sha256)
        )
    ]
    kept.append(record)
    return sorted(kept, key=lambda item: str(item.get("file_name", "")).lower() if isinstance(item, dict) else "")


def _safe_name(name: str) -> str:
    keep = []
    for char in name:
        keep.append(char if char.isalnum() or char in "-_" else "_")
    return "".join(keep).strip("_")[:80]


def configure_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser(description="Company-level financial statement ingestion.")
    parser.add_argument("company", nargs="?", default="GOODMAN")
    parser.add_argument("mode", nargs="?", choices=["run", "init", "update"], default="run")
    parser.add_argument("--companies-root", default="companies")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Company init output root. Defaults to companies/<COMPANY>/final_excel.",
    )
    parser.add_argument("--max-workers", type=int, default=8, help="Maximum parallel PDF extractions; capped at 8.")
    parser.add_argument("--debug", action="store_true", help="Write page text debug files for each PDF.")
    parser.add_argument("--ocr-provider", choices=["none", "mineru"], default="mineru")
    parser.add_argument("--mineru-mode", choices=["precision", "agent"], default="precision")
    parser.add_argument("--ocr-language", default="en")
    parser.add_argument("--render-dpi", type=int, default=220)
    parser.add_argument("--max-continuation-pages", type=int, default=3)
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries per failed PDF extraction. Default: 3 retries after the first attempt.",
    )
    parser.add_argument("--plan-only", action="store_true", help="Only print the ingest plan; do not extract PDFs.")
    args = parser.parse_args()

    cwd_root = Path(args.companies_root)
    if args.mode == "init":
        plan = plan_init(args.company, root=cwd_root) if not final_company_workbook_exists(args.company, root=cwd_root) else plan_update(args.company, root=cwd_root)
    elif args.mode == "update":
        plan = plan_update(args.company, root=cwd_root)
    else:
        plan = plan_company_run(args.company, root=cwd_root)
    logger.info("company={} mode={} selected_reports={}", plan.company, plan.mode, len(plan.inputs))
    logger.debug("requested_mode={}", args.mode)
    logger.debug("financial_statements_dir={}", plan.financial_statements_dir)
    logger.debug("final_excel_dir={}", plan.final_excel_dir)
    logger.debug("config_path={}", plan.config_path)
    for r in plan.inputs[:20]:
        logger.debug("- {} sha256={}... mtime={}", r.file_name, r.sha256[:12], r.mtime)

    if not args.plan_only:
        try:
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
                max_retries=args.max_retries,
            )
        except ConfigurationError as exc:
            logger.warning("[configuration-check-failed] {}", exc)
            raise SystemExit(1) from None
        if summary.failed:
            raise SystemExit(1)
        record_successful_reports(plan, summary, root=cwd_root)
        if summary.succeeded or not final_company_workbook_exists(summary.company, root=cwd_root):
            try:
                merge_company_processed_outputs(summary.company, root=cwd_root)
            except Exception as exc:  # noqa: BLE001
                logger.error("[company-merge-failed] company={} error={}", summary.company, exc)
                raise SystemExit(1) from exc
        else:
            logger.debug("[company-merge-skip] company={} no new processed reports", summary.company)
