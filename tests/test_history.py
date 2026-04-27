from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from platex_client.history import HistoryStore
from platex_client.models import ClipboardEvent
from platex_client.loader import load_script_processor


class HistoryStoreTests(unittest.TestCase):
    def test_add_and_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "history.sqlite3")
            try:
                event = ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="abc123",
                    image_width=120,
                    image_height=80,
                    latex=r"x^2+y^2=z^2",
                    source="test-script",
                    status="ok",
                    error=None,
                )
                store.add(event)

                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertEqual(latest.image_hash, "abc123")
                self.assertEqual(latest.latex, r"x^2+y^2=z^2")
            finally:
                store.close()


class LoaderTests(unittest.TestCase):
    def test_load_script_processor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text(
                r'''
def process_image(image_bytes, context):
    return r"\alpha + \beta"
'''.strip(),
                encoding="utf-8",
            )

            processor = load_script_processor(script_path)
            result = processor.process_image(b"fake-bytes", {})
            self.assertEqual(result, r"\alpha + \beta")


if __name__ == "__main__":
    unittest.main()