# PriceScout reference

Implementation notes for the two MCP servers, the client runtime, and the SQLite schema.
Everything here is derived from the files in this repository; no live pricing claim is made.

- [`../starter_server.py`](../starter_server.py) — `llm_inference` FastMCP server
- [`../starter_client.py`](../starter_client.py) — stdio MCP client and agent loop
- [`../server_config.json`](../server_config.json) — server launch table
- [`../tests/test_server_tools.py`](../tests/test_server_tools.py) — `unittest` coverage

## Server configuration

`starter_client.py` loads `server_config.json` from the directory of the script
(`Configuration.load_config`). The file must contain an `mcpServers` object; every entry must have
`command` and a list-valued `args`, and an optional `env` map is merged over the parent environment.

| Entry | Command | Args | Purpose |
|---|---|---|---|
| `llm_inference` | `python` | `starter_server.py` | scraping tools backed by Firecrawl or demo text |
| `sqlite` | `uvx` | `mcp-server-sqlite --db-path ./test.db` | SQL tools over a local SQLite file |

Both servers are spoken to over stdio. The client resolves `command` with `shutil.which` and
falls back to the literal string, so `python` must be on `PATH` for the server process.

## `llm_inference` tools

Both tools are registered with the `@mcp.tool()` decorator on `FastMCP("llm_inference")`.

### `scrape_websites`

```python
scrape_websites(
    websites: Dict[str, str],              # display name -> URL
    formats: List[str] = ["markdown", "html"],
    api_key: Optional[str] = None,
) -> List[str]                             # provider keys that succeeded
```

- Empty `websites` raises `ValueError`.
- Live mode uses `FirecrawlApp.scrape_url(url, formats=formats)`; the returned object is normalised
  with `model_dump()` when available.
- Demo mode is selected by `PRICESCOUT_DEMO_MODE=1|true|yes` and skips Firecrawl entirely.
- Per-provider failures are recorded with `success: "false"` and an `error` string; the loop
  continues and the tool does not raise.
- Provider keys are lowercased with non-alphanumeric runs collapsed to `_`
  (`www.cloudrift.ai` → `www_cloudrift_ai`).
- Side effects, relative to the server process working directory:
  - `scraped_content/<provider>_<format>.txt` for each requested format;
  - `scraped_content/scraped_metadata.json` rewritten after every call.

### `extract_scraped_info`

```python
extract_scraped_info(identifier: str) -> str   # indented JSON document
```

- `identifier` is lowercased and matched as a substring against, in order: provider key,
  `display_name`, `url`, `domain`. The first match wins, in metadata insertion order.
- The returned object is the stored metadata plus a `content` map of format → file text (empty
  string when the file is missing).
- Misses return `{"error": ..., "available": [...]}` instead of raising.
- A missing metadata file returns `{"error": "No scraped metadata found. Run scrape_websites first."}`.

### Metadata record

| Field | Type | Notes |
|---|---|---|
| `provider_name` | string | normalised key, also the metadata map key |
| `display_name` | string | the key originally passed in `websites` |
| `url` | string | requested URL |
| `domain` | string | `urlparse(url).netloc` |
| `scraped_at` | string | `datetime.utcnow().isoformat()` |
| `formats` | list | requested formats |
| `success` | string | `"true"` or `"false"` |
| `content_files` | object | format → file name |
| `title`, `description` | string | taken from Firecrawl metadata when present |
| `demo_mode` | bool | present on successful scrapes |
| `error` | string | present on failed scrapes |

## SQLite server

The `sqlite` entry launches the reference `mcp-server-sqlite` package through `uvx`, with the
database at `./test.db` relative to the directory the client was started from. The recorded session
in [`../evidence_terminal_output.txt`](../evidence_terminal_output.txt) lists the tools exposed by
that server:

| Tool | Use in this project |
|---|---|
| `write_query` | `CREATE TABLE` and `INSERT` for `pricing_plans` |
| `read_query` | `SELECT ... ORDER BY id DESC LIMIT 5` for `show data` |
| `create_table`, `list_tables`, `describe_table` | available but unused |
| `append_insight` | available but unused |

### `pricing_plans` schema

Created by `DataExtractor.setup_data_tables` on startup:

| Column | Type | Constraint |
|---|---|---|
| `id` | INTEGER | primary key, autoincrement |
| `company_name` | TEXT | not null |
| `plan_name` | TEXT | not null |
| `input_tokens` | REAL | price per 1M input tokens |
| `output_tokens` | REAL | price per 1M output tokens |
| `currency` | TEXT | default `'USD'` |
| `billing_period` | TEXT | e.g. `per 1M tokens` |
| `features` | TEXT | JSON-encoded list |
| `limitations` | TEXT | free text |
| `source_query` | TEXT | the user question that produced the row |
| `created_at` | DATETIME | default `CURRENT_TIMESTAMP` |

Rows are inserted one `INSERT` per plan, with string values escaped by a small
`_sql_literal` helper. Repeated runs append rows; nothing updates or de-duplicates existing
records.

## Client runtime

| Setting | Value | Where |
|---|---|---|
| Chat model | `claude-3-5-sonnet-20241022` | `ChatSession.process_query` |
| Chat `max_tokens` | 2024 | `ChatSession.process_query` |
| Extraction model | `claude-3-5-sonnet-20241022` | `DataExtractor.extract_and_store_data` |
| Extraction `max_tokens` | 1024 | `DataExtractor.extract_and_store_data` |
| Per-tool retries | 2 retries (3 attempts), 1.0 s delay | `Server.execute_tool` |
| Tool read timeout | 60 s | `Server.execute_tool` |
| `show data` window | last 5 rows | `ChatSession.show_stored_data` |
| API key source | `ANTHROPIC_API_KEY` from `.env` or environment | `Configuration` |

The agent loop mirrors the Anthropic tool-use protocol: it sends the tool schemas discovered from
every connected server, executes each `tool_use` block against the owning server, and loops until a
response contains no tool calls. Tool results are appended as text.

## Demo mode

`PRICESCOUT_DEMO_MODE` (any of `1`, `true`, `yes`) changes three things:

1. `scrape_websites` returns built-in page text from the `DEMO_PRICING` dict instead of calling Firecrawl.
2. The client never constructs an `Anthropic` client; `process_query` prints a fixed answer from
   `ChatSession._demo_answer`.
3. `DataExtractor` uses two regexes instead of an LLM call, and only recognises CloudRift and
   DeepInfra price sentences.

[`../.env.example`](../.env.example) ships with `PRICESCOUT_DEMO_MODE=1`, so a plain
`cp .env.example .env` keeps demo mode on even after keys are filled in; set the variable to `0` (or
remove the line) for live runs. Any value outside `1`/`true`/`yes` counts as off.

Built-in demo pages (hard-coded, not scraped):

| Provider | Demo input price | Demo output price |
|---|---|---|
| CloudRift | $0.27 / 1M tokens | $1.10 / 1M tokens |
| DeepInfra | $0.27 / 1M tokens | $1.00 / 1M tokens |
| Fireworks | no numeric price in the demo text | no numeric price in the demo text |
| Groq | no numeric price in the demo text | no numeric price in the demo text |

A provider outside that set receives a placeholder page containing its URL and the sentence
"No specific pricing was available in demo mode."

## Recorded evidence in this repository

| File | Contents |
|---|---|
| [`../evidence.pdf`](../evidence.pdf) | 3-page PDF walkthrough: scraping, extraction, final comparison |
| [`../evidence_terminal_output.txt`](../evidence_terminal_output.txt) | demo-mode transcript: 4/4 providers scraped, 2 plans stored, `show data` output |
| [`../test_output.txt`](../test_output.txt) | recorded `unittest` run: 2 tests, `OK` |

The recorded transcript was produced against the demo path, so it demonstrates the tool wiring and
the persistence path, not live provider prices. The 3-page PDF covers the same workflow steps.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `API key must be provided or set as FIRECRAWL_API_KEY` | live scrape without a key | set the key in `.env`, or set `PRICESCOUT_DEMO_MODE=1` |
| `ANTHROPIC_API_KEY not found in environment variables` | live chat without a key | set the key, or run in demo mode |
| `No scraped metadata found` | scrape never ran, or ran from another directory | run a query first from the repository root |
| `No scraped provider matched '<x>'` | identifier typo | use the provider key or domain shown in the `available` list |
| `sqlite` server fails to initialise | `uvx` missing, or first-run package download failed | install `uv`, then run `uvx mcp-server-sqlite --help` once |
| `show data` prints "No pricing plans have been stored yet." | extraction failed or produced no `plans` | check the log line `Error extracting pricing data` |
| Demo answer repeats regardless of the question | `PRICESCOUT_DEMO_MODE` is still on | set it to `0` in `.env` or unset it |

## Code-level notes

- `pyproject.toml` is still the starter template: project name `mcp-project`, version `0.1.0`, no
  `[build-system]`, no console scripts. Its dependency list also carries unused packages
  (`aiohttp`, `bs4`, `gradio[mcp]`, `ipykernel`, `textblob`); [`../requirements.txt`](../requirements.txt)
  lists the four libraries the two scripts actually import.
- `datetime.utcnow()` is deprecated on Python 3.12+; the recorded test run shows the
  `DeprecationWarning`.
- Demo extraction is regex-based (`_demo_structured_extraction`), so it will not pick up prices for
  any other provider, even if those pages are in `DEMO_PRICING`.
- Logging is configured at INFO and writes to stderr, which interleaves with the chat prompt.
