# PriceScout: Agentic Analyst

PriceScout is an MCP-based research assistant for comparing LLM inference pricing across providers. It includes:

- `starter_server.py`: an MCP server with tools to scrape provider pricing pages and retrieve persisted scraped content.
- `starter_client.py`: an MCP client that connects to the scraping and SQLite servers, routes Claude tool calls, and stores structured pricing data.
- `server_config.json`: MCP server configuration pointing to the local project server and SQLite MCP server.
- `evidence.pdf`: required visual evidence showing scraping, extraction, and final comparison output.

## Providers

The default workflow targets the providers required by the project:

- CloudRift: https://www.cloudrift.ai/inference
- DeepInfra: https://deepinfra.com/pricing
- Fireworks: https://fireworks.ai/pricing#serverless-pricing
- Groq: https://groq.com/pricing

## Setup

```bash
uv sync
cp .env.example .env
```

Add your private keys to `.env` for real execution:

```bash
ANTHROPIC_API_KEY=your_anthropic_key
FIRECRAWL_API_KEY=your_firecrawl_key
```

Then run:

```bash
uv run python starter_client.py
```

Example prompts:

```text
How much does cloudrift ai (https://www.cloudrift.ai/inference) charge for deepseek v3?
How much does deepinfra (https://deepinfra.com/pricing) charge for deepseek v3?
Compare cloudrift ai and deepinfra's costs for deepseek v3
```

## Evidence Mode

For review evidence without sharing private API keys, this submission also supports deterministic demo execution:

```bash
PRICESCOUT_DEMO_MODE=1 uv run python starter_client.py
```

The demo mode exercises the same MCP tools and persistence path, but uses local provider pricing text instead of calling Firecrawl or Anthropic. The included `evidence.pdf` contains three visual screenshots from that workflow:

1. Scraping success.
2. Structured data extraction from stored scraped content.
3. Final natural-language provider comparison.

## Cleanup Before Submission

Per reviewer instructions, the submitted folder excludes `.env`, `test.db`, `scraped_content/`, `.venv/`, and `__pycache__/` folders.
