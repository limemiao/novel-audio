import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from novel_audio.voices import load_catalog, normalize_voices, refresh_catalog


ROWS = [
    {"ShortName":"zh-CN-YunyangNeural", "Locale":"zh-CN", "Gender":"Male"},
    {"ShortName":"ja-JP-NanamiNeural", "Locale":"ja-JP", "Gender":"Female"},
]


class VoiceTests(unittest.TestCase):
    def test_metadata_and_invalid_entries(self):
        voices = normalize_voices(ROWS + [ROWS[0], None, {"ShortName":"fake<script>Neural", "Locale":"zh-CN", "Gender":"Male"}, {"ShortName":"en-US-TestNeural", "Locale":"zh-CN", "Gender":"Female"}])
        self.assertEqual(len(voices), 2)
        self.assertEqual(voices[0]["name"], "云扬")
        self.assertEqual(voices[0]["gender"], "Male")
        self.assertEqual(voices[1]["locale"], "ja-JP")
        with self.assertRaises(ValueError):
            normalize_voices([])

    def test_offline_snapshot_and_corrupt_cache_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            catalog = load_catalog(assets)
            ids = {v["id"] for v in catalog["voices"]}
            self.assertIn("zh-CN-YunyangNeural", ids)
            self.assertIn("zh-CN-liaoning-XiaobeiNeural", ids)
            self.assertIn("ja-JP-NanamiNeural", ids)
            (assets / "edge-voices.json").write_text("broken", encoding="utf-8")
            self.assertEqual(load_catalog(assets), catalog)

    def test_refresh_persists_and_failed_refresh_preserves_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            fake = SimpleNamespace(list_voices=AsyncMock(return_value=ROWS))
            with patch.dict("sys.modules", {"edge_tts":fake}):
                catalog = refresh_catalog(assets)
                self.assertEqual(catalog["source"], "live")
                self.assertEqual(len(load_catalog(assets)["voices"]), 2)
                before = (assets / "edge-voices.json").read_bytes()
                fake.list_voices = AsyncMock(side_effect=TimeoutError("offline"))
                with self.assertRaises(TimeoutError):
                    refresh_catalog(assets)
                self.assertEqual((assets / "edge-voices.json").read_bytes(), before)
                fake.list_voices = AsyncMock(return_value=[])
                with self.assertRaises(ValueError):
                    refresh_catalog(assets)
                self.assertEqual((assets / "edge-voices.json").read_bytes(), before)
