from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import starter_server


class PriceScoutServerToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.scrape_dir = self.root / "scraped_content"
        self.metadata_file = self.root / "scraped_metadata.json"
        self.scrape_dir.mkdir()

    def test_scrape_websites_persists_metadata_and_files(self) -> None:
        fake_result = {
            "success": True,
            "markdown": "# Cloudrift\nDeepSeek V3 input $0.27 output $1.10",
            "html": "<h1>Cloudrift</h1>",
            "metadata": {"title": "Cloudrift Pricing", "description": "Inference pricing"},
        }
        with patch.object(starter_server, "SCRAPE_DIR", self.scrape_dir), patch.object(
            starter_server, "METADATA_FILE", self.metadata_file
        ), patch.object(starter_server, "_fallback_scrape", return_value=fake_result), patch.dict(
            starter_server.os.environ, {"FIRECRAWL_API_KEY": ""}, clear=False
        ):
            successful = starter_server.scrape_websites(
                {"cloudrift": "https://www.cloudrift.ai/inference"}, ["markdown", "html"]
            )

        self.assertEqual(successful, ["cloudrift"])
        metadata = json.loads(self.metadata_file.read_text(encoding="utf-8"))
        self.assertEqual(metadata["cloudrift"]["domain"], "www.cloudrift.ai")
        self.assertTrue((self.scrape_dir / "cloudrift_markdown.txt").exists())
        self.assertTrue((self.scrape_dir / "cloudrift_html.txt").exists())

    def test_extract_saved_info_by_domain(self) -> None:
        (self.scrape_dir / "deepinfra_markdown.txt").write_text("DeepInfra DeepSeek V3 pricing", encoding="utf-8")
        self.metadata_file.write_text(
            json.dumps(
                {
                    "deepinfra": {
                        "provider_name": "deepinfra",
                        "url": "https://deepinfra.com/pricing",
                        "domain": "deepinfra.com",
                        "content_files": {"markdown": "deepinfra_markdown.txt"},
                    }
                }
            ),
            encoding="utf-8",
        )
        with patch.object(starter_server, "SCRAPE_DIR", self.scrape_dir), patch.object(
            starter_server, "METADATA_FILE", self.metadata_file
        ):
            result = json.loads(starter_server.extract_scraped_info("deepinfra.com"))

        self.assertEqual(result["provider_name"], "deepinfra")
        self.assertIn("DeepSeek V3 pricing", result["content"]["markdown"])


if __name__ == "__main__":
    unittest.main()

