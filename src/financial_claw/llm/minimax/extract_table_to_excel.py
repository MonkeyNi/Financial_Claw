from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from financial_claw.llm.minimax.excel_writer import write_table_document_to_xlsx  # noqa: E402
from financial_claw.llm.minimax.minimax_api import (  # noqa: E402
    MinimaxConfig,
    load_config_from_env,
    minimax_chatcompletion_v2_with_image,
)
from financial_claw.llm.minimax.parse_response import parse_table_document_from_model_text  # noqa: E402


SYSTEM_INSTRUCTIONS = """你是一个表格还原器。你会看到一张包含表格的图片。
你的任务：提取并还原表格结构，输出一个严格 JSON（不要输出任何额外文字）。

JSON 结构如下（必须符合）：
{
  "sheets": [
    {
      "name": "Sheet1",
      "cells": [
        {
          "r": 1, "c": 1,
          "v": "单元格内容（字符串/数字/空）",
          "rowspan": 1,
          "colspan": 1,
          "style": {
            "bold": true,
            "italic": false,
            "align": "left|center|right|general",
            "valign": "top|center|bottom|general",
            "number_format": "Excel number format string",
            "bg_color": "#RRGGBB",
            "font_color": "#RRGGBB"
          }
        }
      ],
      "column_widths": [12, 18, 10],
      "row_heights": [18, 18, 18]
    }
  ],
  "meta": {
    "notes": "可选：任何补充信息"
  }
}

约束：
- r/c 从 1 开始。
- 遇到合并单元格：只在左上角单元格写入 v，并设置 rowspan/colspan。
- 不要省略空白行/列（如果存在明显的表格间隔，也要反映到 r/c）。
- 数字保持原样（不要随意加千分位）；含括号的负数保留括号。
- 只输出 JSON（可以放在 ```json 代码块里）。
"""


def build_final_prompt(user_prompt: str) -> str:
    user_prompt = (user_prompt or "").strip()
    if not user_prompt:
        user_prompt = "提取图片中的表格，严格还原行列、合并单元格与文本。"
    return SYSTEM_INSTRUCTIONS + "\n\n用户补充要求：\n" + user_prompt


def _extract_assistant_text(resp_json: dict) -> str:
    # Minimax response example: choices[0].message.content
    choices = resp_json.get("choices") or []
    if not choices:
        raise RuntimeError(f"MiniMax response missing choices: {list(resp_json.keys())}")
    msg = (choices[0] or {}).get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        # Some variants may return content as list; join text blocks
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            content = "\n".join(parts)
        else:
            content = str(content)
    return content


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract table from image using MiniMax, save as Excel.")
    ap.add_argument("--image", type=str, default="", help="Local image path (png/jpg/webp).")
    ap.add_argument("--image-url", type=str, default="", help="Remote image URL.")
    ap.add_argument("--prompt", type=str, required=True, help="User prompt for extraction.")
    ap.add_argument("--out", type=str, required=True, help="Output xlsx path.")
    ap.add_argument("--temperature", type=float, default=0.0, help="Model temperature.")
    ap.add_argument("--model", type=str, default="", help="Override model name for this run.")
    args = ap.parse_args()

    image_path = Path(args.image).expanduser().resolve() if args.image else None
    image_url = args.image_url.strip() if args.image_url else None
    out_path = Path(args.out).expanduser().resolve()

    cfg = load_config_from_env()
    if args.model.strip():
        cfg = MinimaxConfig(
            api_key=cfg.api_key,
            api_base=cfg.api_base,
            model=args.model.strip(),
            timeout_s=cfg.timeout_s,
        )
    final_prompt = build_final_prompt(args.prompt)

    logger.info("Calling MiniMax model={} base={}", cfg.model, cfg.api_base)
    resp_json = minimax_chatcompletion_v2_with_image(
        cfg=cfg,
        prompt=final_prompt,
        image_path=image_path,
        image_url=image_url,
        temperature=float(args.temperature),
    )

    assistant_text = _extract_assistant_text(resp_json)
    logger.debug("Model raw output (truncated): {}", assistant_text[:1200])

    doc = parse_table_document_from_model_text(assistant_text)
    write_table_document_to_xlsx(doc, out_path)


if __name__ == "__main__":
    main()
