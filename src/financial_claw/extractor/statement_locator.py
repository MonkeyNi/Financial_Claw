from __future__ import annotations

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
        re.compile(r"\bconsolidated\s+statements?\s+of\s+comprehensive\s+income\b", re.I),
    ],
    "cash_flow": [
        re.compile(r"\bconsolidated\s+cash\s+flow\s+statements?\b", re.I),
        re.compile(r"\bconsolidated\s+statements?\s+of\s+cash\s+flows?\b", re.I),
    ],
}

NON_TARGET_MAIN_TITLES = [
    re.compile(r"\bconsolidated\s+statements?\s+of\s+changes\s+in\s+equity\b", re.I),
]


def _first_lines(text: str, n: int = 8) -> str:
    text = _normalize_text(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[:n])


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
    return any(pattern.search(head) for pattern in NON_TARGET_MAIN_TITLES)


def _best_statement_hit(text: str) -> tuple[str | None, str | None, float, str]:
    head = _first_lines(text, 10)
    if _has_non_target_title(text):
        return None, None, 0.0, "non-target consolidated statement title"
    if _is_reference_page(text):
        return None, None, 0.0, "reference page"

    best: tuple[str | None, str | None, float, str] = (None, None, 0.0, "")
    for statement_type, patterns in TITLE_PATTERNS.items():
        for pattern in patterns:
            head_match = pattern.search(head)
            if not head_match:
                continue
            score = 0.85
            reason = "title_match_in_page_head"
            if _is_notes_page(text):
                score -= 0.35
                reason += ";notes_page_penalty"
            title = head_match.group(0)
            if score > best[2]:
                best = (statement_type, title, score, reason)
    return best


def locate_statement_candidates(
    profiles: list[PageProfile],
    max_continuation_pages: int = 3,
) -> list[StatementCandidate]:
    starts: list[StatementCandidate] = []
    for profile in profiles:
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
            if _looks_like_continuation(text):
                end_page = next_page
            else:
                break
        candidate.page_end = end_page
        candidate.source_pages = list(range(candidate.page_start, candidate.page_end + 1))
    return _merge_adjacent_same_statement(starts)


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


def _looks_like_continuation(text: str) -> bool:
    lower = text.lower()
    finance_terms = [
        "total assets",
        "total liabilities",
        "cash flows from",
        "profit for the",
        "income tax",
        "net cash",
        "current assets",
        "non-current assets",
        "retained earnings",
    ]
    numeric_tokens = len(re.findall(r"(?:\(?-?\d[\d,]*\.?\d*\)?)", text))
    return numeric_tokens >= 12 and any(term in lower for term in finance_terms)
