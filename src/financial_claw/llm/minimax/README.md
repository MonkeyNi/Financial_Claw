# MiniMax 图片表格提取 → Excel

一个简单脚本：输入一张图片 + prompt，调用 MiniMax `chatcompletion_v2`（支持图片），让模型输出**结构化表格 JSON**，再写入 `.xlsx`，尽量还原合并单元格与基础样式。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r src/financial_claw/llm/minimax/requirements.txt
```

## 配置

推荐使用本地配置文件（不会被 git 跟踪）：

```bash
cp src/financial_claw/llm/minimax/.env.example src/financial_claw/llm/minimax/.env
# 编辑 src/financial_claw/llm/minimax/.env，填入 MINIMAX_API_KEY
```

也可以手动设置环境变量：

```bash
export MINIMAX_API_KEY="YOUR_KEY"
export MINIMAX_API_BASE="https://api.minimax.io"   # 可选
export MINIMAX_MODEL="MiniMax-Text-01"             # 可选
```

## 运行

### 本地图片（推荐）

```bash
python -m financial_claw.llm.minimax.extract_table_to_excel \
  --image ./table.png \
  --prompt "提取图片中的表格，严格还原行列、合并单元格与文本。" \
  --out ./table.xlsx
```

如果你在 `.env` 里配置了偏“纯文本”的模型，图片可能会被忽略；可以临时覆盖为支持图片的模型（例如 `MiniMax-Text-01`）：

```bash
python -m financial_claw.llm.minimax.extract_table_to_excel \
  --model MiniMax-Text-01 \
  --image ./table.png \
  --prompt "提取图片中的表格，严格还原行列、合并单元格与文本。" \
  --out ./table.xlsx
```

### 远程图片 URL

```bash
python -m financial_claw.llm.minimax.extract_table_to_excel \
  --image-url "https://example.com/table.png" \
  --prompt "提取图片中的表格，严格还原行列、合并单元格与文本。" \
  --out ./table.xlsx
```

## 列出当前 Key 可用模型

OpenAI 兼容接口：

```bash
python -m financial_claw.llm.minimax.list_models --api openai
```

Anthropic 兼容接口：

```bash
python -m financial_claw.llm.minimax.list_models --api anthropic
```

保存原始响应：

```bash
python -m financial_claw.llm.minimax.list_models --api openai --out ./models.json
```

## 输出格式（模型需返回）

脚本会强制模型返回一个 JSON（可被包在 ```json 代码块里），形如：

- `sheets[].name`: sheet 名称
- `sheets[].cells[]`: 单元格列表（1-based 行列）
- `cells[].rowspan/colspan`: 合并信息（可选）
- `cells[].style`: 简单样式（可选：bold/italic/align/valign/number_format/bg_color/font_color）

如果模型返回的是 Markdown 表格，脚本会尝试降级解析（无法还原合并单元格）。
