from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RuntimeConfig:
    tolerance: float = 0.5
    llm_table_repair: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RuntimeConfig":
        tolerance = float(env.get("FA_TOLERANCE", cls.tolerance))
        llm_table_repair = env.get("FA_LLM_TABLE_REPAIR", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(tolerance=tolerance, llm_table_repair=llm_table_repair)
