from __future__ import annotations

import unittest

from platex_client.hotkey_listener import convert_hotkey_str
from platex_client.win32_hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    Win32HotkeyListener,
    _parse_hotkey_to_vk,
)


# ---------------------------------------------------------------------------
# Helper: create a Win32HotkeyListener for _parse_hotkey testing
# ---------------------------------------------------------------------------


def _make_listener():
    return Win32HotkeyListener()


# ---------------------------------------------------------------------------
# _parse_hotkey tests (Win32HotkeyListener._parse_hotkey)
# ---------------------------------------------------------------------------


class TestParseHotkeyModifierCombinations(unittest.TestCase):
    """Tests for _parse_hotkey with various modifier combinations."""

    def test_ctrl_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<ctrl>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x41)

    def test_alt_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<alt>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_ALT)
        self.assertEqual(vk, 0x41)

    def test_shift_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<shift>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_SHIFT)
        self.assertEqual(vk, 0x41)

    def test_win_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<cmd>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_WIN)
        self.assertEqual(vk, 0x41)

    def test_ctrl_alt_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<ctrl>+<alt>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT)
        self.assertEqual(vk, 0x41)

    def test_ctrl_shift_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<ctrl>+<shift>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_SHIFT)
        self.assertEqual(vk, 0x41)

    def test_ctrl_alt_shift_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<ctrl>+<alt>+<shift>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT | MOD_SHIFT)
        self.assertEqual(vk, 0x41)

    def test_ctrl_win_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<ctrl>+<cmd>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_WIN)
        self.assertEqual(vk, 0x41)

    def test_all_modifiers(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<ctrl>+<alt>+<shift>+<cmd>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN)
        self.assertEqual(vk, 0x41)

    def test_modifier_name_ctrl(self):
        listener = _make_listener()
        result = listener._parse_hotkey("ctrl+a")
        self.assertIsNotNone(result)
        modifiers, _ = result
        self.assertEqual(modifiers, MOD_CONTROL)

    def test_modifier_name_control(self):
        listener = _make_listener()
        result = listener._parse_hotkey("control+a")
        self.assertIsNotNone(result)
        modifiers, _ = result
        self.assertEqual(modifiers, MOD_CONTROL)

    def test_modifier_name_win(self):
        listener = _make_listener()
        result = listener._parse_hotkey("win+a")
        self.assertIsNotNone(result)
        modifiers, _ = result
        self.assertEqual(modifiers, MOD_WIN)

    def test_modifier_name_cmd(self):
        listener = _make_listener()
        result = listener._parse_hotkey("cmd+a")
        self.assertIsNotNone(result)
        modifiers, _ = result
        self.assertEqual(modifiers, MOD_WIN)

    def test_modifier_name_super(self):
        listener = _make_listener()
        result = listener._parse_hotkey("super+a")
        self.assertIsNotNone(result)
        modifiers, _ = result
        self.assertEqual(modifiers, MOD_WIN)


class TestParseHotkeySingleKeys(unittest.TestCase):
    """Tests for _parse_hotkey with single keys (no modifiers)."""

    def test_single_letter_a(self):
        listener = _make_listener()
        result = listener._parse_hotkey("a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, 0)
        self.assertEqual(vk, 0x41)

    def test_single_letter_z(self):
        listener = _make_listener()
        result = listener._parse_hotkey("z")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x5A)

    def test_single_number_0(self):
        listener = _make_listener()
        result = listener._parse_hotkey("0")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x30)

    def test_single_number_9(self):
        listener = _make_listener()
        result = listener._parse_hotkey("9")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x39)

    def test_space(self):
        listener = _make_listener()
        result = listener._parse_hotkey("space")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x20)

    def test_enter(self):
        listener = _make_listener()
        result = listener._parse_hotkey("enter")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x0D)

    def test_return(self):
        listener = _make_listener()
        result = listener._parse_hotkey("return")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x0D)

    def test_tab(self):
        listener = _make_listener()
        result = listener._parse_hotkey("tab")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x09)

    def test_escape(self):
        listener = _make_listener()
        result = listener._parse_hotkey("escape")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x1B)

    def test_esc(self):
        listener = _make_listener()
        result = listener._parse_hotkey("esc")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x1B)

    def test_backspace(self):
        listener = _make_listener()
        result = listener._parse_hotkey("backspace")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x08)

    def test_delete(self):
        listener = _make_listener()
        result = listener._parse_hotkey("delete")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x2E)

    def test_del(self):
        listener = _make_listener()
        result = listener._parse_hotkey("del")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x2E)

    def test_insert(self):
        listener = _make_listener()
        result = listener._parse_hotkey("insert")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x2D)

    def test_ins(self):
        listener = _make_listener()
        result = listener._parse_hotkey("ins")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x2D)

    def test_home(self):
        listener = _make_listener()
        result = listener._parse_hotkey("home")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x24)

    def test_end(self):
        listener = _make_listener()
        result = listener._parse_hotkey("end")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x23)

    def test_page_up(self):
        listener = _make_listener()
        result = listener._parse_hotkey("page_up")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x21)

    def test_page_down(self):
        listener = _make_listener()
        result = listener._parse_hotkey("page_down")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x22)

    def test_up(self):
        listener = _make_listener()
        result = listener._parse_hotkey("up")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x26)

    def test_down(self):
        listener = _make_listener()
        result = listener._parse_hotkey("down")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x28)

    def test_left(self):
        listener = _make_listener()
        result = listener._parse_hotkey("left")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x25)

    def test_right(self):
        listener = _make_listener()
        result = listener._parse_hotkey("right")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x27)

    def test_caps_lock(self):
        listener = _make_listener()
        result = listener._parse_hotkey("caps_lock")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x14)

    def test_capslock(self):
        listener = _make_listener()
        result = listener._parse_hotkey("capslock")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x14)

    def test_num_lock(self):
        listener = _make_listener()
        result = listener._parse_hotkey("num_lock")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x90)

    def test_scroll_lock(self):
        listener = _make_listener()
        result = listener._parse_hotkey("scroll_lock")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x91)

    def test_print_screen(self):
        listener = _make_listener()
        result = listener._parse_hotkey("print_screen")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x2C)

    def test_pause(self):
        listener = _make_listener()
        result = listener._parse_hotkey("pause")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x13)

    def test_menu(self):
        listener = _make_listener()
        result = listener._parse_hotkey("menu")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x5D)


class TestParseHotkeyFKeys(unittest.TestCase):
    """Tests for _parse_hotkey with function keys."""

    def test_f1(self):
        listener = _make_listener()
        result = listener._parse_hotkey("f1")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x70)

    def test_f12(self):
        listener = _make_listener()
        result = listener._parse_hotkey("f12")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x7B)

    def test_f13(self):
        listener = _make_listener()
        result = listener._parse_hotkey("f13")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x7C)

    def test_f24(self):
        listener = _make_listener()
        result = listener._parse_hotkey("f24")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x87)

    def test_all_f_keys(self):
        listener = _make_listener()
        expected_vks = {
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
            "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
            "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
            "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F,
            "f17": 0x80, "f18": 0x81, "f19": 0x82, "f20": 0x83,
            "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
        }
        for key, expected_vk in expected_vks.items():
            result = listener._parse_hotkey(key)
            self.assertIsNotNone(result, f"Failed for {key}")
            _, vk = result
            self.assertEqual(vk, expected_vk, f"Wrong VK for {key}")

    def test_ctrl_f1(self):
        listener = _make_listener()
        result = listener._parse_hotkey("ctrl+f1")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x70)


class TestParseHotkeyNumpadKeys(unittest.TestCase):
    """Tests for _parse_hotkey with numpad keys."""

    def test_numpad0(self):
        listener = _make_listener()
        result = listener._parse_hotkey("numpad0")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x60)

    def test_numpad9(self):
        listener = _make_listener()
        result = listener._parse_hotkey("numpad9")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x69)

    def test_all_numpad_digits(self):
        listener = _make_listener()
        for i in range(10):
            result = listener._parse_hotkey(f"numpad{i}")
            self.assertIsNotNone(result, f"Failed for numpad{i}")
            _, vk = result
            self.assertEqual(vk, 0x60 + i, f"Wrong VK for numpad{i}")

    def test_multiply(self):
        listener = _make_listener()
        result = listener._parse_hotkey("multiply")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x6A)

    def test_add(self):
        listener = _make_listener()
        result = listener._parse_hotkey("add")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x6B)

    def test_separator(self):
        listener = _make_listener()
        result = listener._parse_hotkey("separator")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x6C)

    def test_subtract(self):
        listener = _make_listener()
        result = listener._parse_hotkey("subtract")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x6D)

    def test_decimal(self):
        listener = _make_listener()
        result = listener._parse_hotkey("decimal")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x6E)

    def test_divide(self):
        listener = _make_listener()
        result = listener._parse_hotkey("divide")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x6F)


class TestParseHotkeyPunctuationKeys(unittest.TestCase):
    """Tests for _parse_hotkey with punctuation keys."""

    def test_semicolon(self):
        listener = _make_listener()
        result = listener._parse_hotkey(";")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBA)

    def test_equals(self):
        listener = _make_listener()
        result = listener._parse_hotkey("=")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBB)

    def test_comma(self):
        listener = _make_listener()
        result = listener._parse_hotkey(",")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBC)

    def test_minus(self):
        listener = _make_listener()
        result = listener._parse_hotkey("-")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBD)

    def test_period(self):
        listener = _make_listener()
        result = listener._parse_hotkey(".")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBE)

    def test_slash(self):
        listener = _make_listener()
        result = listener._parse_hotkey("/")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBF)

    def test_backtick(self):
        listener = _make_listener()
        result = listener._parse_hotkey("`")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xC0)

    def test_left_bracket(self):
        listener = _make_listener()
        result = listener._parse_hotkey("[")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDB)

    def test_backslash(self):
        listener = _make_listener()
        result = listener._parse_hotkey("\\")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDC)

    def test_right_bracket(self):
        listener = _make_listener()
        result = listener._parse_hotkey("]")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDD)

    def test_single_quote(self):
        listener = _make_listener()
        result = listener._parse_hotkey("'")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDE)

    def test_ctrl_semicolon(self):
        listener = _make_listener()
        result = listener._parse_hotkey("ctrl+;")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0xBA)


class TestParseHotkeyBareModifiers(unittest.TestCase):
    """Tests for _parse_hotkey with bare modifiers (should return None)."""

    def test_bare_ctrl(self):
        listener = _make_listener()
        result = listener._parse_hotkey("ctrl")
        self.assertIsNone(result)

    def test_bare_alt(self):
        listener = _make_listener()
        result = listener._parse_hotkey("alt")
        self.assertIsNone(result)

    def test_bare_shift(self):
        listener = _make_listener()
        result = listener._parse_hotkey("shift")
        self.assertIsNone(result)

    def test_bare_win(self):
        listener = _make_listener()
        result = listener._parse_hotkey("win")
        self.assertIsNone(result)

    def test_bare_cmd(self):
        listener = _make_listener()
        result = listener._parse_hotkey("cmd")
        self.assertIsNone(result)

    def test_bare_super(self):
        listener = _make_listener()
        result = listener._parse_hotkey("super")
        self.assertIsNone(result)

    def test_bare_control(self):
        listener = _make_listener()
        result = listener._parse_hotkey("control")
        self.assertIsNone(result)

    def test_bare_ctrl_angle_brackets(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<ctrl>")
        self.assertIsNone(result)

    def test_bare_alt_angle_brackets(self):
        listener = _make_listener()
        result = listener._parse_hotkey("<alt>")
        self.assertIsNone(result)


class TestParseHotkeyEmptyAndInvalid(unittest.TestCase):
    """Tests for _parse_hotkey with empty and invalid inputs."""

    def test_empty_string(self):
        listener = _make_listener()
        result = listener._parse_hotkey("")
        self.assertIsNone(result)

    def test_only_spaces(self):
        listener = _make_listener()
        result = listener._parse_hotkey("   ")
        self.assertIsNone(result)

    def test_unknown_key(self):
        listener = _make_listener()
        result = listener._parse_hotkey("unknown_key_xyz")
        self.assertIsNone(result)

    def test_only_plus(self):
        listener = _make_listener()
        result = listener._parse_hotkey("+")
        self.assertIsNone(result)


class TestParseHotkeyMediaKeys(unittest.TestCase):
    """Tests for _parse_hotkey with media keys."""

    def test_volume_down(self):
        listener = _make_listener()
        result = listener._parse_hotkey("volume_down")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xAE)

    def test_volume_mute(self):
        listener = _make_listener()
        result = listener._parse_hotkey("volume_mute")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xAD)

    def test_volume_up(self):
        listener = _make_listener()
        result = listener._parse_hotkey("volume_up")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xAF)

    def test_media_next(self):
        listener = _make_listener()
        result = listener._parse_hotkey("media_next")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xB0)

    def test_media_prev(self):
        listener = _make_listener()
        result = listener._parse_hotkey("media_prev")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xB1)

    def test_media_stop(self):
        listener = _make_listener()
        result = listener._parse_hotkey("media_stop")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xB2)

    def test_media_play_pause(self):
        listener = _make_listener()
        result = listener._parse_hotkey("media_play_pause")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xB3)

    def test_media_play(self):
        listener = _make_listener()
        result = listener._parse_hotkey("media_play")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xB3)

    def test_launch_mail(self):
        listener = _make_listener()
        result = listener._parse_hotkey("launch_mail")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xB4)

    def test_launch_media(self):
        listener = _make_listener()
        result = listener._parse_hotkey("launch_media")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xB5)


class TestParseHotkeyBrowserKeys(unittest.TestCase):
    """Tests for _parse_hotkey with browser keys."""

    def test_browser_back(self):
        listener = _make_listener()
        result = listener._parse_hotkey("browser_back")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xA6)

    def test_browser_forward(self):
        listener = _make_listener()
        result = listener._parse_hotkey("browser_forward")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xA7)

    def test_browser_refresh(self):
        listener = _make_listener()
        result = listener._parse_hotkey("browser_refresh")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xA8)

    def test_browser_stop(self):
        listener = _make_listener()
        result = listener._parse_hotkey("browser_stop")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xA9)

    def test_browser_search(self):
        listener = _make_listener()
        result = listener._parse_hotkey("browser_search")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xAA)

    def test_browser_favorites(self):
        listener = _make_listener()
        result = listener._parse_hotkey("browser_favorites")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xAB)

    def test_browser_home(self):
        listener = _make_listener()
        result = listener._parse_hotkey("browser_home")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xAC)


# ---------------------------------------------------------------------------
# _parse_hotkey_to_vk tests (standalone function)
# ---------------------------------------------------------------------------


class TestParseHotkeyToVkModifierCombinations(unittest.TestCase):
    """Tests for _parse_hotkey_to_vk with various modifier combinations."""

    def test_ctrl_a(self):
        result = _parse_hotkey_to_vk("<ctrl>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x41)

    def test_alt_a(self):
        result = _parse_hotkey_to_vk("<alt>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_ALT)
        self.assertEqual(vk, 0x41)

    def test_shift_a(self):
        result = _parse_hotkey_to_vk("<shift>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_SHIFT)
        self.assertEqual(vk, 0x41)

    def test_ctrl_alt_a(self):
        result = _parse_hotkey_to_vk("<ctrl>+<alt>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT)
        self.assertEqual(vk, 0x41)

    def test_ctrl_alt_shift_a(self):
        result = _parse_hotkey_to_vk("<ctrl>+<alt>+<shift>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT | MOD_SHIFT)
        self.assertEqual(vk, 0x41)

    def test_ctrl_win_a(self):
        result = _parse_hotkey_to_vk("<ctrl>+<cmd>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_WIN)
        self.assertEqual(vk, 0x41)

    def test_all_modifiers(self):
        result = _parse_hotkey_to_vk("<ctrl>+<alt>+<shift>+<cmd>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN)
        self.assertEqual(vk, 0x41)


class TestParseHotkeyToVkSingleKeys(unittest.TestCase):
    """Tests for _parse_hotkey_to_vk with single keys."""

    def test_a(self):
        result = _parse_hotkey_to_vk("a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, 0)
        self.assertEqual(vk, 0x41)

    def test_z(self):
        result = _parse_hotkey_to_vk("z")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x5A)

    def test_0(self):
        result = _parse_hotkey_to_vk("0")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x30)

    def test_9(self):
        result = _parse_hotkey_to_vk("9")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x39)

    def test_space(self):
        result = _parse_hotkey_to_vk("space")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x20)

    def test_enter(self):
        result = _parse_hotkey_to_vk("enter")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x0D)

    def test_f1(self):
        result = _parse_hotkey_to_vk("f1")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x70)

    def test_f12(self):
        result = _parse_hotkey_to_vk("f12")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x7B)


class TestParseHotkeyToVkPunctuationKeys(unittest.TestCase):
    """Tests for _parse_hotkey_to_vk with punctuation keys."""

    def test_semicolon(self):
        result = _parse_hotkey_to_vk(";")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBA)

    def test_equals(self):
        result = _parse_hotkey_to_vk("=")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBB)

    def test_comma(self):
        result = _parse_hotkey_to_vk(",")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBC)

    def test_minus(self):
        result = _parse_hotkey_to_vk("-")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBD)

    def test_period(self):
        result = _parse_hotkey_to_vk(".")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBE)

    def test_slash(self):
        result = _parse_hotkey_to_vk("/")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBF)

    def test_backtick(self):
        result = _parse_hotkey_to_vk("`")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xC0)

    def test_left_bracket(self):
        result = _parse_hotkey_to_vk("[")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDB)

    def test_backslash(self):
        result = _parse_hotkey_to_vk("\\")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDC)

    def test_right_bracket(self):
        result = _parse_hotkey_to_vk("]")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDD)

    def test_single_quote(self):
        result = _parse_hotkey_to_vk("'")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xDE)


class TestParseHotkeyToVkNumpadKeys(unittest.TestCase):
    """Tests for _parse_hotkey_to_vk with numpad keys."""

    def test_numpad0(self):
        result = _parse_hotkey_to_vk("numpad0")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x60)

    def test_numpad9(self):
        result = _parse_hotkey_to_vk("numpad9")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x69)

    def test_all_numpad_digits(self):
        for i in range(10):
            result = _parse_hotkey_to_vk(f"numpad{i}")
            self.assertIsNotNone(result, f"Failed for numpad{i}")
            _, vk = result
            self.assertEqual(vk, 0x60 + i, f"Wrong VK for numpad{i}")


class TestParseHotkeyToVkBareModifiers(unittest.TestCase):
    """Tests for _parse_hotkey_to_vk with bare modifiers (should return None)."""

    def test_bare_ctrl(self):
        result = _parse_hotkey_to_vk("ctrl")
        self.assertIsNone(result)

    def test_bare_alt(self):
        result = _parse_hotkey_to_vk("alt")
        self.assertIsNone(result)

    def test_bare_shift(self):
        result = _parse_hotkey_to_vk("shift")
        self.assertIsNone(result)

    def test_bare_win(self):
        result = _parse_hotkey_to_vk("win")
        self.assertIsNone(result)

    def test_bare_cmd(self):
        result = _parse_hotkey_to_vk("cmd")
        self.assertIsNone(result)

    def test_bare_super(self):
        result = _parse_hotkey_to_vk("super")
        self.assertIsNone(result)

    def test_bare_control(self):
        result = _parse_hotkey_to_vk("control")
        self.assertIsNone(result)


class TestParseHotkeyToVkEmptyAndInvalid(unittest.TestCase):
    """Tests for _parse_hotkey_to_vk with empty and invalid inputs."""

    def test_empty_string(self):
        result = _parse_hotkey_to_vk("")
        self.assertIsNone(result)

    def test_only_spaces(self):
        result = _parse_hotkey_to_vk("   ")
        self.assertIsNone(result)

    def test_unknown_key(self):
        result = _parse_hotkey_to_vk("unknown_key_xyz")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Roundtrip: convert_hotkey_str -> _parse_hotkey_to_vk
# ---------------------------------------------------------------------------


class TestRoundtripConvertHotkeyStrToVk(unittest.TestCase):
    """Tests that convert_hotkey_str output can be parsed by _parse_hotkey_to_vk."""

    def test_ctrl_a_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+A")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x41)

    def test_ctrl_shift_f5_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+Shift+F5")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_SHIFT)
        self.assertEqual(vk, 0x74)

    def test_win_k_roundtrip(self):
        pynput_key = convert_hotkey_str("Win+K")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_WIN)
        self.assertEqual(vk, 0x4B)

    def test_ctrl_alt_delete_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+Alt+Delete")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT)
        self.assertEqual(vk, 0x2E)

    def test_ctrl_space_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+Space")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x20)

    def test_alt_enter_roundtrip(self):
        pynput_key = convert_hotkey_str("Alt+Enter")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_ALT)
        self.assertEqual(vk, 0x0D)

    def test_shift_tab_roundtrip(self):
        pynput_key = convert_hotkey_str("Shift+Tab")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_SHIFT)
        self.assertEqual(vk, 0x09)

    def test_ctrl_page_up_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+Page Up")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x21)

    def test_ctrl_f1_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+F1")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x70)

    def test_ctrl_alt_shift_f12_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+Alt+Shift+F12")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT | MOD_SHIFT)
        self.assertEqual(vk, 0x7B)

    def test_ctrl_1_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+1")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0x31)

    def test_ctrl_equals_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+=")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0xBB)

    def test_ctrl_minus_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+-")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0xBD)

    def test_ctrl_comma_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+,")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0xBC)

    def test_ctrl_semicolon_roundtrip(self):
        pynput_key = convert_hotkey_str("Ctrl+;")
        result = _parse_hotkey_to_vk(pynput_key)
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, MOD_CONTROL)
        self.assertEqual(vk, 0xBA)


# ---------------------------------------------------------------------------
# Win32HotkeyListener init and get_status
# ---------------------------------------------------------------------------


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
