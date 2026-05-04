from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.clipboard import (
    _MAX_IMAGE_DIMENSION,
    _MAX_IMAGE_SIZE,
    _try_load_image_from_file_list,
    copy_text_to_clipboard,
    image_hash,
    set_publishing_callback,
)


# ---------------------------------------------------------------------------
# image_hash
# ---------------------------------------------------------------------------

class TestImageHash(unittest.TestCase):
    """Tests for image_hash(image_bytes)."""

    def test_consistent_hash(self):
        data = b"test image data"
        h1 = image_hash(data)
        h2 = image_hash(data)
        self.assertEqual(h1, h2)

    def test_different_data_different_hash(self):
        h1 = image_hash(b"data1")
        h2 = image_hash(b"data2")
        self.assertNotEqual(h1, h2)

    def test_hash_is_hex_string(self):
        h = image_hash(b"test")
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_hash_length(self):
        h = image_hash(b"test")
        self.assertEqual(len(h), 64)

    def test_empty_data(self):
        h = image_hash(b"")
        self.assertEqual(len(h), 64)

    def test_large_data(self):
        h = image_hash(b"x" * 1024 * 1024)
        self.assertEqual(len(h), 64)

    def test_returns_string(self):
        h = image_hash(b"test")
        self.assertIsInstance(h, str)

    def test_deterministic_across_calls(self):
        """Same input should always produce the same hash."""
        data = b"deterministic test data 12345"
        hashes = [image_hash(data) for _ in range(10)]
        self.assertEqual(len(set(hashes)), 1)

    def test_known_sha256_value(self):
        """Verify against known SHA-256 hash of empty string."""
        import hashlib
        expected = hashlib.sha256(b"").hexdigest()
        self.assertEqual(image_hash(b""), expected)

    def test_binary_data(self):
        h = image_hash(bytes(range(256)))
        self.assertEqual(len(h), 64)

    def test_unicode_bytes(self):
        h = image_hash("unicode text".encode("utf-8"))
        self.assertEqual(len(h), 64)


# ---------------------------------------------------------------------------
# set_publishing_callback
# ---------------------------------------------------------------------------

class TestSetPublishingCallback(unittest.TestCase):
    """Tests for set_publishing_callback(callback)."""

    def tearDown(self):
        set_publishing_callback(None)

    def test_set_callback(self):
        called = []
        set_publishing_callback(lambda is_pub: called.append(is_pub))
        self.assertEqual(len(called), 0)

    def test_set_callback_none(self):
        set_publishing_callback(None)
        set_publishing_callback(None)

    def test_replace_callback(self):
        calls1 = []
        calls2 = []
        set_publishing_callback(lambda is_pub: calls1.append(is_pub))
        set_publishing_callback(lambda is_pub: calls2.append(is_pub))
        # Only the second callback should be active
        with patch("platex_client.clipboard.set_text"):
            copy_text_to_clipboard("test")
        self.assertEqual(len(calls1), 0)
        self.assertTrue(len(calls2) > 0)


# ---------------------------------------------------------------------------
# copy_text_to_clipboard
# ---------------------------------------------------------------------------

class TestCopyTextToClipboard(unittest.TestCase):
    """Tests for copy_text_to_clipboard(text)."""

    def tearDown(self):
        set_publishing_callback(None)

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_calls_set_text(self, mock_set_text):
        copy_text_to_clipboard("hello")
        mock_set_text.assert_called_once_with("hello")

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_with_publishing_callback(self, mock_set_text):
        calls = []
        set_publishing_callback(lambda is_pub: calls.append(is_pub))
        copy_text_to_clipboard("hello")
        mock_set_text.assert_called_once_with("hello")
        self.assertIn(True, calls)
        self.assertIn(False, calls)

    @patch("platex_client.clipboard.set_text", side_effect=RuntimeError("clipboard error"))
    def test_copy_text_handles_set_text_error(self, mock_set_text):
        copy_text_to_clipboard("hello")

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_publishing_callback_exception(self, mock_set_text):
        set_publishing_callback(lambda is_pub: (_ for _ in ()).throw(RuntimeError("callback error")))
        copy_text_to_clipboard("hello")
        mock_set_text.assert_called_once_with("hello")

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_empty_string(self, mock_set_text):
        copy_text_to_clipboard("")
        mock_set_text.assert_called_once_with("")

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_unicode(self, mock_set_text):
        copy_text_to_clipboard("中文测试 🧪")
        mock_set_text.assert_called_once_with("中文测试 🧪")

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_publishing_callback_order(self, mock_set_text):
        """Publishing callback should be called with True before set_text and False after."""
        order = []
        set_publishing_callback(lambda is_pub: order.append("pub" if is_pub else "unpub"))
        mock_set_text.side_effect = lambda t: order.append("set_text")
        copy_text_to_clipboard("test")
        self.assertEqual(order, ["pub", "set_text", "unpub"])

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_no_callback(self, mock_set_text):
        """Without a publishing callback, set_text should still be called."""
        set_publishing_callback(None)
        copy_text_to_clipboard("test")
        mock_set_text.assert_called_once_with("test")

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_callback_false_on_error(self, mock_set_text):
        """Even when set_text raises, the callback should still be called with False."""
        calls = []
        set_publishing_callback(lambda is_pub: calls.append(is_pub))
        mock_set_text.side_effect = RuntimeError("error")
        copy_text_to_clipboard("test")
        self.assertIn(True, calls)
        self.assertIn(False, calls)

    @patch("platex_client.clipboard.set_text")
    def test_copy_text_long_string(self, mock_set_text):
        long_text = "x" * 100000
        copy_text_to_clipboard(long_text)
        mock_set_text.assert_called_once_with(long_text)


# ---------------------------------------------------------------------------
# grab_image_clipboard
# ---------------------------------------------------------------------------

class TestGrabImageClipboard(unittest.TestCase):
    """Tests for grab_image_clipboard()."""

    @patch("platex_client.clipboard.ImageGrab.grabclipboard", return_value=None)
    def test_no_image_returns_none(self, mock_grab):
        from platex_client.clipboard import grab_image_clipboard
        result = grab_image_clipboard()
        self.assertIsNone(result)

    @patch("platex_client.clipboard.ImageGrab.grabclipboard", return_value="not an image")
    def test_non_image_returns_none(self, mock_grab):
        from platex_client.clipboard import grab_image_clipboard
        result = grab_image_clipboard()
        self.assertIsNone(result)

    @patch("platex_client.clipboard.ImageGrab.grabclipboard", side_effect=OSError("clipboard error"))
    def test_os_error_retries(self, mock_grab):
        from platex_client.clipboard import grab_image_clipboard
        result = grab_image_clipboard()
        self.assertIsNone(result)
        self.assertGreater(mock_grab.call_count, 1)


# ---------------------------------------------------------------------------
# _try_load_image_from_file_list
# ---------------------------------------------------------------------------

class TestTryLoadImageFromFileList(unittest.TestCase):
    """Tests for _try_load_image_from_file_list(file_list)."""

    def test_empty_list(self):
        result = _try_load_image_from_file_list([])
        self.assertIsNone(result)

    def test_non_string_items(self):
        result = _try_load_image_from_file_list([42, None, 3.14])
        self.assertIsNone(result)

    def test_nonexistent_file(self):
        result = _try_load_image_from_file_list(["/nonexistent/path/image.png"])
        self.assertIsNone(result)

    def test_non_image_extension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / "readme.txt"
            txt_path.write_bytes(b"not an image")
            result = _try_load_image_from_file_list([str(txt_path)])
            self.assertIsNone(result)

    def test_valid_png_file(self):
        """Test loading a valid PNG image from file list."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "test.png"
            img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
            img.save(img_path)
            result = _try_load_image_from_file_list([str(img_path)])
            self.assertIsNotNone(result)
            self.assertEqual(result.size, (10, 10))

    def test_valid_jpg_file(self):
        """Test loading a valid JPEG image from file list."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "test.jpg"
            img = Image.new("RGB", (10, 10), (255, 0, 0))
            img.save(img_path)
            result = _try_load_image_from_file_list([str(img_path)])
            self.assertIsNotNone(result)

    def test_valid_bmp_file(self):
        """Test loading a valid BMP image from file list."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "test.bmp"
            img = Image.new("RGB", (10, 10), (0, 255, 0))
            img.save(img_path)
            result = _try_load_image_from_file_list([str(img_path)])
            self.assertIsNotNone(result)

    def test_returns_first_valid_image(self):
        """Should return the first valid image from the list."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path1 = Path(tmpdir) / "first.png"
            img_path2 = Path(tmpdir) / "second.png"
            Image.new("RGB", (10, 10), (255, 0, 0)).save(img_path1)
            Image.new("RGB", (20, 20), (0, 255, 0)).save(img_path2)
            result = _try_load_image_from_file_list([str(img_path1), str(img_path2)])
            self.assertIsNotNone(result)
            self.assertEqual(result.size, (10, 10))

    def test_skips_non_image_before_valid(self):
        """Should skip non-image files and find the valid image."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / "readme.txt"
            txt_path.write_text("not an image")
            img_path = Path(tmpdir) / "image.png"
            Image.new("RGB", (10, 10), (0, 0, 255)).save(img_path)
            result = _try_load_image_from_file_list([str(txt_path), str(img_path)])
            self.assertIsNotNone(result)

    def test_converts_to_rgba(self):
        """Result should be converted to RGBA mode."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "test.png"
            Image.new("RGB", (10, 10), (128, 128, 128)).save(img_path)
            result = _try_load_image_from_file_list([str(img_path)])
            self.assertIsNotNone(result)
            self.assertEqual(result.mode, "RGBA")

    def test_supported_extensions(self):
        """Test that all supported extensions are recognized."""
        from PIL import Image
        supported = [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"]
        with tempfile.TemporaryDirectory() as tmpdir:
            for ext in supported:
                img_path = Path(tmpdir) / f"test{ext}"
                if ext == ".jpg" or ext == ".jpeg":
                    img = Image.new("RGB", (10, 10), (255, 0, 0))
                elif ext == ".bmp":
                    img = Image.new("RGB", (10, 10), (0, 255, 0))
                elif ext == ".gif":
                    img = Image.new("P", (10, 10))
                elif ext in (".tiff", ".tif"):
                    img = Image.new("RGB", (10, 10), (0, 0, 255))
                elif ext == ".webp":
                    img = Image.new("RGB", (10, 10), (128, 128, 128))
                else:
                    img = Image.new("RGBA", (10, 10))
                img.save(img_path)
                result = _try_load_image_from_file_list([str(img_path)])
                self.assertIsNotNone(result, f"Failed to load {ext} file")

    def test_case_insensitive_extension(self):
        """Extension matching should be case-insensitive."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "test.PNG"
            Image.new("RGBA", (10, 10)).save(img_path)
            result = _try_load_image_from_file_list([str(img_path)])
            self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestClipboardConstants(unittest.TestCase):
    """Tests for module-level constants."""

    def test_max_image_size(self):
        self.assertEqual(_MAX_IMAGE_SIZE, 20 * 1024 * 1024)

    def test_max_image_dimension(self):
        self.assertEqual(_MAX_IMAGE_DIMENSION, 16384)


if __name__ == "__main__":
    unittest.main()
