from __future__ import annotations


def conflict_column_name(period: str, report_name: str) -> str:
    return f"{period} Conflict - {report_name}"
