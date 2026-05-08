from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageProfile:
    page_number: int
    text: str
    line_count: int
    word_count: int
    has_embedded_text: bool
    width: float
    height: float


@dataclass
class StatementCandidate:
    statement_type: str
    page_start: int
    page_end: int
    title: str
    score: float
    reason: str
    extraction_method: str = "embedded_text_coordinates"
    source_pages: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "statement_type": self.statement_type,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "title": self.title,
            "score": self.score,
            "reason": self.reason,
            "extraction_method": self.extraction_method,
            "source_pages": ",".join(str(p) for p in self.source_pages),
        }


@dataclass
class ExtractionResult:
    candidate: StatementCandidate
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)


@dataclass
class RunConfig:
    pdf_path: Path
    company: str
    output_dir: Path
    debug_dir: Path
    max_continuation_pages: int = 3
