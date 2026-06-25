<div align="center">

[![English](https://img.shields.io/badge/Language-English-2ea44f?style=for-the-badge)](README.md) &nbsp; [![中文](https://img.shields.io/badge/语言-中文-555555?style=for-the-badge)](README.zh-CN.md)

# PriceScout · Agentic Analyst

### An MCP research assistant that scrapes and compares LLM inference pricing across providers

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Protocol-MCP-blueviolet?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Store-SQLite-blue?style=for-the-badge&logo=sqlite&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-yellowgreen?style=for-the-badge" />
</p>

</div>

> LLM inference pricing is scattered across a dozen provider pages and changes weekly. PriceScout points an agent at those pages, extracts the numbers, persists them, and answers "who's cheaper for model X?".

---

## Overview

PriceScout is an **MCP-based research assistant** for comparing LLM inference pricing across providers.

| Component | Role |
|---|---|
| `starter_server.py` | MCP server — tools to scrape provider pricing pages + retrieve persisted content |
| `starter_client.py` | MCP client — connects to the scraping + SQLite servers, routes Claude tool calls, stores structured pricing data |
| `server_config.json` | MCP server config (local project server + SQLite MCP server) |
| `evidence.pdf` | visual evidence: scraping, extraction, final comparison |

---

## 1. Providers

Default workflow targets:

- [CloudRift](https://www.cloudrift.ai/inference) · [DeepInfra](https://deepinfra.com/pricing) · [Fireworks](https://fireworks.ai/pricing#serverless-pricing) · [Groq](https://groq.com/pricing)

---

## 2. Setup

```bash
uv sync
cp .env.example .env
```

Add your keys to `.env` for real execution:

```bash
ANTHROPIC_API_KEY=your_anthropic_key
FIRECRAWL_API_KEY=your_firecrawl_key
```

Run:

```bash
uv run python starter_client.py
```

Example prompts:

```text
How much does CloudRift charge for deepseek v3?
How much does DeepInfra charge for deepseek v3?
Compare CloudRift and DeepInfra costs for deepseek v3
```

---

## 3. Evidence / Demo Mode

For evidence without sharing private API keys, deterministic demo execution is supported:

```bash
PRICESCOUT_DEMO_MODE=1 uv run python starter_client.py
```

Demo mode exercises the same MCP tools + persistence path but uses local provider pricing text instead of calling Firecrawl/Anthropic. `evidence.pdf` shows: 4/4 provider scraping success · structured extraction + `show data` from SQLite · final natural-language comparison + unit-test output.

The submitted folder excludes `.env`, `test.db`, `scraped_content/`, `.venv/`, `__pycache__/`.

---

## License

[MIT](LICENSE) © 2026 Leo Lin
