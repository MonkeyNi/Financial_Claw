from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RuntimeConfig:
    validation_tolerance_millions: float = 0.5
    enable_llm_table_repair: bool = False
    enable_llm_lineitem_match: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RuntimeConfig":
        validation_tolerance_millions = float(
            env.get(
                "FA_VALIDATION_TOLERANCE_MILLIONS",
                cls.validation_tolerance_millions,
            )
        )
        enable_llm_table_repair = env.get("FA_ENABLE_LLM_TABLE_REPAIR", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        enable_llm_lineitem_match = env.get(
            "FA_ENABLE_LLM_LINEITEM_MATCH", ""
        ).lower() in {"1", "true", "yes", "on"}
        return cls(
            validation_tolerance_millions=validation_tolerance_millions,
            enable_llm_table_repair=enable_llm_table_repair,
            enable_llm_lineitem_match=enable_llm_lineitem_match,
        )
