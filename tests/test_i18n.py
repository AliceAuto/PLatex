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


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestI18nInitialize(unittest.TestCase):
    """Tests for initialize(language)."""

    def setUp(self):
        initialize("en")

    def test_initialize_en(self):
        initialize("en")
        self.assertEqual(get_current_language(), "en")

    def test_initialize_zh_cn(self):
        initialize("zh-cn")
        self.assertEqual(get_current_language(), "zh-cn")

    def test_initialize_invalid_falls_back_to_en(self):
        initialize("nonexistent")
        self.assertEqual(get_current_language(), "en")

    def test_initialize_empty_string(self):
        initialize("")
        self.assertEqual(get_current_language(), "en")

    def test_initialize_en_returns_en(self):
        """Initializing with 'en' when en.yaml exists should stay en."""
        initialize("en")
        self.assertEqual(get_current_language(), "en")

    def test_reinitialize_changes_language(self):
        initialize("en")
        self.assertEqual(get_current_language(), "en")
        initialize("zh-cn")
        self.assertEqual(get_current_language(), "zh-cn")
        initialize("en")
        self.assertEqual(get_current_language(), "en")


# ---------------------------------------------------------------------------
# get_current_language
# ---------------------------------------------------------------------------

class TestGetCurrentLanguage(unittest.TestCase):
    """Tests for get_current_language()."""

    def setUp(self):
        initialize("en")

    def test_returns_string(self):
        lang = get_current_language()
        self.assertIsInstance(lang, str)

    def test_after_initialize_en(self):
        initialize("en")
        self.assertEqual(get_current_language(), "en")

    def test_after_initialize_zh_cn(self):
        initialize("zh-cn")
        self.assertEqual(get_current_language(), "zh-cn")


# ---------------------------------------------------------------------------
# t (translate)
# ---------------------------------------------------------------------------

class TestI18nTranslate(unittest.TestCase):
    """Tests for t(key, **kwargs)."""

    def setUp(self):
        initialize("en")

    def test_t_returns_key_for_missing_translation(self):
        result = t("nonexistent.key.12345")
        self.assertEqual(result, "nonexistent.key.12345")

    def test_t_with_format_kwargs(self):
        result = t("nonexistent.key.{name}", name="test")
        self.assertIn("test", result)

    def test_t_without_kwargs(self):
        result = t("nonexistent.key")
        self.assertEqual(result, "nonexistent.key")

    def test_t_empty_key(self):
        result = t("")
        self.assertEqual(result, "")

    def test_t_known_key_en(self):
        """Test with a real translation key from en.yaml."""
        result = t("btn_save")
        self.assertEqual(result, "Save & Apply")

    def test_t_known_key_zh_cn(self):
        """Test with a real translation key from zh-cn.yaml."""
        initialize("zh-cn")
        result = t("btn_save")
        self.assertEqual(result, "\u4fdd\u5b58\u5e76\u5e94\u7528")

    def test_t_format_with_real_key(self):
        """Test format substitution with a real key that has placeholders."""
        result = t("msg_backend", backend="test-backend")
        self.assertIn("test-backend", result)

    def test_t_format_missing_kwarg_keeps_placeholder(self):
        """When a format placeholder is not provided, the original {name} is kept."""
        result = t("msg_backend")
        self.assertIn("{backend}", result)

    def test_t_multiple_kwargs(self):
        result = t("tray_about_message", version="1.0", mode="watching", script="test", interval="5")
        self.assertIn("1.0", result)
        self.assertIn("watching", result)
        self.assertIn("test", result)
        self.assertIn("5", result)

    def test_t_numeric_format_arg(self):
        result = t("msg_running", count=5)
        self.assertIn("5", result)

    def test_t_switch_language_changes_translation(self):
        initialize("en")
        en_result = t("btn_close")
        initialize("zh-cn")
        zh_result = t("btn_close")
        self.assertNotEqual(en_result, zh_result)


# ---------------------------------------------------------------------------
# switch_language
# ---------------------------------------------------------------------------

class TestI18nSwitchLanguage(unittest.TestCase):
    """Tests for switch_language(language)."""

    def setUp(self):
        initialize("en")

    def test_switch_to_zh_cn(self):
        initialize("en")
        switch_language("zh-cn")
        self.assertEqual(get_current_language(), "zh-cn")

    def test_switch_back_to_en(self):
        initialize("en")
        switch_language("zh-cn")
        switch_language("en")
        self.assertEqual(get_current_language(), "en")

    def test_switch_to_same_language_noop(self):
        initialize("en")
        switch_language("en")
        self.assertEqual(get_current_language(), "en")

    def test_switch_to_invalid_keeps_current(self):
        initialize("en")
        switch_language("invalid_lang")
        self.assertEqual(get_current_language(), "en")

    def test_switch_to_invalid_from_zh_cn(self):
        initialize("zh-cn")
        switch_language("nonexistent")
        self.assertEqual(get_current_language(), "zh-cn")

    def test_switch_changes_translations(self):
        initialize("en")
        en_text = t("btn_close")
        switch_language("zh-cn")
        zh_text = t("btn_close")
        self.assertNotEqual(en_text, zh_text)

    def test_switch_to_en_from_zh_cn(self):
        initialize("zh-cn")
        switch_language("en")
        self.assertEqual(get_current_language(), "en")
        result = t("btn_close")
        self.assertEqual(result, "Close")


# ---------------------------------------------------------------------------
# on_language_changed / remove_language_callback
# ---------------------------------------------------------------------------

class TestI18nCallbacks(unittest.TestCase):
    """Tests for on_language_changed(callback) and remove_language_callback(callback)."""

    def setUp(self):
        initialize("en")

    def test_on_language_changed(self):
        called_with = []
        on_language_changed(lambda lang: called_with.append(lang))
        switch_language("zh-cn")
        self.assertTrue(len(called_with) > 0)
        self.assertEqual(called_with[-1], "zh-cn")

    def test_remove_language_callback(self):
        called = []
        cb = lambda lang: called.append(lang)
        on_language_changed(cb)
        remove_language_callback(cb)
        switch_language("zh-cn")
        self.assertEqual(len(called), 0)

    def test_callback_exception_handled(self):
        def bad_cb(lang):
            raise RuntimeError("error")

        on_language_changed(bad_cb)
        # Should not raise
        switch_language("zh-cn")

    def test_multiple_callbacks(self):
        r1, r2 = [], []
        on_language_changed(lambda lang: r1.append(lang))
        on_language_changed(lambda lang: r2.append(lang))
        switch_language("zh-cn")
        self.assertTrue(len(r1) > 0)
        self.assertTrue(len(r2) > 0)

    def test_callback_receives_language_code(self):
        received = []
        on_language_changed(lambda lang: received.append(lang))
        switch_language("zh-cn")
        self.assertIn("zh-cn", received)

    def test_callback_not_called_on_same_language(self):
        called = []
        cb = lambda lang: called.append(lang)
        on_language_changed(cb)
        # switch_language to same language is a no-op
        switch_language("en")
        self.assertEqual(len(called), 0)

    def test_remove_non_registered_callback_no_error(self):
        """Removing a callback that was never registered should not raise."""
        remove_language_callback(lambda lang: None)

    def test_remove_one_callback_keeps_others(self):
        r1, r2 = [], []
        cb1 = lambda lang: r1.append(lang)
        cb2 = lambda lang: r2.append(lang)
        on_language_changed(cb1)
        on_language_changed(cb2)
        remove_language_callback(cb1)
        switch_language("zh-cn")
        self.assertEqual(len(r1), 0)
        self.assertTrue(len(r2) > 0)

    def test_callback_called_on_each_switch(self):
        called = []
        on_language_changed(lambda lang: called.append(lang))
        switch_language("zh-cn")
        switch_language("en")
        self.assertEqual(len(called), 2)
        self.assertEqual(called[0], "zh-cn")
        self.assertEqual(called[1], "en")


# ---------------------------------------------------------------------------
# available_languages
# ---------------------------------------------------------------------------

class TestI18nAvailableLanguages(unittest.TestCase):
    """Tests for available_languages()."""

    def test_available_languages_returns_list(self):
        langs = available_languages()
        self.assertIsInstance(langs, list)

    def test_available_languages_has_en(self):
        langs = available_languages()
        codes = [code for code, name in langs]
        self.assertIn("en", codes)

    def test_available_languages_has_zh_cn(self):
        langs = available_languages()
        codes = [code for code, name in langs]
        self.assertIn("zh-cn", codes)

    def test_available_languages_format(self):
        langs = available_languages()
        for code, name in langs:
            self.assertIsInstance(code, str)
            self.assertIsInstance(name, str)
            self.assertTrue(len(code) > 0)
            self.assertTrue(len(name) > 0)

    def test_available_languages_tuples(self):
        langs = available_languages()
        for item in langs:
            self.assertEqual(len(item), 2)

    def test_available_languages_en_name(self):
        langs = available_languages()
        names = {code: name for code, name in langs}
        self.assertEqual(names["en"], "English")

    def test_available_languages_zh_cn_name(self):
        langs = available_languages()
        names = {code: name for code, name in langs}
        self.assertIn("zh-cn", names)
        self.assertIn("\u4e2d\u6587", names["zh-cn"])


# ---------------------------------------------------------------------------
# _load_language_pack (indirect)
# ---------------------------------------------------------------------------

class TestLoadLanguagePack(unittest.TestCase):
    """Indirect tests for _load_language_pack via initialize()."""

    def test_load_valid_language(self):
        initialize("en")
        # Should have loaded translations
        self.assertNotEqual(t("btn_save"), "btn_save")

    def test_load_invalid_language_returns_empty(self):
        """Invalid language falls back to en, so translations should still work."""
        initialize("nonexistent_lang_xyz")
        # Falls back to en
        self.assertEqual(get_current_language(), "en")
        self.assertNotEqual(t("btn_save"), "btn_save")

    def test_load_zh_cn_has_translations(self):
        initialize("zh-cn")
        result = t("btn_save")
        self.assertNotEqual(result, "btn_save")


# ---------------------------------------------------------------------------
# _resolve_locales_dir (indirect)
# ---------------------------------------------------------------------------

class TestResolveLocalesDir(unittest.TestCase):
    """Indirect tests for _resolve_locales_dir via available_languages()."""

    def test_locales_dir_resolves(self):
        """If locales dir resolves, available_languages should return at least en."""
        langs = available_languages()
        self.assertTrue(len(langs) > 0)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestI18nConcurrency(unittest.TestCase):
    """Tests for concurrent access to i18n module."""

    def test_concurrent_switch(self):
        initialize("en")
        errors = []

        def switcher(lang):
            try:
                for _ in range(50):
                    switch_language(lang)
                    get_current_language()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=switcher, args=("en",)),
            threading.Thread(target=switcher, args=("zh-cn",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(errors), 0)

    def test_concurrent_translate(self):
        initialize("en")
        errors = []

        def translator():
            try:
                for _ in range(50):
                    t("some.key")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=translator) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(errors), 0)

    def test_concurrent_switch_and_translate(self):
        initialize("en")
        errors = []

        def switcher():
            try:
                for _ in range(30):
                    switch_language("en")
                    switch_language("zh-cn")
            except Exception as e:
                errors.append(e)

        def translator():
            try:
                for _ in range(30):
                    t("btn_save")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=switcher),
            threading.Thread(target=translator),
            threading.Thread(target=translator),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(errors), 0)

    def test_concurrent_callback_registration(self):
        initialize("en")
        errors = []

        def register_and_unregister():
            try:
                for _ in range(20):
                    cb = lambda lang: None
                    on_language_changed(cb)
                    remove_language_callback(cb)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_and_unregister) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
