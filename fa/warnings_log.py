from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class WarningRecord:
    severity: str
    issue_type: str
    message: str
    timestamp: str


@dataclass
class WarningCollector:
    records: list[WarningRecord] = field(default_factory=list)

    def add(self, *, severity: str, issue_type: str, message: str) -> None:
        ts = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        self.records.append(
            WarningRecord(
                severity=severity,
                issue_type=issue_type,
                message=message,
                timestamp=ts,
            )
        )
