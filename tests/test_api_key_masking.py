from __future__ import annotations

import os
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


# ---------------------------------------------------------------------------
# is_sensitive_key
# ---------------------------------------------------------------------------

class TestIsSensitiveKey(unittest.TestCase):
    """Tests for is_sensitive_key(key)."""

    def test_api_key(self):
        self.assertTrue(is_sensitive_key("api_key"))

    def test_glm_api_key(self):
        self.assertTrue(is_sensitive_key("glm_api_key"))

    def test_secret(self):
        self.assertTrue(is_sensitive_key("secret"))

    def test_token(self):
        self.assertTrue(is_sensitive_key("my_token"))

    def test_password(self):
        self.assertTrue(is_sensitive_key("password"))

    def test_apikey(self):
        self.assertTrue(is_sensitive_key("apikey"))

    def test_client_secret(self):
        self.assertTrue(is_sensitive_key("client_secret"))

    def test_access_token(self):
        self.assertTrue(is_sensitive_key("access_token"))

    def test_db_password(self):
        self.assertTrue(is_sensitive_key("db_password"))

    def test_non_sensitive_name(self):
        self.assertFalse(is_sensitive_key("name"))

    def test_non_sensitive_enabled(self):
        self.assertFalse(is_sensitive_key("enabled"))

    def test_non_sensitive_api(self):
        self.assertFalse(is_sensitive_key("api"))

    def test_non_sensitive_model(self):
        self.assertFalse(is_sensitive_key("model"))

    def test_non_sensitive_interval(self):
        self.assertFalse(is_sensitive_key("interval"))

    def test_case_insensitive_upper(self):
        self.assertTrue(is_sensitive_key("API_KEY"))

    def test_case_insensitive_mixed(self):
        self.assertTrue(is_sensitive_key("My_Token"))

    def test_case_insensitive_password(self):
        self.assertTrue(is_sensitive_key("PASSWORD"))

    def test_case_insensitive_apikey_upper(self):
        self.assertTrue(is_sensitive_key("APIKEY"))

    def test_case_insensitive_secret_upper(self):
        self.assertTrue(is_sensitive_key("SECRET"))

    def test_empty_string(self):
        self.assertFalse(is_sensitive_key(""))

    def test_partial_match_not_suffix(self):
        """Keys where the suffix appears in the middle, not at the end."""
        self.assertFalse(is_sensitive_key("api_key_extra"))
        self.assertFalse(is_sensitive_key("token_holder"))


# ---------------------------------------------------------------------------
# _is_masked_value
# ---------------------------------------------------------------------------

class TestIsMaskedValue(unittest.TestCase):
    """Tests for _is_masked_value(val)."""

    def test_all_stars_eight(self):
        self.assertTrue(_is_masked_value("********"))

    def test_all_stars_three(self):
        self.assertTrue(_is_masked_value("***"))

    def test_all_stars_four(self):
        self.assertTrue(_is_masked_value("****"))

    def test_all_stars_many(self):
        self.assertTrue(_is_masked_value("***************"))

    def test_partial_mask_sk_prefix(self):
        self.assertTrue(_is_masked_value("sk-1****"))

    def test_partial_mask_two_chars(self):
        self.assertTrue(_is_masked_value("ab****"))

    def test_partial_mask_one_char(self):
        self.assertTrue(_is_masked_value("a****"))

    def test_partial_mask_four_chars(self):
        self.assertTrue(_is_masked_value("abcd****"))

    def test_real_key_not_masked(self):
        self.assertFalse(_is_masked_value("real-key"))

    def test_normal_sk_value(self):
        self.assertFalse(_is_masked_value("sk-12345"))

    def test_empty_string(self):
        self.assertFalse(_is_masked_value(""))

    def test_single_star(self):
        self.assertTrue(_is_masked_value("*"))

    def test_two_stars(self):
        self.assertTrue(_is_masked_value("**"))

    def test_five_chars_prefix_too_long(self):
        """Pattern ^.{1,4}\*+$ means 1-4 chars then stars. 5 chars won't match."""
        self.assertFalse(_is_masked_value("abcde****"))

    def test_no_stars_at_end(self):
        self.assertFalse(_is_masked_value("sk-1234"))


# ---------------------------------------------------------------------------
# strip_api_keys
# ---------------------------------------------------------------------------

class TestStripApiKeys(unittest.TestCase):
    """Tests for strip_api_keys(data)."""

    def test_simple_key(self):
        data = {"api_key": "secret123"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_nested_key(self):
        data = {"scripts": {"my_script": {"api_key": "sk-1234567890"}}}
        result = strip_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "********")

    def test_non_string_value(self):
        data = {"api_key": 12345}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], 12345)

    def test_empty_string_value(self):
        data = {"api_key": ""}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "")

    def test_none_value(self):
        data = {"api_key": None}
        result = strip_api_keys(data)
        self.assertIsNone(result["api_key"])

    def test_does_not_modify_original(self):
        data = {"api_key": "secret123"}
        result = strip_api_keys(data)
        self.assertEqual(data["api_key"], "secret123")
        self.assertNotEqual(result["api_key"], "secret123")

    def test_list_of_dicts(self):
        data = {"items": [{"api_key": "secret1"}, {"token": "secret2"}]}
        result = strip_api_keys(data)
        self.assertEqual(result["items"][0]["api_key"], "********")
        self.assertEqual(result["items"][1]["token"], "********")

    def test_non_sensitive_untouched(self):
        data = {"name": "test", "interval": 1.5}
        result = strip_api_keys(data)
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["interval"], 1.5)

    def test_short_value(self):
        data = {"api_key": "abc"}
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

    def test_mixed_sensitive_and_non(self):
        data = {"api_key": "secret", "name": "test", "password": "pass123"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["password"], "********")

    def test_deeply_nested(self):
        data = {"level1": {"level2": {"level3": {"token": "deep-secret"}}}}
        result = strip_api_keys(data)
        self.assertEqual(result["level1"]["level2"]["level3"]["token"], "********")

    def test_empty_dict(self):
        data = {}
        result = strip_api_keys(data)
        self.assertEqual(result, {})

    def test_list_with_non_dict_items(self):
        data = {"items": ["string", 42, {"api_key": "secret"}]}
        result = strip_api_keys(data)
        self.assertEqual(result["items"][0], "string")
        self.assertEqual(result["items"][1], 42)
        self.assertEqual(result["items"][2]["api_key"], "********")

    def test_multiple_sensitive_keys(self):
        data = {"api_key": "a", "secret": "b", "token": "c", "password": "d", "apikey": "e"}
        result = strip_api_keys(data)
        for key in ("api_key", "secret", "token", "password", "apikey"):
            self.assertEqual(result[key], "********")

    def test_boolean_value(self):
        data = {"api_key": True}
        result = strip_api_keys(data)
        self.assertTrue(result["api_key"])

    def test_deep_copy_independence(self):
        data = {"nested": {"api_key": "secret", "model": "gpt-4"}}
        result = strip_api_keys(data)
        result["nested"]["model"] = "modified"
        self.assertEqual(data["nested"]["model"], "gpt-4")


# ---------------------------------------------------------------------------
# hide_api_key
# ---------------------------------------------------------------------------

class TestHideApiKey(unittest.TestCase):
    """Tests for hide_api_key(yaml_text)."""

    def test_simple(self):
        text = "glm_api_key: sk-real-key-12345\n"
        result = hide_api_key(text)
        self.assertIn("***", result)
        self.assertNotIn("sk-real-key-12345", result)

    def test_multiple_keys(self):
        text = "glm_api_key: key1\nglm_model: model1\n"
        result = hide_api_key(text)
        self.assertNotIn("key1", result)

    def test_non_key_lines_untouched(self):
        text = "interval: 1.5\n"
        result = hide_api_key(text)
        self.assertIn("1.5", result)

    def test_empty_text(self):
        result = hide_api_key("")
        self.assertEqual(result, "")

    def test_password_key(self):
        text = "password: mysecret\n"
        result = hide_api_key(text)
        self.assertNotIn("mysecret", result)

    def test_token_key(self):
        text = "my_token: abc123\n"
        result = hide_api_key(text)
        self.assertNotIn("abc123", result)

    def test_secret_key(self):
        text = "client_secret: s3cr3t\n"
        result = hide_api_key(text)
        self.assertNotIn("s3cr3t", result)

    def test_apikey_no_underscore(self):
        text = "apikey: mykey123\n"
        result = hide_api_key(text)
        self.assertNotIn("mykey123", result)

    def test_preserves_key_name(self):
        text = "glm_api_key: sk-real-key-12345\n"
        result = hide_api_key(text)
        self.assertIn("glm_api_key", result)

    def test_preserves_indentation(self):
        text = "  api_key: secret123\n"
        result = hide_api_key(text)
        self.assertTrue(result.startswith("  "))

    def test_multiple_sensitive_lines(self):
        text = "api_key: key1\ntoken: tok1\npassword: pass1\nname: myname\n"
        result = hide_api_key(text)
        self.assertNotIn("key1", result)
        self.assertNotIn("tok1", result)
        self.assertNotIn("pass1", result)
        self.assertIn("myname", result)

    def test_line_without_newline(self):
        text = "api_key: secret"
        result = hide_api_key(text)
        self.assertNotIn("secret", result)
        self.assertIn("***", result)

    def test_mixed_lines(self):
        text = "interval: 1.5\napi_key: sk-key\nmodel: glm-4\n"
        result = hide_api_key(text)
        self.assertIn("1.5", result)
        self.assertNotIn("sk-key", result)
        self.assertIn("glm-4", result)

    def test_value_with_colon(self):
        text = "api_key: key:with:colons\n"
        result = hide_api_key(text)
        self.assertNotIn("key:with:colons", result)

    def test_empty_value(self):
        text = "api_key: \n"
        result = hide_api_key(text)
        # Empty value line should still be processed
        self.assertIn("api_key", result)


# ---------------------------------------------------------------------------
# restore_api_key
# ---------------------------------------------------------------------------

class TestRestoreApiKey(unittest.TestCase):
    """Tests for restore_api_key(edited_text, original_text)."""

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

    def test_multiple_same_type_keys(self):
        edited = "api_key: ***\napi_key: ***\n"
        original = "api_key: key1\napi_key: key2\n"
        result = restore_api_key(edited, original)
        self.assertIn("key1", result)
        self.assertIn("key2", result)

    def test_no_original_trailing_newline(self):
        edited = "glm_api_key: ***"
        original = "glm_api_key: sk-real-key"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key", result)

    def test_multiple_different_keys(self):
        edited = "api_key: ***\ntoken: ***\npassword: ***\n"
        original = "api_key: mykey\ntoken: mytoken\npassword: mypass\n"
        result = restore_api_key(edited, original)
        self.assertIn("mykey", result)
        self.assertIn("mytoken", result)
        self.assertIn("mypass", result)

    def test_non_sensitive_lines_untouched(self):
        edited = "api_key: ***\nmodel: glm-4\n"
        original = "api_key: secret\nmodel: glm-4\n"
        result = restore_api_key(edited, original)
        self.assertIn("secret", result)
        self.assertIn("glm-4", result)

    def test_edited_non_masked_not_restored(self):
        edited = "api_key: new-key\n"
        original = "api_key: old-key\n"
        result = restore_api_key(edited, original)
        self.assertIn("new-key", result)
        self.assertNotIn("old-key", result)

    def test_empty_edited_text(self):
        edited = ""
        original = "api_key: secret\n"
        result = restore_api_key(edited, original)
        self.assertNotIn("secret", result)

    def test_empty_original_text(self):
        edited = "api_key: ***\n"
        original = ""
        result = restore_api_key(edited, original)
        self.assertIn("***", result)

    def test_original_trailing_newline_added(self):
        edited = "api_key: ***"
        original = "api_key: secret\n"
        result = restore_api_key(edited, original)
        self.assertTrue(result.endswith("\n"))

    def test_no_original_trailing_newline_no_extra(self):
        edited = "api_key: ***"
        original = "api_key: secret"
        result = restore_api_key(edited, original)
        self.assertFalse(result.endswith("\n\n"))


# ---------------------------------------------------------------------------
# fill_masked_api_keys
# ---------------------------------------------------------------------------

class TestFillMaskedApiKeys(unittest.TestCase):
    """Tests for fill_masked_api_keys(data) — now a simple shallow copy."""

    def test_returns_shallow_copy(self):
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result, data)
        self.assertIsNot(result, data)

    def test_preserves_non_masked_values(self):
        data = {"glm_api_key": "actual-key", "model": "glm-4"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "actual-key")
        self.assertEqual(result["model"], "glm-4")

    def test_preserves_masked_values(self):
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "********")

    def test_preserves_scripts(self):
        data = {"scripts": {"my_script": {"api_key": "actual-key"}}}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "actual-key")


if __name__ == "__main__":
    unittest.main()
