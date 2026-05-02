from __future__ import annotations

import threading
import unittest

from platex_client.i18n import (
    available_languages,
    get_current_language,
    initialize,
    on_language_changed,
    remove_language_callback,
    switch_language,
    t,
)


class TestI18nInitialize(unittest.TestCase):
    def tearDown(self):
        initialize("en")

    def test_initialize_en(self):
        initialize("en")
        self.assertEqual(get_current_language(), "en")

    def test_initialize_zh_cn(self):
        initialize("zh-cn")
        self.assertEqual(get_current_language(), "zh-cn")
        initialize("en")

    def test_initialize_invalid_falls_back_to_en(self):
        initialize("nonexistent")
        self.assertEqual(get_current_language(), "en")

    def test_initialize_empty_string_falls_back_to_en(self):
        initialize("")
        self.assertEqual(get_current_language(), "en")


class TestI18nTranslation(unittest.TestCase):
    def setUp(self):
        initialize("en")

    def test_t_returns_key_for_missing(self):
        result = t("nonexistent.key.12345")
        self.assertEqual(result, "nonexistent.key.12345")

    def test_t_with_format_kwargs(self):
        result = t("nonexistent.key.{name}", name="test")
        self.assertIn("test", result)

    def test_t_with_empty_kwargs(self):
        result = t("nonexistent.key")
        self.assertEqual(result, "nonexistent.key")

    def test_t_returns_string(self):
        result = t("some.key")
        self.assertIsInstance(result, str)


class TestI18nSwitchLanguage(unittest.TestCase):
    def setUp(self):
        initialize("en")

    def tearDown(self):
        initialize("en")

    def test_switch_to_zh_cn(self):
        initialize("en")
        switch_language("zh-cn")
        self.assertEqual(get_current_language(), "zh-cn")

    def test_switch_to_invalid_keeps_current(self):
        initialize("en")
        switch_language("invalid_lang")
        self.assertEqual(get_current_language(), "en")

    def test_switch_to_same_language_noop(self):
        initialize("en")
        switch_language("en")
        self.assertEqual(get_current_language(), "en")


class TestI18nLanguageCallbacks(unittest.TestCase):
    def setUp(self):
        initialize("en")

    def tearDown(self):
        initialize("en")

    def test_on_language_changed_callback(self):
        called_with = []
        cb = lambda lang: called_with.append(lang)
        on_language_changed(cb)
        try:
            switch_language("zh-cn")
            self.assertEqual(len(called_with), 1)
            self.assertEqual(called_with[0], "zh-cn")
        finally:
            remove_language_callback(cb)

    def test_remove_language_callback(self):
        called = []
        cb = lambda lang: called.append(lang)
        on_language_changed(cb)
        remove_language_callback(cb)
        switch_language("zh-cn")
        self.assertEqual(len(called), 0)


class TestI18nAvailableLanguages(unittest.TestCase):
    def test_available_languages_returns_list(self):
        langs = available_languages()
        self.assertIsInstance(langs, list)

    def test_available_languages_has_tuples(self):
        langs = available_languages()
        for code, name in langs:
            self.assertIsInstance(code, str)
            self.assertIsInstance(name, str)

    def test_english_available(self):
        langs = available_languages()
        codes = [code for code, _ in langs]
        self.assertIn("en", codes)


if __name__ == "__main__":
    unittest.main()
