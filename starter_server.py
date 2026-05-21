import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from firecrawl import FirecrawlApp
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SCRAPE_DIR = "scraped_content"
METADATA_FILENAME = "scraped_metadata.json"

mcp = FastMCP("llm_inference")

DEMO_PRICING = {
    "cloudrift": {
        "title": "CloudRift AI Inference Pricing",
        "description": "Demo pricing extracted from CloudRift AI inference page.",
        "markdown": """
# CloudRift AI Inference Pricing

CloudRift lists serverless inference prices by model. DeepSeek V3 is priced at
$0.27 per 1M input tokens and $1.10 per 1M output tokens. The service is billed
per token with no monthly platform fee for serverless usage.

Other notes: OpenAI-compatible API, low-latency routing, and usage-based billing.
""".strip(),
    },
    "deepinfra": {
        "title": "DeepInfra Pricing",
        "description": "Demo pricing extracted from DeepInfra pricing page.",
        "markdown": """
# DeepInfra Pricing

DeepInfra publishes model-level token pricing. DeepSeek V3 is listed at $0.27
per 1M input tokens and $1.00 per 1M output tokens. Billing is usage based and
there is no fixed monthly subscription for serverless inference.

Other notes: serverless inference, OpenAI-compatible endpoints, and volume usage
tracking.
""".strip(),
    },
    "fireworks": {
        "title": "Fireworks Serverless Pricing",
        "description": "Demo pricing extracted from Fireworks serverless pricing.",
        "markdown": """
# Fireworks Serverless Pricing

Fireworks lists serverless model prices. DeepSeek V3 class models are billed per
1M input and output tokens. Pricing varies by hosted model and throughput tier.
""".strip(),
    },
    "groq": {
        "title": "Groq Pricing",
        "description": "Demo pricing extracted from Groq pricing.",
        "markdown": """
# Groq Pricing

Groq publishes token prices for supported hosted models and emphasizes very fast
inference. Pricing is usage based with model-specific input and output rates.
""".strip(),
    },
}


def _safe_provider_name(provider_name: str, url: str) -> str:
    base = provider_name or urlparse(url).netloc or "provider"
    return re.sub(r"[^a-zA-Z0-9]+", "_", base.strip().lower()).strip("_")


def _load_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Metadata file was invalid JSON. Starting fresh.")
        return {}


def _write_content_files(provider_key: str, formats: List[str], scrape_data: dict, out_dir: Path) -> dict:
    content_files = {}
    for fmt in formats:
        content = scrape_data.get(fmt) or scrape_data.get("markdown") or scrape_data.get("html") or ""
        filename = f"{provider_key}_{fmt}.txt"
        (out_dir / filename).write_text(str(content), encoding="utf-8")
        content_files[fmt] = filename
    return content_files


def _demo_scrape(provider_name: str, url: str) -> dict:
    provider_key = _safe_provider_name(provider_name, url)
    normalized = provider_key.replace("_ai", "")
    demo = DEMO_PRICING.get(normalized) or DEMO_PRICING.get(provider_key)
    if demo is None:
        demo = {
            "title": f"{provider_name} pricing",
            "description": "Demo pricing content for offline evidence generation.",
            "markdown": f"# {provider_name}\n\nPricing page: {url}\n\nNo specific pricing was available in demo mode.",
        }
    markdown = demo["markdown"]
    return {
        "markdown": markdown,
        "html": f"<html><body><pre>{markdown}</pre></body></html>",
        "metadata": {"title": demo["title"], "description": demo["description"]},
    }


def _firecrawl_scrape(app: FirecrawlApp, url: str, formats: List[str]) -> dict:
    result = app.scrape_url(url, formats=formats)
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if isinstance(result, dict):
        return result
    return dict(result)


@mcp.tool()
def scrape_websites(
    websites: Dict[str, str],
    formats: List[str] = ["markdown", "html"],
    api_key: Optional[str] = None,
) -> List[str]:
    """
    Scrape multiple pricing websites using Firecrawl and store their content.

    When PRICESCOUT_DEMO_MODE=1, deterministic local demo content is used so the
    workflow can be demonstrated without sharing private API keys.
    """
    if not websites:
        raise ValueError("websites must contain at least one provider URL")

    out_dir = Path(SCRAPE_DIR)
    out_dir.mkdir(exist_ok=True)
    metadata_path = out_dir / METADATA_FILENAME
    metadata = _load_metadata(metadata_path)

    demo_mode = os.getenv("PRICESCOUT_DEMO_MODE", "").lower() in {"1", "true", "yes"}
    app = None
    if not demo_mode:
        api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            raise ValueError(
                "API key must be provided or set as FIRECRAWL_API_KEY. "
                "For local evidence without secrets, set PRICESCOUT_DEMO_MODE=1."
            )
        app = FirecrawlApp(api_key=api_key)

    scraped = []
    for provider_name, url in websites.items():
        provider_key = _safe_provider_name(provider_name, url)
        parsed = urlparse(url)
        logger.info("Scraping %s from %s", provider_key, url)

        try:
            scrape_data = _demo_scrape(provider_name, url) if demo_mode else _firecrawl_scrape(app, url, formats)
            content_files = _write_content_files(provider_key, formats, scrape_data, out_dir)
            scrape_metadata = scrape_data.get("metadata", {}) or {}
            metadata[provider_key] = {
                "provider_name": provider_key,
                "display_name": provider_name,
                "url": url,
                "domain": parsed.netloc,
                "scraped_at": datetime.utcnow().isoformat(),
                "formats": formats,
                "success": "true",
                "content_files": content_files,
                "title": scrape_metadata.get("title", provider_name),
                "description": scrape_metadata.get("description", "Pricing page scraped successfully."),
                "demo_mode": demo_mode,
            }
            scraped.append(provider_key)
        except Exception as exc:
            logger.exception("Failed to scrape %s", provider_name)
            metadata[provider_key] = {
                "provider_name": provider_key,
                "display_name": provider_name,
                "url": url,
                "domain": parsed.netloc,
                "scraped_at": datetime.utcnow().isoformat(),
                "formats": formats,
                "success": "false",
                "error": str(exc),
                "content_files": {},
            }

    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.info("Scraping completed: %s/%s providers succeeded: %s", len(scraped), len(websites), scraped)
    return scraped


@mcp.tool()
def extract_scraped_info(identifier: str) -> str:
    """
    Return stored metadata and content for a provider name, URL, or domain.
    """
    logger.info("Extracting information for identifier: %s", identifier)
    metadata_path = Path(SCRAPE_DIR) / METADATA_FILENAME
    if not metadata_path.exists():
        return json.dumps({"error": "No scraped metadata found. Run scrape_websites first."}, indent=2)

    metadata = _load_metadata(metadata_path)
    needle = identifier.strip().lower()
    selected_key = None
    for provider_key, item in metadata.items():
        candidates = [
            provider_key,
            item.get("display_name", ""),
            item.get("url", ""),
            item.get("domain", ""),
        ]
        if any(needle in str(candidate).lower() for candidate in candidates):
            selected_key = provider_key
            break

    if selected_key is None:
        return json.dumps({"error": f"No scraped provider matched '{identifier}'.", "available": list(metadata)}, indent=2)

    item = dict(metadata[selected_key])
    content = {}
    for fmt, filename in item.get("content_files", {}).items():
        path = Path(SCRAPE_DIR) / filename
        content[fmt] = path.read_text(encoding="utf-8") if path.exists() else ""
    item["content"] = content
    return json.dumps(item, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
