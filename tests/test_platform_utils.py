from __future__ import annotations

import sys
import unittest

from platex_client.platform_utils import IS_WINDOWS


class TestPlatformUtils(unittest.TestCase):
    def test_is_windows_returns_bool(self):
        self.assertIsInstance(IS_WINDOWS, bool)

    def test_is_windows_on_windows(self):
        if sys.platform == "win32":
            self.assertTrue(IS_WINDOWS)
        else:
            self.assertFalse(IS_WINDOWS)


if __name__ == "__main__":
    unittest.main()
