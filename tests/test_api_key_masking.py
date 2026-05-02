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


class TestIsSensitiveKey(unittest.TestCase):
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

    def test_non_sensitive(self):
        self.assertFalse(is_sensitive_key("name"))

    def test_non_sensitive_enabled(self):
        self.assertFalse(is_sensitive_key("enabled"))

    def test_non_sensitive_api(self):
        self.assertFalse(is_sensitive_key("api"))

    def test_case_insensitive(self):
        self.assertTrue(is_sensitive_key("API_KEY"))
        self.assertTrue(is_sensitive_key("My_Token"))
        self.assertTrue(is_sensitive_key("PASSWORD"))


class TestIsMaskedValue(unittest.TestCase):
    def test_all_stars(self):
        self.assertTrue(_is_masked_value("********"))

    def test_few_stars(self):
        self.assertTrue(_is_masked_value("***"))

    def test_partial_mask(self):
        self.assertTrue(_is_masked_value("sk-1****"))

    def test_four_stars(self):
        self.assertTrue(_is_masked_value("****"))

    def test_real_key(self):
        self.assertFalse(_is_masked_value("real-key"))

    def test_normal_value(self):
        self.assertFalse(_is_masked_value("sk-12345"))

    def test_empty_string(self):
        self.assertFalse(_is_masked_value(""))


class TestStripApiKeys(unittest.TestCase):
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


class TestHideApiKey(unittest.TestCase):
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


class TestRestoreApiKey(unittest.TestCase):
    def test_restore_masked_value(self):
        edited = "glm_api_key: ***\n"
        original = "glm_api_key: sk-real-key-12345\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key-12345", result)

    def test_preserves_non_masked(self):
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


class TestFillMaskedApiKeys(unittest.TestCase):
    def setUp(self):
        from platex_client.secrets import clear_all
        clear_all()
        self._original_env = os.environ.get("GLM_API_KEY")
        if "GLM_API_KEY" in os.environ:
            del os.environ["GLM_API_KEY"]

    def tearDown(self):
        from platex_client.secrets import clear_all
        clear_all()
        if self._original_env is not None:
            os.environ["GLM_API_KEY"] = self._original_env
        elif "GLM_API_KEY" in os.environ:
            del os.environ["GLM_API_KEY"]

    def test_fill_masked_glm_api_key(self):
        from platex_client.secrets import set_secret
        set_secret("GLM_API_KEY", "real-key-123")
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "real-key-123")

    def test_fill_non_masked_kept(self):
        data = {"glm_api_key": "actual-key"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "actual-key")

    def test_fill_keeps_masked_when_no_secret(self):
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "********")

    def test_fill_partial_mask(self):
        from platex_client.secrets import set_secret
        set_secret("GLM_API_KEY", "real-key-123")
        data = {"glm_api_key": "sk-1****"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "real-key-123")

    def test_fill_script_api_key(self):
        from platex_client.secrets import set_secret
        set_secret("GLM_API_KEY", "global-key")
        data = {"scripts": {"my_script": {"api_key": "********"}}}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "global-key")

    def test_fill_script_with_own_key(self):
        from platex_client.secrets import set_secret
        set_secret("PLATEX_API_KEY_MY_SCRIPT", "script-specific-key")
        data = {"scripts": {"my_script": {"api_key": "********"}}}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "script-specific-key")

    def test_does_not_modify_original(self):
        from platex_client.secrets import set_secret
        set_secret("GLM_API_KEY", "real-key")
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(data["glm_api_key"], "********")

    def test_fill_from_env(self):
        os.environ["GLM_API_KEY"] = "env-key-123"
        try:
            data = {"glm_api_key": "********"}
            result = fill_masked_api_keys(data)
            self.assertEqual(result["glm_api_key"], "env-key-123")
        finally:
            del os.environ["GLM_API_KEY"]


if __name__ == "__main__":
    unittest.main()
