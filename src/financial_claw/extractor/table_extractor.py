from __future__ import annotations

from pathlib import Path
import re
from time import perf_counter

from loguru import logger

from .pymupdf_compat import fitz

from .models import ExtractionResult, StatementCandidate
from .pdf_profile import page_lines_from_words
from .providers import MinerUOCRProvider


NUMBER_RE = re.compile(r"^\(?-?\$?\d[\d,]*(?:\.\d+)?\)?$|^-$")


def extract_candidate_tables(
    pdf_path: Path,
    candidates: list[StatementCandidate],
    ocr_provider: MinerUOCRProvider | None = None,
) -> list[ExtractionResult]:
    start = perf_counter()
    logger.info("Opening PDF for table extraction: {}", pdf_path)
    doc = fitz.open(pdf_path)
    page_rows_by_number: dict[int, list[list[str]]] = {}
    low_density_pages: set[int] = set()
    candidate_pages = sorted({page for candidate in candidates for page in candidate.source_pages})
    logger.info("Extracting embedded-text rows from {} candidate page(s): {}", len(candidate_pages), candidate_pages)
    for candidate in candidates:
        for page_number in candidate.source_pages:
            if page_number in page_rows_by_number:
                continue
            page_start = perf_counter()
            page_rows = extract_page_rows(doc.load_page(page_number - 1))
            page_rows_by_number[page_number] = page_rows
            numeric_cells = _count_numeric_cells(page_rows)
            logger.info(
                "Embedded extraction page={} rows={} numeric_cells={} elapsed={:.2f}s",
                page_number,
                len(page_rows),
                numeric_cells,
                perf_counter() - page_start,
            )
            if ocr_provider is not None and numeric_cells < 4:
                low_density_pages.add(page_number)

    if ocr_provider is not None:
        if low_density_pages:
            logger.info("Low-density page(s) requiring OCR fallback: {}", sorted(low_density_pages))
        else:
            logger.info("No pages require OCR fallback.")

    ocr_start = perf_counter()
    ocr_results = (
        ocr_provider.extract_pages_tables(pdf_path, sorted(low_density_pages))
        if ocr_provider is not None and low_density_pages
        else {}
    )
    if ocr_results:
        logger.info("OCR fallback returned {} page result(s) in {:.2f}s", len(ocr_results), perf_counter() - ocr_start)

    results: list[ExtractionResult] = []
    for candidate in candidates:
        rows: list[list[str]] = []
        warnings: list[str] = []
        for page_number in candidate.source_pages:
            page_rows = page_rows_by_number[page_number]
            if page_number in ocr_results:
                ocr_result = ocr_results[page_number]
                if ocr_result.rows:
                    page_rows = ocr_result.rows
                    candidate.extraction_method = "mineru_ocr_fallback"
                warnings.extend(ocr_result.warnings)
            if rows:
                page_rows = _drop_repeated_leading_header(page_rows)
                rows.append([])
                rows.append(["continue"])
            rows.extend(page_rows)
        rows = _remove_non_table_rows(rows)
        numeric_cells = _count_numeric_cells(rows)
        if not rows:
            warnings.append("No rows extracted from embedded text; OCR fallback likely required.")
        elif numeric_cells < 4:
            warnings.append("Low numeric/table density from embedded text; OCR fallback likely required.")
        results.append(ExtractionResult(candidate=candidate, rows=rows, warnings=warnings))
        logger.info(
            "Candidate table complete: type={} pages={}..{} rows={} numeric_cells={} warnings={}",
            candidate.statement_type,
            candidate.page_start,
            candidate.page_end,
            len(rows),
            numeric_cells,
            len(warnings),
        )
    logger.info("Table extraction complete in {:.2f}s", perf_counter() - start)
    return results


def _count_numeric_cells(rows: list[list[str]]) -> int:
    return sum(1 for row in rows for cell in row if cell and NUMBER_RE.match(str(cell).replace(",", "")))


def _drop_repeated_leading_header(rows: list[list[str]]) -> list[list[str]]:
    trimmed = list(rows)
    while trimmed and _is_repeated_header_row(trimmed[0]):
        trimmed.pop(0)
    return trimmed


def _remove_non_table_rows(rows: list[list[str]]) -> list[list[str]]:
    return [row for row in rows if not _is_non_table_row(row)]


def _is_non_table_row(row: list[str]) -> bool:
    text = " ".join(str(cell) for cell in row if cell).strip().lower()
    if not text:
        return False
    if _is_page_number_text(text):
        return True
    non_table_terms = [
        "the accompanying notes are an integral part",
        "are an integral part of the consolidated financial statements",
        "are an integral part of the interim condensed consolidated financial",
        "are to be read in conjunction with the accompanying notes",
        "to be read in conjunction with the accompanying notes",
        "form part of these consolidated financial statements",
        "approved and authorised for issue by the board of directors",
        "approved and authorized for issue by the board of directors",
        "statements.",
    ]
    return any(term in text for term in non_table_terms)


def _is_repeated_header_row(row: list[str]) -> bool:
    text = " ".join(str(cell) for cell in row if cell).strip().lower()
    if not text:
        return True
    if _is_statement_title_text(text) or _is_unit_context_text(text):
        return True
    if _is_continuation_column_header_row(row):
        return True
    repeated_terms = [
        "consolidated statement",
        "consolidated statements",
        "interim condensed consolidated",
        "for each of the",
        "for the three-month",
        "for the year ended",
        "as of ",
        "as at ",
        "in millions of",
        "except per share",
        "the accompanying notes",
        "march 31",
        "december 31",
        "unaudited",
        "notes",
    ]
    if any(term in text for term in repeated_terms):
        return True
    return False


def _is_continuation_column_header_row(row: list[str]) -> bool:
    non_empty = [str(cell).strip() for cell in row if str(cell).strip()]
    if not non_empty:
        return True
    text = " ".join(non_empty).lower()
    if _is_unit_context_text(text):
        return True
    if all(_is_structural_header_cell(cell) for cell in non_empty):
        return True
    if _looks_like_entity_column_header(non_empty):
        return True
    return False


def _looks_like_entity_column_header(cells: list[str]) -> bool:
    if len(cells) > 6:
        return False
    if any(_is_amount_token(cell) or re.fullmatch(r"\d{4}", cell.strip()) for cell in cells):
        return False
    if any(_is_structural_header_cell(cell) for cell in cells):
        return False
    return all(re.search(r"[A-Za-z]", cell) and len(cell.split()) <= 3 for cell in cells)


def extract_page_rows(page: fitz.Page) -> list[list[str]]:
    lines = page_lines_from_words(page)
    table_lines = [line for line in lines if _line_in_body(line, page) and _line_is_financial_table_like(line, page)]
    if not table_lines:
        table_lines = [line for line in lines if _line_in_body(line, page)]
    anchors = _infer_numeric_anchors(table_lines)
    rows: list[list[str]] = []
    for line in table_lines:
        row = _line_to_cells(line, anchors)
        if any(cell.strip() for cell in row):
            rows.append(row)
    rows = _merge_leading_label_fragments(rows)
    return _merge_label_continuation_rows(_merge_multiline_headers(rows))


def _line_in_body(line: list[tuple], page: fitz.Page) -> bool:
    y = min(float(w[1]) for w in line)
    return 45 <= y <= float(page.rect.height) - 30


def _is_top_table_header_text(line: list[tuple], page: fitz.Page) -> bool:
    y = min(float(w[1]) for w in line)
    if y > min(180.0, float(page.rect.height) * 0.25):
        return False
    words = [str(w[4]).strip() for w in line if str(w[4]).strip()]
    if not 1 <= len(words) <= 6:
        return False
    text = " ".join(words)
    low = text.lower()
    if any(NUMBER_RE.match(word.replace(",", "")) for word in words):
        return False
    if any(term in low for term in ("annual report", "auditor", "director", "chairman")):
        return False
    if _is_non_table_row([text]):
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _line_is_financial_table_like(line: list[tuple], page: fitz.Page) -> bool:
    words = [str(w[4]) for w in line]
    text = " ".join(words)
    if _is_section_label_text(text):
        return True
    if _is_top_table_header_text(line, page):
        return True
    if len(words) <= 1:
        return False
    if any(NUMBER_RE.match(word.replace(",", "")) for word in words):
        return True
    low = text.lower()
    if _is_unit_context_text(low):
        return True
    return any(
        token in low
        for token in [
            "assets",
            "liabilities",
            "revenue",
            "cash flows",
            "profit",
            "income",
            "borrowings",
            "payable",
            "receivable",
            "equity",
            "financial position",
            "$m",
            "note",
        ]
    )


def _infer_numeric_anchors(lines: list[list[tuple]]) -> list[float]:
    xs: list[float] = []
    for line in lines:
        if _is_title_or_date_line(line):
            continue
        if not _line_has_financial_number(line):
            continue
        for word in line:
            token = str(word[4]).strip()
            if _is_column_anchor_token(token):
                xs.append((float(word[0]) + float(word[2])) / 2)
    if not xs:
        return []
    return _cluster_x_positions(xs, tolerance=24.0, min_count=2, max_columns=8)


def _is_title_or_date_line(line: list[tuple]) -> bool:
    text = " ".join(str(w[4]) for w in line).lower()
    title_terms = [
        "as of",
        "as at",
        "for each",
        "for the year",
        "for the period",
        "consolidated statements",
        "consolidated statement",
        "interim condensed",
        "unaudited",
    ]
    months = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    return any(term in text for term in title_terms) or any(month in text for month in months)


def _line_has_financial_number(line: list[tuple]) -> bool:
    for word in line:
        token = str(word[4]).strip()
        if _is_amount_token(token):
            return True
    return False


def _is_column_anchor_token(token: str) -> bool:
    low = token.lower()
    return _is_amount_token(token) or low in {"note", "notes", "$m", "$000"}


def _is_amount_token(token: str) -> bool:
    cleaned = _normalize_number_token(token)
    if cleaned in {"-", "–"}:
        return True
    if re.fullmatch(r"\(?-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\)?", cleaned):
        return True
    return False


def _normalize_number_token(token: str) -> str:
    cleaned = token.strip().replace("$", "").replace("￦", "").replace("¥", "").strip()
    if cleaned.startswith("W "):
        cleaned = cleaned[2:].strip()
    if cleaned.endswith(" W"):
        cleaned = cleaned[:-2].strip()
    return cleaned


def _cluster_x_positions(xs: list[float], tolerance: float, min_count: int, max_columns: int) -> list[float]:
    clusters: list[list[float]] = []
    for x in sorted(xs):
        if not clusters or abs(x - _mean(clusters[-1])) > tolerance:
            clusters.append([x])
        else:
            clusters[-1].append(x)

    kept = [cluster for cluster in clusters if len(cluster) >= min_count]
    if len(kept) > max_columns:
        kept = sorted(kept, key=len, reverse=True)[:max_columns]
    return sorted(_mean(cluster) for cluster in kept)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _line_to_cells(line: list[tuple], anchors: list[float]) -> list[str]:
    words = sorted(line, key=lambda w: w[0])
    text = " ".join(str(w[4]) for w in words)
    if _is_unit_context_text(text) or _is_statement_title_text(text):
        return [text]
    if not anchors:
        return [" ".join(str(w[4]) for w in words)]
    cells = [[] for _ in range(len(anchors) + 1)]
    boundaries = [(anchors[i] + anchors[i + 1]) / 2 for i in range(len(anchors) - 1)]
    first_boundary = anchors[0] - 30
    for word in words:
        x_mid = (float(word[0]) + float(word[2])) / 2
        token = str(word[4])
        if _is_standalone_currency_marker(token):
            continue
        if x_mid < first_boundary:
            idx = 0
        else:
            idx = 1 + sum(x_mid > boundary for boundary in boundaries)
        idx = max(0, min(idx, len(cells) - 1))
        cells[idx].append(token)
    return [" ".join(cell).strip() for cell in cells]


def _merge_leading_label_fragments(rows: list[list[str]]) -> list[list[str]]:
    merged_rows: list[list[str]] = []
    for row in rows:
        merged_rows.append(_merge_leading_label_fragment(row))
    return merged_rows


def _merge_leading_label_fragment(row: list[str]) -> list[str]:
    if len(row) < 3 or not row[0] or not row[1]:
        return row
    fragment = str(row[1]).strip()
    if not fragment or _should_keep_as_structured_column(fragment):
        return row
    new_row = row[:]
    new_row[0] = f"{new_row[0]} {fragment}".strip()
    new_row[1] = ""
    return new_row


def _should_keep_as_structured_column(text: str) -> bool:
    normalized = text.strip()
    structural = _strip_currency_markers(normalized).strip()
    low = normalized.lower()
    if not normalized:
        return True
    if low in {"note", "notes"}:
        return True
    if re.fullmatch(r"\d{4}", normalized):
        return True
    if _is_amount_token(normalized):
        return True
    if re.fullmatch(r"\d+(?:\s*,\s*\d+)*", structural):
        return True
    return False


def _strip_currency_markers(text: str) -> str:
    return (
        text.replace("￦", "")
        .replace("¥", "")
        .replace("$", "")
        .replace("HK$", "")
        .replace("US$", "")
    )


def _is_standalone_currency_marker(token: str) -> bool:
    return token in {"W", "$", "HK$", "US$"}


def _merge_multiline_headers(rows: list[list[str]]) -> list[list[str]]:
    if len(rows) < 4:
        return rows
    first_data_idx = _find_first_data_row(rows)
    if first_data_idx <= 1:
        return rows

    prefix = rows[:first_data_idx]
    merged_header = _merge_header_band(prefix)
    if not merged_header:
        return rows
    return merged_header + rows[first_data_idx:]


def _find_first_data_row(rows: list[list[str]]) -> int:
    for idx, row in enumerate(rows):
        label = (row[0] if row else "").lower()
        numeric_cells = sum(1 for cell in row[1:] if cell and _is_amount_token(str(cell)))
        if numeric_cells >= 2 and not _looks_like_header_label(label):
            return idx
    return min(len(rows), 3)


def _looks_like_header_label(label: str) -> bool:
    header_terms = [
        "for the year",
        "for each",
        "as at",
        "as of",
        "expressed in",
        "korean won in millions",
        "won in millions",
        "in millions",
        "in thousands",
        "consolidated",
        "interim condensed",
    ]
    return any(term in label for term in header_terms)


def _merge_header_band(rows: list[list[str]]) -> list[list[str]]:
    leading_rows: list[list[str]] = []
    column_rows: list[list[str]] = []
    section_rows: list[list[str]] = []
    for row in rows:
        non_empty = [(idx, cell) for idx, cell in enumerate(row) if cell]
        if not non_empty:
            continue
        if _row_is_statement_context(row):
            leading_rows.append([" ".join(str(cell) for _, cell in non_empty)])
        elif _is_section_label_row(row):
            section_rows.append(row)
        elif len(non_empty) == 1 and non_empty[0][0] == 0:
            leading_rows.append(row)
        elif any(idx > 0 for idx, _ in non_empty):
            column_rows.append(row)
        else:
            leading_rows.append(row)

    if not column_rows:
        return leading_rows + section_rows
    if any(_column_row_has_entity_label(row) for row in column_rows):
        return leading_rows + column_rows + section_rows

    width = max(len(row) for row in column_rows)
    merged = [""] * width
    for row in column_rows:
        padded = row + [""] * (width - len(row))
        for idx, cell in enumerate(padded):
            if not cell:
                continue
            merged[idx] = f"{merged[idx]}\n{cell}" if merged[idx] else cell
    return leading_rows + [merged] + section_rows


def _row_is_statement_context(row: list[str]) -> bool:
    text = " ".join(str(cell) for cell in row if cell).lower()
    return text.startswith(("as of ", "as at ", "for each ", "for the year ", "for the period "))


def _column_row_has_entity_label(row: list[str]) -> bool:
    for idx, cell in enumerate(row):
        text = str(cell or "").strip()
        if idx == 0 or not text:
            continue
        if _is_structural_header_cell(text):
            continue
        if re.search(r"[A-Za-z]", text):
            return True
    return False


def _is_structural_header_cell(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in {"note", "notes", "$m", "$000", "$", "m"}:
        return True
    if re.fullmatch(r"\d{4}", normalized):
        return True
    if re.fullmatch(r"(?:19|20)\d{2}\s*[\n ]+\$?m", normalized):
        return True
    return False


def _is_section_label_row(row: list[str]) -> bool:
    non_empty = [str(cell).strip() for cell in row if cell]
    return len(non_empty) == 1 and _is_section_label_text(non_empty[0])


def _is_section_label_text(text: str) -> bool:
    normalized = text.strip().lower()
    section_labels = {
        "assets",
        "current assets",
        "non-current assets",
        "liabilities",
        "current liabilities",
        "non-current liabilities",
        "equity",
        "revenue",
        "cash flows from operating activities",
        "cash flows from investing activities",
        "cash flows from financing activities",
    }
    return normalized in section_labels


def _merge_label_continuation_rows(rows: list[list[str]]) -> list[list[str]]:
    merged: list[list[str]] = []
    idx = 0
    while idx < len(rows):
        row = rows[idx]
        if idx + 1 < len(rows) and _is_label_only_continuation(row) and _row_has_numeric_amount(rows[idx + 1]):
            next_row = rows[idx + 1][:]
            next_row[0] = f"{row[0]} {next_row[0]}".strip()
            merged.append(next_row)
            idx += 2
            continue
        merged.append(row)
        idx += 1
    return merged


def _is_label_only_continuation(row: list[str]) -> bool:
    non_empty = [cell for cell in row if cell]
    if len(non_empty) != 1 or not row or not row[0]:
        return False
    label = row[0].strip().lower()
    if _is_unit_context_text(label):
        return False
    if label.endswith(":"):
        return False
    section_labels = {
        "assets",
        "current assets",
        "non-current assets",
        "liabilities",
        "current liabilities",
        "non-current liabilities",
        "equity",
        "revenue",
        "cash flows from operating activities",
        "cash flows from investing activities",
        "cash flows from financing activities",
    }
    return label not in section_labels and len(label.split()) >= 3


def _row_has_numeric_amount(row: list[str]) -> bool:
    return any(cell and _is_amount_token(str(cell)) for cell in row[1:])


def _is_page_number_text(text: str) -> bool:
    normalized = text.strip().replace("–", "-").replace("—", "-")
    return bool(re.fullmatch(r"-\s*\d+\s*-", normalized))


def _is_unit_context_text(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.search(
            r"\((?:korean\s+)?won\s+in\s+(?:millions|thousands)\)",
            normalized,
        )
        or re.search(r"\((?:us\s+)?dollars?\s+in\s+(?:millions|thousands)\)", normalized)
        or re.search(r"\bin\s+(?:millions|thousands)\b", normalized)
    )


def _is_statement_title_text(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.search(
            r"\bconsolidated\s+statements?\s+of\s+"
            r"(?:financial\s+position|comprehensive\s+income|cash\s+flows?|profit\s+or\s+loss)",
            normalized,
        )
        or re.search(r"\bconsolidated\s+(?:income|cash\s+flow)\s+statements?\b", normalized)
    )
