from __future__ import annotations

import os
import tempfile
import unittest

from platex_client.api_key_masking import (
    _is_masked_value,
    fill_masked_api_keys,
    hide_api_key,
    is_sensitive_key,
    restore_api_key,
    strip_api_keys,
)
from platex_client.secrets import clear_all, set_secret


class TestIsSensitiveKey(unittest.TestCase):
    def test_api_key(self):
        self.assertTrue(is_sensitive_key("api_key"))

    def test_glm_api_key(self):
        self.assertTrue(is_sensitive_key("glm_api_key"))

    def test_secret(self):
        self.assertTrue(is_sensitive_key("secret"))

    def test_my_token(self):
        self.assertTrue(is_sensitive_key("my_token"))

    def test_password(self):
        self.assertTrue(is_sensitive_key("password"))

    def test_apikey(self):
        self.assertTrue(is_sensitive_key("apikey"))

    def test_ACCESS_TOKEN(self):
        self.assertTrue(is_sensitive_key("ACCESS_TOKEN"))

    def test_DB_PASSWORD(self):
        self.assertTrue(is_sensitive_key("DB_PASSWORD"))

    def test_name_not_sensitive(self):
        self.assertFalse(is_sensitive_key("name"))

    def test_enabled_not_sensitive(self):
        self.assertFalse(is_sensitive_key("enabled"))

    def test_api_not_sensitive(self):
        self.assertFalse(is_sensitive_key("api"))

    def test_interval_not_sensitive(self):
        self.assertFalse(is_sensitive_key("interval"))

    def test_empty_string_not_sensitive(self):
        self.assertFalse(is_sensitive_key(""))


class TestStripApiKeys(unittest.TestCase):
    def test_short_value(self):
        data = {"api_key": "abc"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_long_value(self):
        data = {"api_key": "sk-1234567890abcdef"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_exact_4_chars(self):
        data = {"api_key": "abcd"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_12_chars(self):
        data = {"api_key": "123456789012"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_13_chars(self):
        data = {"api_key": "1234567890123"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_non_string_value(self):
        data = {"api_key": 12345}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], 12345)

    def test_empty_string(self):
        data = {"api_key": ""}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "")

    def test_none_value(self):
        data = {"api_key": None}
        result = strip_api_keys(data)
        self.assertIsNone(result["api_key"])

    def test_nested_dict(self):
        data = {"scripts": {"my_script": {"api_key": "sk-1234567890"}}}
        result = strip_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "********")

    def test_deeply_nested(self):
        data = {"level1": {"level2": {"level3": {"secret": "deep_secret"}}}}
        result = strip_api_keys(data)
        self.assertEqual(result["level1"]["level2"]["level3"]["secret"], "********")

    def test_list_of_dicts(self):
        data = {"items": [{"api_key": "key1"}, {"api_key": "key2"}]}
        result = strip_api_keys(data)
        self.assertEqual(result["items"][0]["api_key"], "********")
        self.assertEqual(result["items"][1]["api_key"], "********")

    def test_does_not_modify_original(self):
        data = {"api_key": "secret123"}
        result = strip_api_keys(data)
        self.assertEqual(data["api_key"], "secret123")
        self.assertNotEqual(result["api_key"], "secret123")

    def test_non_sensitive_keys_unchanged(self):
        data = {"name": "test", "interval": 2.0, "enabled": True}
        result = strip_api_keys(data)
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["interval"], 2.0)
        self.assertTrue(result["enabled"])

    def test_mixed_sensitive_and_non(self):
        data = {"api_key": "secret", "name": "test", "password": "pass123"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["password"], "********")

    def test_empty_dict(self):
        result = strip_api_keys({})
        self.assertEqual(result, {})

    def test_boolean_value(self):
        data = {"api_key": True}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], True)

    def test_list_value(self):
        data = {"api_key": [1, 2, 3]}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], [1, 2, 3])


class TestIsMaskedValue(unittest.TestCase):
    def test_all_stars(self):
        self.assertTrue(_is_masked_value("********"))

    def test_three_stars(self):
        self.assertTrue(_is_masked_value("***"))

    def test_four_stars(self):
        self.assertTrue(_is_masked_value("****"))

    def test_partial_mask(self):
        self.assertTrue(_is_masked_value("sk-1****"))

    def test_real_key_not_masked(self):
        self.assertFalse(_is_masked_value("real-key"))

    def test_sk_12345_not_masked(self):
        self.assertFalse(_is_masked_value("sk-12345"))

    def test_empty_string_not_masked(self):
        self.assertFalse(_is_masked_value(""))

    def test_single_star(self):
        self.assertTrue(_is_masked_value("*"))

    def test_two_stars(self):
        self.assertTrue(_is_masked_value("**"))

    def test_prefix_with_stars(self):
        self.assertTrue(_is_masked_value("ab****"))


class TestHideApiKey(unittest.TestCase):
    def test_simple_key(self):
        text = "glm_api_key: sk-12345\n"
        result = hide_api_key(text)
        self.assertIn("***", result)
        self.assertNotIn("sk-12345", result)

    def test_multiple_keys(self):
        text = "glm_api_key: key1\nglm_model: model1\n"
        result = hide_api_key(text)
        self.assertNotIn("key1", result)

    def test_no_keys(self):
        text = "interval: 2.0\nname: test\n"
        result = hide_api_key(text)
        self.assertEqual(result, text)

    def test_password_key(self):
        text = "password: mysecret\n"
        result = hide_api_key(text)
        self.assertNotIn("mysecret", result)

    def test_token_key(self):
        text = "my_token: abc123\n"
        result = hide_api_key(text)
        self.assertNotIn("abc123", result)

    def test_empty_text(self):
        result = hide_api_key("")
        self.assertEqual(result, "")


class TestRestoreApiKey(unittest.TestCase):
    def test_restore_masked_value(self):
        edited = "glm_api_key: ***\n"
        original = "glm_api_key: sk-real-key-12345\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key-12345", result)

    def test_preserves_non_masked_values(self):
        edited = "glm_api_key: new-actual-key\n"
        original = "glm_api_key: old-key\n"
        result = restore_api_key(edited, original)
        self.assertIn("new-actual-key", result)

    def test_trailing_newline(self):
        edited = "glm_api_key: ***\n"
        original = "glm_api_key: sk-real-key\n"
        result = restore_api_key(edited, original)
        self.assertTrue(result.endswith("\n"))

    def test_partial_mask(self):
        edited = "glm_api_key: sk-1****\n"
        original = "glm_api_key: sk-1234567890\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-1234567890", result)

    def test_eight_star_mask(self):
        edited = "glm_api_key: ********\n"
        original = "glm_api_key: sk-real-key-12345\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key-12345", result)

    def test_multiple_keys(self):
        edited = "glm_api_key: ********\nglm_model: gpt-4\n"
        original = "glm_api_key: sk-real-key\nglm_model: glm-4\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key", result)
        self.assertIn("gpt-4", result)

    def test_no_masked_values(self):
        edited = "interval: 2.0\n"
        original = "interval: 1.0\n"
        result = restore_api_key(edited, original)
        self.assertIn("2.0", result)

    def test_empty_strings(self):
        result = restore_api_key("", "")
        self.assertEqual(result, "")

    def test_original_trailing_newline_preserved(self):
        edited = "glm_api_key: ***"
        original = "glm_api_key: sk-key\n"
        result = restore_api_key(edited, original)
        self.assertTrue(result.endswith("\n"))


class TestFillMaskedApiKeys(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY",):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY",):
            os.environ.pop(key, None)

    def test_fill_masked_glm_api_key(self):
        set_secret("GLM_API_KEY", "real-key-123")
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "real-key-123")

    def test_fill_non_masked_glm_api_key(self):
        data = {"glm_api_key": "actual-key"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "actual-key")

    def test_fill_masked_keeps_masked_when_no_secret(self):
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "********")

    def test_fill_partial_mask(self):
        set_secret("GLM_API_KEY", "real-key-123")
        data = {"glm_api_key": "sk-1****"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "real-key-123")

    def test_fill_does_not_modify_original(self):
        set_secret("GLM_API_KEY", "real-key")
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(data["glm_api_key"], "********")
        self.assertEqual(result["glm_api_key"], "real-key")

    def test_fill_with_scripts(self):
        set_secret("GLM_API_KEY", "real-key")
        data = {"glm_api_key": "********", "scripts": {"my_script": {"api_key": "********"}}}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "real-key")
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "real-key")

    def test_fill_with_non_dict_scripts(self):
        data = {"scripts": "not_a_dict"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"], "not_a_dict")

    def test_fill_with_non_dict_script_config(self):
        data = {"scripts": {"my_script": "not_a_dict"}}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"], "not_a_dict")

    def test_fill_empty_data(self):
        result = fill_masked_api_keys({})
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
