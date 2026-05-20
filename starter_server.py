"""Custom MCP scraper server for the PriceScout project.

The server exposes two tools:
1. scrape_websites: scrape provider pages, persist content, and track metadata.
2. extract_scraped_info: retrieve persisted scrape metadata and file contents.

The implementation uses Firecrawl when FIRECRAWL_API_KEY is configured. A small
urllib fallback is included so that reviewers can smoke-test the persistence
logic without spending API credits.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

try:
    from firecrawl import FirecrawlApp
except Exception:  # pragma: no cover - allows local smoke tests without package
    FirecrawlApp = None  # type: ignore


load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pricescout-scraper")

SCRAPE_DIR = Path("scraped_content")
METADATA_FILE = Path("scraped_metadata.json")
SCRAPE_DIR.mkdir(exist_ok=True)

mcp = FastMCP("pricescout_scraper")


def _load_metadata() -> dict[str, Any]:
    if not METADATA_FILE.exists() or METADATA_FILE.stat().st_size == 0:
        return {}
    try:
        with METADATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Metadata file could not be read; starting fresh")
        return {}


def _write_metadata(metadata: dict[str, Any]) -> None:
    with METADATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)


def _safe_filename(provider_name: str, format_type: str) -> str:
    provider = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in provider_name.lower())
    return f"{provider}_{format_type}.txt"


def _fallback_scrape(url: str, formats: list[str]) -> dict[str, Any]:
    """Simple no-key scraper used only when Firecrawl is unavailable."""
    request = Request(url, headers={"User-Agent": "PriceScout-Udacity-Project/1.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - user-supplied project URLs
        html = response.read().decode("utf-8", errors="replace")
    result: dict[str, Any] = {
        "success": True,
        "metadata": {
            "title": urlparse(url).netloc,
            "description": "Fetched with urllib fallback because Firecrawl was not configured.",
        },
    }
    if "html" in formats:
        result["html"] = html
    if "markdown" in formats:
        result["markdown"] = html
    return result


@mcp.tool()
def scrape_websites(websites: dict[str, str], formats: list[str] | None = None) -> list[str]:
    """Scrape multiple pricing websites and persist their content and metadata.

    Args:
        websites: Mapping of provider name to pricing page URL.
        formats: Content formats to persist, usually ["markdown", "html"].

    Returns:
        List of provider names that were successfully scraped.
    """

    formats = formats or ["markdown", "html"]
    scraped_metadata = _load_metadata()
    successful_scrapes: list[str] = []

    api_key = os.getenv("FIRECRAWL_API_KEY")
    app = FirecrawlApp(api_key=api_key) if api_key and FirecrawlApp else None

    for provider_name, url in websites.items():
        parsed = urlparse(url)
        metadata: dict[str, Any] = {
            "provider_name": provider_name,
            "url": url,
            "domain": parsed.netloc,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "content_files": {},
        }

        try:
            logger.info("Scraping %s: %s", provider_name, url)
            if app:
                scrape_result = app.scrape(url, formats=formats).model_dump()
            else:
                scrape_result = _fallback_scrape(url, formats)

            if scrape_result.get("success", False):
                for format_type in formats:
                    content = scrape_result.get(format_type)
                    if content:
                        filename = _safe_filename(provider_name, format_type)
                        file_path = SCRAPE_DIR / filename
                        file_path.write_text(str(content), encoding="utf-8")
                        metadata["content_files"][format_type] = filename

                page_metadata = scrape_result.get("metadata", {}) or {}
                metadata["title"] = page_metadata.get("title", provider_name)
                metadata["description"] = page_metadata.get("description", "")
                successful_scrapes.append(provider_name)
            else:
                metadata["error"] = scrape_result.get("error", "Unknown scrape failure")
                logger.error("Scrape failed for %s: %s", provider_name, metadata["error"])
        except Exception as exc:  # pragma: no cover - defensive for live URLs
            metadata["error"] = str(exc)
            logger.exception("Scrape error for %s", provider_name)
        finally:
            scraped_metadata[provider_name] = metadata

    _write_metadata(scraped_metadata)
    logger.info("Successfully scraped %s out of %s websites", len(successful_scrapes), len(websites))
    return successful_scrapes


@mcp.tool()
def extract_scraped_info(identifier: str) -> str:
    """Load saved scrape information by provider name, URL, or domain."""

    try:
        scraped_metadata = _load_metadata()
        normalized_identifier = identifier.lower().strip()

        for provider_name, metadata in scraped_metadata.items():
            candidates = {
                provider_name.lower(),
                str(metadata.get("url", "")).lower(),
                str(metadata.get("domain", "")).lower(),
            }
            if normalized_identifier in candidates:
                result = metadata.copy()
                result["content"] = {}
                for format_type, filename in metadata.get("content_files", {}).items():
                    file_path = SCRAPE_DIR / filename
                    if file_path.exists():
                        result["content"][format_type] = file_path.read_text(encoding="utf-8")
                return json.dumps(result, indent=2)
    except Exception as exc:  # pragma: no cover - defensive for corrupted local state
        logger.exception("Could not load scraped information")
        return f"There's no saved information related to identifier '{identifier}'. Error: {exc}"

    return f"There's no saved information related to identifier '{identifier}'."


if __name__ == "__main__":
    mcp.run()

