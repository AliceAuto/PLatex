from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from platex_client.clipboard import (
    copy_text_to_clipboard,
    image_hash,
    set_publishing_callback,
)


class TestImageHash(unittest.TestCase):
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


class TestSetPublishingCallback(unittest.TestCase):
    def tearDown(self):
        set_publishing_callback(None)

    def test_set_callback(self):
        called = []
        set_publishing_callback(lambda is_pub: called.append(is_pub))
        self.assertEqual(len(called), 0)

    def test_set_callback_none(self):
        set_publishing_callback(None)
        set_publishing_callback(None)


class TestCopyTextToClipboard(unittest.TestCase):
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


class TestGrabImageClipboard(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
