from __future__ import annotations

import unittest
from unittest.mock import patch

from platex_client.mouse_input import simulate_click


class TestSimulateClickValidation(unittest.TestCase):
    def test_non_integer_x_raises_type_error(self):
        with self.assertRaises(TypeError):
            simulate_click(1.5, 100)

    def test_non_integer_y_raises_type_error(self):
        with self.assertRaises(TypeError):
            simulate_click(100, 1.5)

    def test_string_x_raises_type_error(self):
        with self.assertRaises(TypeError):
            simulate_click("100", 100)

    def test_string_y_raises_type_error(self):
        with self.assertRaises(TypeError):
            simulate_click(100, "100")

    def test_invalid_button_defaults_to_left(self):
        with patch("platex_client.mouse_input._win32_simulate_click", return_value=True), \
             patch("platex_client.mouse_input.IS_WINDOWS", True), \
             patch("platex_client.mouse_input.USER32") as mock_user32:
            mock_user32.GetSystemMetrics.side_effect = [1920, 1080]
            simulate_click(100, 200, button="middle")

    def test_negative_x_clamped(self):
        with patch("platex_client.mouse_input._win32_simulate_click", return_value=True), \
             patch("platex_client.mouse_input.IS_WINDOWS", True), \
             patch("platex_client.mouse_input.USER32") as mock_user32:
            mock_user32.GetSystemMetrics.side_effect = [1920, 1080]
            simulate_click(-10, 100)

    def test_negative_y_clamped(self):
        with patch("platex_client.mouse_input._win32_simulate_click", return_value=True), \
             patch("platex_client.mouse_input.IS_WINDOWS", True), \
             patch("platex_client.mouse_input.USER32") as mock_user32:
            mock_user32.GetSystemMetrics.side_effect = [1920, 1080]
            simulate_click(100, -10)


class TestGetForegroundWindowTitle(unittest.TestCase):
    def test_non_windows_returns_empty(self):
        from platex_client.mouse_input import get_foreground_window_title
        with patch("platex_client.mouse_input._IS_WINDOWS", False):
            result = get_foreground_window_title()
            self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
