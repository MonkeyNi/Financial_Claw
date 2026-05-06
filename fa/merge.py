from __future__ import annotations


GREY_BAND_FUZZ: tuple[float, float] = (
    0.6,
    0.9,
)


def union_rows(rows: dict[str, dict[str, float]], periods: list[str]) -> dict[str, dict[str, float | None]]:
    """Expand each row to all ``periods``; missing periods become ``None``."""
    return {item: {p: values.get(p) for p in periods} for item, values in rows.items()}
