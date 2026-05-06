from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportFile:
    company: str
    pdf_path: str
    file_name: str
    sha256: str
    mtime: float

    def __post_init__(self) -> None:
        if len(self.sha256) != 64:
            raise ValueError("sha256 must be 64 characters")
