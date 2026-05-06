from __future__ import annotations


def maybe_repair_table(
    table: dict,
    enable_llm: bool,
    threshold: float,
    repair_fn,
) -> dict:
    """Optionally elevate low-confidence extracts through ``repair_fn``."""
    if not enable_llm:
        return table
    confidence = float(table.get("confidence", 1.0))
    if confidence >= threshold:
        return table
    return repair_fn(table)
