from __future__ import annotations

import unittest
from datetime import datetime, timezone

from platex_client.models import ClipboardEvent, ClipboardImage, OcrProcessor


class TestClipboardEvent(unittest.TestCase):
    def test_create_basic_event(self):
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
        self.assertEqual(event.image_hash, "abc123")
        self.assertEqual(event.image_width, 120)
        self.assertEqual(event.image_height, 80)
        self.assertEqual(event.latex, r"x^2+y^2=z^2")
        self.assertEqual(event.source, "test-script")
        self.assertEqual(event.status, "ok")
        self.assertIsNone(event.error)

    def test_create_error_event(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="err_hash",
            image_width=0,
            image_height=0,
            latex="",
            source="test",
            status="error",
            error="Something went wrong",
        )
        self.assertEqual(event.status, "error")
        self.assertEqual(event.error, "Something went wrong")

    def test_error_default_none(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=1,
            image_height=1,
            latex="x",
            source="s",
            status="ok",
        )
        self.assertIsNone(event.error)

    def test_slots_prevents_arbitrary_attributes(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=1,
            image_height=1,
            latex="x",
            source="s",
            status="ok",
        )
        with self.assertRaises(AttributeError):
            event.arbitrary_attr = "fail"

    def test_unicode_latex(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=1,
            image_height=1,
            latex=r"\alpha + \beta = \gamma",
            source="s",
            status="ok",
        )
        self.assertIn(r"\alpha", event.latex)

    def test_empty_latex(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=1,
            image_height=1,
            latex="",
            source="s",
            status="error",
            error="empty result",
        )
        self.assertEqual(event.latex, "")

    def test_large_dimensions(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=3840,
            image_height=2160,
            latex="x",
            source="s",
            status="ok",
        )
        self.assertEqual(event.image_width, 3840)
        self.assertEqual(event.image_height, 2160)

    def test_zero_dimensions(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=0,
            image_height=0,
            latex="",
            source="s",
            status="error",
            error="no image",
        )
        self.assertEqual(event.image_width, 0)

    def test_long_error_message(self):
        long_error = "x" * 5000
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=1,
            image_height=1,
            latex="",
            source="s",
            status="error",
            error=long_error,
        )
        self.assertEqual(len(event.error), 5000)

    def test_various_status_values(self):
        for status in ("ok", "error", "pending", "timeout"):
            event = ClipboardEvent(
                created_at=datetime.now(timezone.utc),
                image_hash="h",
                image_width=1,
                image_height=1,
                latex="x",
                source="s",
                status=status,
            )
            self.assertEqual(event.status, status)

    def test_mutable_dataclass(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="h",
            image_width=1,
            image_height=1,
            latex="x",
            source="s",
            status="ok",
        )
        event.latex = "y"
        self.assertEqual(event.latex, "y")


class TestClipboardImage(unittest.TestCase):
    def test_create_with_bytes(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        self.assertEqual(img.image_bytes, b"fake")
        self.assertEqual(img.width, 100)
        self.assertEqual(img.height, 100)
        self.assertEqual(img.fingerprint, "")

    def test_fingerprint_field(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100, fingerprint="abc123")
        self.assertEqual(img.fingerprint, "abc123")

    def test_default_pil_image_none(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        self.assertIsNone(img._pil_image)

    def test_slots_prevents_arbitrary_attributes(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        with self.assertRaises(AttributeError):
            img.arbitrary_attr = "fail"

    def test_empty_bytes(self):
        img = ClipboardImage(image_bytes=b"", width=0, height=0)
        self.assertEqual(img.image_bytes, b"")
        self.assertEqual(img.width, 0)

    def test_large_bytes(self):
        large_bytes = b"x" * 1024 * 1024
        img = ClipboardImage(image_bytes=large_bytes, width=1920, height=1080)
        self.assertEqual(len(img.image_bytes), 1024 * 1024)

    def test_zero_dimensions(self):
        img = ClipboardImage(image_bytes=b"fake", width=0, height=0)
        self.assertEqual(img.width, 0)
        self.assertEqual(img.height, 0)

    def test_repr_excludes_pil_image(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        r = repr(img)
        self.assertNotIn("_pil_image", r)

    def test_get_pil_image_returns_image(self):
        try:
            from PIL import Image
            import io

            img_data = io.BytesIO()
            Image.new("RGB", (10, 10), color="red").save(img_data, format="PNG")
            img_bytes = img_data.getvalue()

            img = ClipboardImage(image_bytes=img_bytes, width=10, height=10)
            pil_img = img.get_pil_image()
            self.assertIsNotNone(pil_img)
            self.assertEqual(pil_img.size, (10, 10))
        except ImportError:
            self.skipTest("PIL not available")

    def test_get_pil_image_no_cache(self):
        try:
            from PIL import Image
            import io

            img_data = io.BytesIO()
            Image.new("RGB", (10, 10), color="red").save(img_data, format="PNG")
            img_bytes = img_data.getvalue()

            img = ClipboardImage(image_bytes=img_bytes, width=10, height=10)
            pil1 = img.get_pil_image()
            pil2 = img.get_pil_image()
            self.assertIsNotNone(pil1)
            self.assertIsNotNone(pil2)
            self.assertEqual(pil1.size, pil2.size)
        except ImportError:
            self.skipTest("PIL not available")


class TestOcrProcessor(unittest.TestCase):
    def test_process_image_raises_not_implemented(self):
        processor = OcrProcessor()
        with self.assertRaises(NotImplementedError):
            processor.process_image(b"fake", {})

    def test_process_image_no_context(self):
        processor = OcrProcessor()
        with self.assertRaises(NotImplementedError):
            processor.process_image(b"fake")

    def test_subclass_must_implement(self):
        class MyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "result"

        processor = MyProcessor()
        result = processor.process_image(b"fake", {})
        self.assertEqual(result, "result")

    def test_subclass_with_dict_context(self):
        class MyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return context.get("key", "default")

        processor = MyProcessor()
        result = processor.process_image(b"fake", {"key": "value"})
        self.assertEqual(result, "value")


if __name__ == "__main__":
    unittest.main()
