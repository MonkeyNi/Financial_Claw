from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Align = Literal["left", "center", "right", "general"]
VAlign = Literal["top", "center", "bottom", "general"]


@dataclass(frozen=True)
class CellStyle:
    bold: bool | None = None
    italic: bool | None = None
    align: Align | None = None
    valign: VAlign | None = None
    number_format: str | None = None
    bg_color: str | None = None  # "#RRGGBB"
    font_color: str | None = None  # "#RRGGBB"


@dataclass(frozen=True)
class TableCell:
    r: int
    c: int
    v: str | int | float | None = None
    rowspan: int = 1
    colspan: int = 1
    style: CellStyle = field(default_factory=CellStyle)


@dataclass(frozen=True)
class TableSheet:
    name: str = "Sheet1"
    cells: list[TableCell] = field(default_factory=list)
    column_widths: list[float] | None = None
    row_heights: list[float] | None = None


@dataclass(frozen=True)
class TableDocument:
    sheets: list[TableSheet] = field(default_factory=list)
    meta: dict[str, Any] | None = None

