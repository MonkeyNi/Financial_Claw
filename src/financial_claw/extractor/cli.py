from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

from loguru import logger

from .excel_writer import write_workbook
from .metadata import extract_metadata, infer_company_from_path
from .pdf_profile import extract_page_text_debug, load_page_profiles
from .providers import MinerUOCRProvider, validate_mineru_configuration
from .statement_locator import locate_statement_candidates
from .table_extractor import extract_candidate_tables
from .models import ExtractionResult


@dataclass(frozen=True)
class PdfExtractionConfig:
    pdf_path: Path
    output_dir: Path = Path("outputs")
    company: str = ""
    debug: bool = False
    max_continuation_pages: int = 3
    ocr_provider: Literal["none", "mineru"] = "none"
    mineru_mode: Literal["precision", "agent"] = "precision"
    ocr_language: str = "en"
    render_dpi: int = 220


@dataclass(frozen=True)
class PdfExtractionSummary:
    pdf_path: Path
    output_path: Path
    debug_dir: Path
    pages: int
    candidates: int
    elapsed_s: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract consolidated financial statements from one PDF.")
    parser.add_argument("--pdf", required=True, help="Path to one PDF report.")
    parser.add_argument("--output-dir", default="outputs", help="Output root directory.")
    parser.add_argument("--company", default="", help="Optional company override.")
    parser.add_argument("--debug", action="store_true", help="Write page text and candidate debug files.")
    parser.add_argument("--max-continuation-pages", type=int, default=3)
    parser.add_argument("--ocr-provider", choices=["none", "mineru"], default="none")
    parser.add_argument("--mineru-mode", choices=["precision", "agent"], default="precision")
    parser.add_argument("--ocr-language", default="en")
    parser.add_argument("--render-dpi", type=int, default=220)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_pdf_extraction(
        PdfExtractionConfig(
            pdf_path=Path(args.pdf),
            output_dir=Path(args.output_dir),
            company=args.company,
            debug=args.debug,
            max_continuation_pages=args.max_continuation_pages,
            ocr_provider=args.ocr_provider,
            mineru_mode=args.mineru_mode,
            ocr_language=args.ocr_language,
            render_dpi=args.render_dpi,
        )
    )
    return 0


def validate_pdf_extraction_config(config: PdfExtractionConfig) -> None:
    if config.ocr_provider == "mineru":
        validate_mineru_configuration(mode=config.mineru_mode)


def run_pdf_extraction(config: PdfExtractionConfig) -> PdfExtractionSummary:
    run_start = perf_counter()
    pdf_path = config.pdf_path.resolve()
    output_root = config.output_dir.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    validate_pdf_extraction_config(config)

    logger.info("Starting extraction")
    logger.info("PDF: {}", pdf_path)
    logger.info("Output root: {}", output_root)
    logger.info(
        "Options: debug={} ocr_provider={} mineru_mode={} ocr_language={} render_dpi={}",
        config.debug,
        config.ocr_provider,
        config.mineru_mode,
        config.ocr_language,
        config.render_dpi,
    )

    company = config.company or infer_company_from_path(pdf_path)
    debug_dir = output_root / "debug" / company / pdf_path.stem
    excel_dir = output_root / "excel"

    step_start = _log_step_start("Load PDF page profiles")
    profiles = load_page_profiles(pdf_path)
    _log_step_done("Load PDF page profiles", step_start, pages=len(profiles))

    step_start = _log_step_start("Extract metadata")
    metadata = extract_metadata(pdf_path, profiles)
    metadata["company"] = company
    metadata["ocr_provider_status"] = config.ocr_provider
    metadata["ocr_language"] = config.ocr_language
    metadata["llm_fallback_status"] = "placeholder_not_used"
    _log_step_done("Extract metadata", step_start, company=company)

    step_start = _log_step_start("Locate statement candidates")
    candidates = locate_statement_candidates(profiles, max_continuation_pages=config.max_continuation_pages)
    _log_step_done("Locate statement candidates", step_start, candidates=len(candidates))
    for candidate in candidates:
        logger.info(
            "Candidate: type={} pages={}..{} title={!r} score={}",
            candidate.statement_type,
            candidate.page_start,
            candidate.page_end,
            candidate.title,
            candidate.score,
        )

    ocr_provider = None
    if config.ocr_provider == "mineru":
        logger.info(
            "Initializing MinerU OCR provider: mode={} language={} dpi={} debug_dir={}",
            config.mineru_mode,
            config.ocr_language,
            config.render_dpi,
            debug_dir,
        )
        ocr_provider = MinerUOCRProvider(
            debug_dir,
            mode=config.mineru_mode,
            language=config.ocr_language,
            dpi=config.render_dpi,
        )
        metadata["mineru_mode"] = config.mineru_mode
        metadata["render_dpi"] = str(config.render_dpi)

    step_start = _log_step_start("Extract candidate tables")
    extracted_results = extract_candidate_tables(pdf_path, candidates, ocr_provider=ocr_provider)
    _log_step_done("Extract candidate tables", step_start, results=len(extracted_results))

    step_start = _log_step_start("Merge comprehensive income")
    results = merge_comprehensive_income(extracted_results)
    _log_step_done("Merge comprehensive income", step_start, results=len(results))

    output_path = excel_dir / f"{company}_{_safe_name(pdf_path.stem)}_statements.xlsx"
    step_start = _log_step_start("Write Excel outputs")
    output_path = write_with_available_name(output_path, metadata, profiles, candidates, results)
    _log_step_done("Write Excel outputs", step_start, output=output_path)

    step_start = _log_step_start("Write debug metadata")
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (debug_dir / "candidates.json").write_text(
        json.dumps([candidate.to_dict() for candidate in candidates], indent=2),
        encoding="utf-8",
    )
    _log_step_done("Write debug metadata", step_start, debug_dir=debug_dir)

    if config.debug:
        step_start = _log_step_start("Write page text debug files")
        extract_page_text_debug(pdf_path, debug_dir / "page_text")
        _log_step_done("Write page text debug files", step_start)

    logger.info("Pages: {}", len(profiles))
    logger.info("Candidates: {}", len(candidates))
    logger.info("Excel: {}", output_path)
    logger.info("Debug: {}", debug_dir)
    elapsed_s = perf_counter() - run_start
    logger.info("Extraction finished in {:.2f}s", elapsed_s)
    return PdfExtractionSummary(
        pdf_path=pdf_path,
        output_path=output_path,
        debug_dir=debug_dir,
        pages=len(profiles),
        candidates=len(candidates),
        elapsed_s=elapsed_s,
    )


def _log_step_start(name: str) -> float:
    logger.info("[step] {} ...", name)
    return perf_counter()


def _log_step_done(name: str, start: float, **fields: object) -> None:
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("[done] {} in {:.2f}s{}", name, perf_counter() - start, f" ({suffix})" if suffix else "")


def _safe_name(name: str) -> str:
    keep = []
    for char in name:
        keep.append(char if char.isalnum() or char in "-_" else "_")
    return "".join(keep).strip("_")[:80]


def write_with_available_name(output_path, metadata, profiles, candidates, results):
    for idx in range(10):
        candidate_path = output_path if idx == 0 else output_path.with_name(f"{output_path.stem}_run{idx + 1}{output_path.suffix}")
        try:
            write_workbook(candidate_path, metadata, profiles, candidates, results)
            return candidate_path
        except PermissionError:
            if idx == 9:
                raise
    return output_path


def merge_comprehensive_income(results: list[ExtractionResult]) -> list[ExtractionResult]:
    merged: list[ExtractionResult] = []
    for result in results:
        result = copy.deepcopy(result)
        title = result.candidate.title.lower()
        is_comprehensive = "comprehensive income" in title
        if (
            is_comprehensive
            and merged
            and merged[-1].candidate.statement_type == "income_statement"
            and result.candidate.page_start <= merged[-1].candidate.page_end + 2
        ):
            merged[-1].rows.append([])
            merged[-1].rows.extend(result.rows)
            merged[-1].candidate.page_end = max(merged[-1].candidate.page_end, result.candidate.page_end)
            merged[-1].candidate.source_pages.extend(result.candidate.source_pages)
            merged[-1].warnings.extend(result.warnings)
            continue
        merged.append(result)
    return merged


if __name__ == "__main__":
    raise SystemExit(main())
