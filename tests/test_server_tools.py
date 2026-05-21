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
        self.scrape_dir = Path(self.temp_dir.name) / "scraped_content"

    def test_demo_scrape_websites_persists_metadata_and_files(self) -> None:
        with patch.object(starter_server, "SCRAPE_DIR", str(self.scrape_dir)), patch.dict(
            starter_server.os.environ, {"PRICESCOUT_DEMO_MODE": "1"}, clear=False
        ):
            successful = starter_server.scrape_websites(
                {"cloudrift": "https://www.cloudrift.ai/inference"}, ["markdown", "html"]
            )

        self.assertEqual(successful, ["cloudrift"])
        metadata = json.loads((self.scrape_dir / starter_server.METADATA_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(metadata["cloudrift"]["domain"], "www.cloudrift.ai")
        self.assertTrue((self.scrape_dir / "cloudrift_markdown.txt").exists())
        self.assertTrue((self.scrape_dir / "cloudrift_html.txt").exists())

    def test_extract_saved_info_by_domain(self) -> None:
        self.scrape_dir.mkdir(parents=True)
        (self.scrape_dir / "deepinfra_markdown.txt").write_text("DeepInfra DeepSeek V3 pricing", encoding="utf-8")
        (self.scrape_dir / starter_server.METADATA_FILENAME).write_text(
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
        with patch.object(starter_server, "SCRAPE_DIR", str(self.scrape_dir)):
            result = json.loads(starter_server.extract_scraped_info("deepinfra.com"))

        self.assertEqual(result["provider_name"], "deepinfra")
        self.assertIn("DeepSeek V3 pricing", result["content"]["markdown"])


if __name__ == "__main__":
    unittest.main()
