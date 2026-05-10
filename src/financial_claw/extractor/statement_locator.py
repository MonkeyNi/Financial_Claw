from __future__ import annotations

import json
from pathlib import Path
import re

from .models import PageProfile, StatementCandidate


TITLE_PATTERNS: dict[str, list[re.Pattern]] = {
    "balance_sheet": [
        re.compile(r"\bconsolidated\s+statements?\s+of\s+financial\s+position\b", re.I),
        re.compile(r"\bconsolidated\s+balance\s+sheets?\b", re.I),
    ],
    "income_statement": [
        re.compile(r"\bconsolidated\s+income\s+statements?\b", re.I),
        re.compile(r"\bconsolidated\s+statements?\s+of\s+(?:profit\s+or\s+loss|operations|earnings)\b", re.I),
        re.compile(r"\bconsolidated\s+statements?\s+of\s+comprehensive\s+income(?:\s+(?:or\s+loss|\(?loss\)?))?(?=$|\s|[,:;-])", re.I),
    ],
    "cash_flow": [
        re.compile(r"\bconsolidated\s+cash\s+flow\s+statements?\b", re.I),
        re.compile(r"\bconsolidated\s+statements?\s+of\s+cash\s+flows?\b", re.I),
    ],
}

NON_TARGET_MAIN_TITLES = [
    re.compile(r"\bconsolidated\s+statements?\s+of\s+changes\s+in\s+equity\b", re.I),
]
TARGET_STATEMENT_TYPES = {"balance_sheet", "income_statement", "cash_flow"}
LOCATOR_CONFIG_NAME = "locator_config.json"
STATEMENT_SET_MAX_GAP_PAGES = 12
SUPPLEMENTARY_SECTION_RE = re.compile(
    r"\b(?:appendix|appendices|supplementary|additional financial information|"
    r"parent entity|company financial statements|statutory financial statements|"
    r"trust financial statements)\b|附件|附录",
    re.I,
)


def _first_lines(text: str, n: int = 8) -> str:
    text = _normalize_text(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[:n])


def _head_lines(text: str, n: int = 18) -> list[str]:
    text = _normalize_text(text)
    return [line.strip() for line in text.splitlines() if line.strip()][:n]


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u2019", "'")
    return "\n".join(re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines())


def _is_notes_page(text: str) -> bool:
    lines = [line.strip().lower() for line in _normalize_text(text).splitlines() if line.strip()]
    for line in lines[:8]:
        if line.startswith(
            (
                "notes to the consolidated financial statements",
                "notes to the interim condensed consolidated financial statements",
            )
        ):
            return True
    return False


def _is_reference_page(text: str) -> bool:
    head = _first_lines(text, 10).lower()
    if "contents" in head or "index to consolidated financial statements" in head:
        return True
    if "independent auditor" in head or "independent auditors" in head or "basis for opinions" in head or "report on review" in head:
        return True
    if "responsibilities of management" in head or "internal control over financial reporting" in head:
        return True
    return False


def _has_non_target_title(text: str) -> bool:
    head = _first_lines(text, 8)
    return any(pattern.search(head) for pattern in NON_TARGET_MAIN_TITLES) or _looks_like_equity_statement_table(
        re.sub(r"\s+", " ", _normalize_text(text).lower())
    )


def _best_statement_hit(text: str) -> tuple[str | None, str | None, float, str]:
    if _has_non_target_title(text):
        return None, None, 0.0, "non-target consolidated statement title"
    if _is_reference_page(text):
        return None, None, 0.0, "reference page"

    best: tuple[str | None, str | None, float, str] = (None, None, 0.0, "")
    head_lines = _head_lines(text, 18)
    for statement_type, patterns in TITLE_PATTERNS.items():
        for pattern in patterns:
            for line in head_lines:
                head_match = pattern.search(line)
                if not head_match or not _is_standalone_statement_heading(line, head_match.group(0)):
                    continue
                score = 0.85
                reason = "title_match_in_page_head"
                if _is_notes_page(text):
                    score -= 0.35
                    reason += ";notes_page_penalty"
                title = head_match.group(0)
                if score > best[2]:
                    best = (statement_type, title, score, reason)
    inferred = None if _is_notes_page(text) else _infer_statement_from_table_text(text)
    if inferred and inferred[2] > best[2]:
        return inferred
    return best


def _best_configured_statement_hit(
    text: str,
    locator_config: dict | None,
) -> tuple[str | None, str | None, float, str]:
    if not locator_config or _has_non_target_title(text) or _is_reference_page(text):
        return None, None, 0.0, ""
    keywords_by_type = locator_config.get("statement_keywords")
    if not isinstance(keywords_by_type, dict):
        return None, None, 0.0, ""

    best: tuple[str | None, str | None, float, str] = (None, None, 0.0, "")
    head_lines = _head_lines(text, 18)
    for statement_type in TARGET_STATEMENT_TYPES:
        keywords = keywords_by_type.get(statement_type, [])
        if not isinstance(keywords, list):
            continue
        for keyword in keywords:
            if not isinstance(keyword, str) or not keyword.strip():
                continue
            normalized_keyword = re.sub(r"\s+", " ", keyword.strip().lower())
            for line in head_lines:
                normalized_line = re.sub(r"\s+", " ", line.strip().lower())
                if normalized_keyword not in normalized_line:
                    continue
                if not _is_standalone_statement_heading(line, keyword):
                    continue
                score = 0.92
                reason = "company_locator_config"
                if _is_notes_page(text):
                    score -= 0.35
                    reason += ";notes_page_penalty"
                if score > best[2]:
                    best = (statement_type, keyword, score, reason)
    return best


def _is_standalone_statement_heading(line: str, title: str) -> bool:
    normalized_line = re.sub(r"\s+", " ", line.strip().lower())
    normalized_title = re.sub(r"\s+", " ", title.strip().lower())
    if normalized_line == normalized_title:
        return True
    prefixed_title = re.fullmatch(
        rf"(?:interim\s+)?(?:condensed\s+)?{re.escape(normalized_title)}(?:\s*,?\s*continued)?",
        normalized_line,
    )
    if prefixed_title:
        return True
    suffix = normalized_line.removeprefix(normalized_title).strip(" :-–—")
    if not suffix:
        return True
    return bool(
        re.fullmatch(
            r"(?:as at|as of|for the year ended|for the years ended|for the period ended|for the periods ended).+",
            suffix,
        )
    )


def _infer_statement_from_table_text(text: str) -> tuple[str | None, str | None, float, str] | None:
    normalized = re.sub(r"\s+", " ", _normalize_text(text).lower())
    if not normalized:
        return None
    if _looks_like_balance_sheet_table(normalized):
        return ("balance_sheet", "Consolidated statements of financial position", 0.72, "table_structure_inference")
    if _looks_like_income_statement_table(normalized):
        return ("income_statement", "Consolidated income statements", 0.72, "table_structure_inference")
    if _looks_like_cash_flow_table(normalized):
        return ("cash_flow", "Consolidated cash flow statements", 0.72, "table_structure_inference")
    return None


def _looks_like_balance_sheet_table(text: str) -> bool:
    required = ("current assets", "total assets", "current liabilities", "total liabilities")
    if not all(term in text for term in required):
        return False
    return "equity" in text or "net assets" in text


def _looks_like_income_statement_table(text: str) -> bool:
    if "revenue" not in text:
        return False
    outcome_terms = ("profit for the year", "profit for the period", "loss for the year", "loss for the period")
    expense_terms = ("expenses", "property expenses", "development expenses", "income tax")
    return any(term in text for term in outcome_terms) and any(term in text for term in expense_terms)


def _looks_like_cash_flow_table(text: str) -> bool:
    if "cash flows from operating activities" not in text:
        return False
    activity_terms = ("cash flows from investing activities", "cash flows from financing activities", "net cash")
    return any(term in text for term in activity_terms)


def _looks_like_equity_statement_table(text: str) -> bool:
    if "balance at 1 july" not in text and "balance at the beginning" not in text:
        return False
    equity_terms = ("issued capital", "retained earnings", "total reserves")
    attribution_terms = ("attributable to securityholders", "attributable to unitholders", "attributable to owners")
    return any(term in text for term in equity_terms) and any(term in text for term in attribution_terms)


def locate_statement_candidates(
    profiles: list[PageProfile],
    max_continuation_pages: int = 3,
    locator_config: dict | None = None,
) -> list[StatementCandidate]:
    starts: list[StatementCandidate] = []
    for profile in profiles:
        statement_type, title, score, reason = _best_configured_statement_hit(profile.text, locator_config)
        if not statement_type:
            statement_type, title, score, reason = _best_statement_hit(profile.text)
        if statement_type and title and score >= 0.55:
            starts.append(
                StatementCandidate(
                    statement_type=statement_type,
                    page_start=profile.page_number,
                    page_end=profile.page_number,
                    title=title,
                    score=round(score, 3),
                    reason=reason,
                    source_pages=[profile.page_number],
                )
            )

    start_pages = {candidate.page_start for candidate in starts}
    for candidate in starts:
        end_page = candidate.page_start
        for next_page in range(candidate.page_start + 1, min(candidate.page_start + max_continuation_pages, len(profiles)) + 1):
            text = profiles[next_page - 1].text
            if next_page in start_pages:
                break
            if _is_notes_page(text) or _has_non_target_title(text):
                break
            if _looks_like_continuation(text, candidate.statement_type):
                end_page = next_page
            else:
                break
        candidate.page_end = end_page
        candidate.source_pages = list(range(candidate.page_start, candidate.page_end + 1))
    merged = _merge_adjacent_same_statement(starts)
    return _filter_duplicate_statement_sets(merged, profiles)


def load_company_locator_config(pdf_path: Path) -> dict | None:
    config_path = _company_locator_config_path(pdf_path)
    if not config_path or not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _company_locator_config_path(pdf_path: Path) -> Path | None:
    parts = list(pdf_path.resolve().parts)
    lowered = [part.lower() for part in parts]
    if "companies" not in lowered:
        return None
    companies_idx = lowered.index("companies")
    if companies_idx + 1 >= len(parts):
        return None
    return Path(*parts[: companies_idx + 2]) / LOCATOR_CONFIG_NAME


def _merge_adjacent_same_statement(candidates: list[StatementCandidate]) -> list[StatementCandidate]:
    merged: list[StatementCandidate] = []
    for candidate in sorted(candidates, key=lambda c: (c.page_start, c.statement_type)):
        if (
            merged
            and candidate.statement_type == merged[-1].statement_type
            and candidate.page_start <= merged[-1].page_end + 1
        ):
            merged[-1].page_end = max(merged[-1].page_end, candidate.page_end)
            merged[-1].source_pages = list(range(merged[-1].page_start, merged[-1].page_end + 1))
            merged[-1].reason += ";merged_adjacent_continuation"
            merged[-1].score = max(merged[-1].score, candidate.score)
            continue
        merged.append(candidate)
    return merged


def _filter_duplicate_statement_sets(
    candidates: list[StatementCandidate],
    profiles: list[PageProfile],
) -> list[StatementCandidate]:
    groups = _group_statement_sets(candidates)
    complete_groups = [group for group in groups if _is_complete_statement_set(group)]
    if not complete_groups:
        return candidates

    main_group = max(complete_groups, key=lambda group: _statement_set_score(group, profiles))
    main_start = min(candidate.page_start for candidate in main_group)
    keep_ids = {
        id(candidate)
        for group in groups
        if group is main_group or (not _is_complete_statement_set(group) and max(candidate.page_end for candidate in group) < main_start)
        for candidate in group
    }
    return [candidate for candidate in candidates if id(candidate) in keep_ids]


def _group_statement_sets(candidates: list[StatementCandidate]) -> list[list[StatementCandidate]]:
    groups: list[list[StatementCandidate]] = []
    for candidate in sorted(candidates, key=lambda item: item.page_start):
        if not groups:
            groups.append([candidate])
            continue
        previous = groups[-1][-1]
        if candidate.page_start - previous.page_end <= STATEMENT_SET_MAX_GAP_PAGES:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    return groups


def _is_complete_statement_set(group: list[StatementCandidate]) -> bool:
    return TARGET_STATEMENT_TYPES.issubset({candidate.statement_type for candidate in group})


def _statement_set_score(group: list[StatementCandidate], profiles: list[PageProfile]) -> float:
    statement_types = {candidate.statement_type for candidate in group}
    score = len(statement_types & TARGET_STATEMENT_TYPES) * 100.0
    score += sum(candidate.score for candidate in group)
    score -= min(candidate.page_start for candidate in group) * 0.01
    if _has_supplementary_context(group, profiles):
        score -= 200.0
    return score


def _has_supplementary_context(group: list[StatementCandidate], profiles: list[PageProfile]) -> bool:
    start_page = max(1, min(candidate.page_start for candidate in group) - 5)
    end_page = min(len(profiles), max(candidate.page_end for candidate in group))
    context = "\n".join(profile.text for profile in profiles[start_page - 1 : end_page])
    return bool(SUPPLEMENTARY_SECTION_RE.search(context))


def _looks_like_continuation(text: str, statement_type: str) -> bool:
    lower = text.lower()
    numeric_tokens = len(re.findall(r"(?:\(?-?\d[\d,]*\.?\d*\)?)", text))
    if numeric_tokens < 12:
        return False
    if _looks_like_equity_statement_table(re.sub(r"\s+", " ", _normalize_text(text).lower())):
        return False
    if statement_type == "balance_sheet":
        return any(
            term in lower
            for term in (
                "total assets",
                "total liabilities",
                "current assets",
                "non-current assets",
                "current liabilities",
                "non-current liabilities",
                "total equity",
            )
        )
    if statement_type == "income_statement":
        return any(
            term in lower
            for term in (
                "profit for the",
                "loss for the",
                "income tax",
                "total comprehensive income",
                "earnings per",
            )
        )
    if statement_type == "cash_flow":
        return any(term in lower for term in ("cash flows from", "net cash", "cash and cash equivalents"))
    return False
