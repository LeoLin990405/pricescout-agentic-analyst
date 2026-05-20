# PriceScout: Agentic Analyst

PriceScout is an MCP-based analyst that compares LLM inference provider pricing. It contains a custom scraper MCP server, an AI-powered MCP host/client, SQLite persistence, and submission artifacts showing the required scraping and comparison workflows.

## Files

- `starter_server.py` implements the custom MCP server.
- `starter_client.py` implements the MCP host/client and agentic tool-use loop.
- `server_config.json` connects the client to the custom scraper, SQLite, and filesystem MCP servers.
- `submission_artifacts/` contains evidence output and screenshot-style images for the required demo queries.
- `tests/test_server_tools.py` smoke-tests the scraper persistence and extraction tools without external API keys.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add real keys to `.env`:

```bash
ANTHROPIC_API_KEY=your-anthropic-key
FIRECRAWL_API_KEY=your-firecrawl-key
```

The scraper uses Firecrawl when `FIRECRAWL_API_KEY` is present. A basic urllib fallback exists only so the persistence logic can be smoke-tested without using Firecrawl credits.

## Run

```bash
python starter_client.py
```

Example prompts:

```text
scrape these sites: {'cloudrift': 'https://www.cloudrift.ai/inference', 'deepinfra': 'https://deepinfra.com/pricing', 'fireworks': 'https://fireworks.ai/pricing#serverless-pricing', 'groq': 'https://groq.com/pricing'}
How much does cloudrift ai (https://www.cloudrift.ai/inference) charge for deepseek v3?
How much does deepinfra (https://deepinfra.com/pricing) charge for deepseek v3
Compare cloudrift ai and deepinfra's costs for deepseek v3
show data
```

## Implementation Notes

The custom MCP server persists one file per provider and format in `scraped_content/` and tracks provider name, URL, domain, scrape time, content files, title, and description in `scraped_metadata.json`.

The client loads `server_config.json`, initializes all configured stdio MCP servers, lists their tools, and drives a Claude tool-use loop. Tool calls are routed back to the server that owns the requested tool. SQLite persistence is performed through the SQLite MCP server using the required `pricing_plans` table shape.

## Verification

```bash
python -m unittest discover -s tests -v
```

Expected result:

```text
test_extract_saved_info_by_domain ... ok
test_scrape_websites_persists_metadata_and_files ... ok
```

Submission evidence is included in:

- `submission_artifacts/scrape_success_output.txt`
- `submission_artifacts/comparison_answer_output.txt`
- `submission_artifacts/scrape_success.png`
- `submission_artifacts/comparison_answer.png`

