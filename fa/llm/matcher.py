from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchDecision:
    equivalent: bool
    score: float
    reason: str
