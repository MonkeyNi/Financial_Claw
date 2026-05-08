from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from loguru import logger

from .excel_writer import write_workbook
from .metadata import extract_metadata, infer_company_from_path
from .pdf_profile import extract_page_text_debug, load_page_profiles
from .providers import MinerUOCRProvider
from .statement_locator import locate_statement_candidates
from .table_extractor import extract_candidate_tables
from .models import ExtractionResult


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
    pdf_path = Path(args.pdf).resolve()
    output_root = Path(args.output_dir).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    company = args.company or infer_company_from_path(pdf_path)
    debug_dir = output_root / "debug" / company / pdf_path.stem
    excel_dir = output_root / "excel"

    profiles = load_page_profiles(pdf_path)
    metadata = extract_metadata(pdf_path, profiles)
    metadata["company"] = company
    metadata["ocr_provider_status"] = args.ocr_provider
    metadata["ocr_language"] = args.ocr_language
    metadata["llm_fallback_status"] = "placeholder_not_used"

    candidates = locate_statement_candidates(profiles, max_continuation_pages=args.max_continuation_pages)
    ocr_provider = None
    if args.ocr_provider == "mineru":
        ocr_provider = MinerUOCRProvider(
            debug_dir,
            mode=args.mineru_mode,
            language=args.ocr_language,
            dpi=args.render_dpi,
        )
        metadata["mineru_mode"] = args.mineru_mode
        metadata["render_dpi"] = str(args.render_dpi)
    results = merge_comprehensive_income(extract_candidate_tables(pdf_path, candidates, ocr_provider=ocr_provider))

    output_path = excel_dir / f"{company}_{_safe_name(pdf_path.stem)}_statements.xlsx"
    output_path = write_with_available_name(output_path, metadata, profiles, candidates, results)

    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (debug_dir / "candidates.json").write_text(
        json.dumps([candidate.to_dict() for candidate in candidates], indent=2),
        encoding="utf-8",
    )
    if args.debug:
        extract_page_text_debug(pdf_path, debug_dir / "page_text")

    logger.info("PDF: {}", pdf_path)
    logger.info("Pages: {}", len(profiles))
    logger.info("Candidates: {}", len(candidates))
    logger.info("Excel: {}", output_path)
    logger.info("Debug: {}", debug_dir)
    return 0


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
