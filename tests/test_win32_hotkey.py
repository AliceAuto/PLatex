from __future__ import annotations

import unittest

from platex_client.win32_hotkey import Win32HotkeyListener, _parse_hotkey_to_vk


class TestWin32HotkeyParseHotkey(unittest.TestCase):
    def _make_listener(self):
        return Win32HotkeyListener()

    def test_parse_simple_key(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("A")
        self.assertIsNotNone(result)

    def test_parse_ctrl_a(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Ctrl+A")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0002)
        self.assertEqual(vk, 0x41)

    def test_parse_ctrl_alt_a(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Ctrl+Alt+A")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0002)
        self.assertTrue(modifiers & 0x0001)

    def test_parse_ctrl_shift_a(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Ctrl+Shift+A")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0002)
        self.assertTrue(modifiers & 0x0004)

    def test_parse_ctrl_alt_shift_a(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Ctrl+Alt+Shift+A")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0002)
        self.assertTrue(modifiers & 0x0001)
        self.assertTrue(modifiers & 0x0004)

    def test_parse_f1(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("F1")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x70)

    def test_parse_ctrl_f1(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Ctrl+F1")
        self.assertIsNotNone(result)

    def test_parse_number_key(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Ctrl+1")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x31)

    def test_parse_lowercase(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("ctrl+a")
        self.assertIsNotNone(result)

    def test_parse_space(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Space")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x20)

    def test_parse_enter(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Enter")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x0D)

    def test_parse_escape(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Escape")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x1B)

    def test_parse_tab(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Tab")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x09)

    def test_parse_backspace(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Backspace")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x08)

    def test_parse_delete(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Delete")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x2E)

    def test_parse_win_key(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Win+A")
        self.assertIsNotNone(result)
        modifiers, _ = result
        self.assertTrue(modifiers & 0x0008)

    def test_parse_empty_returns_none(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("")
        self.assertIsNone(result)

    def test_parse_bare_modifier_returns_none(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Ctrl")
        self.assertIsNone(result)

    def test_parse_function_keys_range(self):
        listener = self._make_listener()
        for i in range(1, 13):
            result = listener._parse_hotkey(f"F{i}")
            self.assertIsNotNone(result, f"Failed for F{i}")

    def test_parse_ctrl_function_keys(self):
        listener = self._make_listener()
        for i in range(1, 13):
            result = listener._parse_hotkey(f"Ctrl+F{i}")
            self.assertIsNotNone(result, f"Failed for Ctrl+F{i}")

    def test_parse_home_key(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Home")
        self.assertIsNotNone(result)

    def test_parse_end_key(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("End")
        self.assertIsNotNone(result)

    def test_parse_arrow_keys(self):
        listener = self._make_listener()
        for key in ("Up", "Down", "Left", "Right"):
            result = listener._parse_hotkey(key)
            self.assertIsNotNone(result, f"Failed for {key}")

    def test_parse_page_up(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Page_Up")
        self.assertIsNotNone(result)

    def test_parse_page_down(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Page_Down")
        self.assertIsNotNone(result)

    def test_parse_insert(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Insert")
        self.assertIsNotNone(result)

    def test_parse_caps_lock(self):
        listener = self._make_listener()
        result = listener._parse_hotkey("Caps_Lock")
        self.assertIsNotNone(result)

    def test_parse_numpad_keys(self):
        listener = self._make_listener()
        for i in range(10):
            result = listener._parse_hotkey(f"Numpad{i}")
            self.assertIsNotNone(result, f"Failed for Numpad{i}")


class TestParseHotkeyToVk(unittest.TestCase):
    def test_parse_vk_simple(self):
        result = _parse_hotkey_to_vk("A")
        self.assertIsNotNone(result)

    def test_parse_vk_ctrl_a(self):
        result = _parse_hotkey_to_vk("Ctrl+A")
        self.assertIsNotNone(result)

    def test_parse_vk_returns_tuple(self):
        result = _parse_hotkey_to_vk("Ctrl+A")
        self.assertIsInstance(result, tuple)

    def test_parse_vk_has_modifiers_and_key(self):
        result = _parse_hotkey_to_vk("Ctrl+A")
        self.assertEqual(len(result), 2)

    def test_parse_vk_modifiers(self):
        modifiers, vk = _parse_hotkey_to_vk("Ctrl+Alt+Shift+A")
        self.assertIsNotNone(modifiers)

    def test_parse_vk_f1(self):
        modifiers, vk = _parse_hotkey_to_vk("F1")
        self.assertIsNotNone(vk)
        self.assertEqual(vk, 0x70)

    def test_parse_vk_empty_returns_none(self):
        result = _parse_hotkey_to_vk("")
        self.assertIsNone(result)

    def test_parse_vk_bare_modifier_returns_none(self):
        result = _parse_hotkey_to_vk("Ctrl")
        self.assertIsNone(result)


class TestWin32HotkeyListenerInit(unittest.TestCase):
    def test_init_no_args(self):
        listener = Win32HotkeyListener()
        self.assertIsNotNone(listener)

    def test_get_status(self):
        listener = Win32HotkeyListener()
        status = listener.get_status()
        self.assertIsInstance(status, dict)
        self.assertIn("registered", status)
        self.assertIn("failed", status)
        self.assertIn("running", status)


if __name__ == "__main__":
    unittest.main()
