from __future__ import annotations


def within_tolerance(reported: float, calculated: float, tolerance: float) -> bool:
    return abs(reported - calculated) <= tolerance
