from __future__ import annotations

import threading
import unittest

from platex_client.secrets import (
    clear_all,
    delete_secret,
    get_all_keys,
    get_secret,
    has_secret,
    set_secret,
)


# ---------------------------------------------------------------------------
# set_secret / get_secret
# ---------------------------------------------------------------------------

class TestSetAndGet(unittest.TestCase):
    """Tests for set_secret(key, value) and get_secret(key, default)."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_set_and_get_simple(self):
        set_secret("KEY1", "value1")
        self.assertEqual(get_secret("KEY1"), "value1")

    def test_set_and_get_multiple_keys(self):
        set_secret("A", "1")
        set_secret("B", "2")
        set_secret("C", "3")
        self.assertEqual(get_secret("A"), "1")
        self.assertEqual(get_secret("B"), "2")
        self.assertEqual(get_secret("C"), "3")

    def test_overwrite_value(self):
        set_secret("KEY", "old")
        set_secret("KEY", "new")
        self.assertEqual(get_secret("KEY"), "new")

    def test_overwrite_multiple_times(self):
        for i in range(10):
            set_secret("KEY", f"value_{i}")
        self.assertEqual(get_secret("KEY"), "value_9")

    def test_get_nonexistent_returns_default(self):
        self.assertEqual(get_secret("NONEXISTENT"), "")

    def test_get_nonexistent_custom_default(self):
        self.assertEqual(get_secret("NONEXISTENT", "fallback"), "fallback")

    def test_get_nonexistent_none_default(self):
        self.assertEqual(get_secret("NONEXISTENT", None), None)

    def test_empty_string_value(self):
        set_secret("KEY", "")
        self.assertTrue(has_secret("KEY"))
        self.assertEqual(get_secret("KEY"), "")

    def test_unicode_values(self):
        set_secret("KEY", "中文密钥 🔑 日本語 한국어")
        self.assertEqual(get_secret("KEY"), "中文密钥 🔑 日本語 한국어")

    def test_long_value(self):
        val = "x" * 10000
        set_secret("KEY", val)
        self.assertEqual(get_secret("KEY"), val)

    def test_special_characters(self):
        val = "key\twith\nspecial\r\nchars\\n\"'`\0\x01"
        set_secret("KEY", val)
        self.assertEqual(get_secret("KEY"), val)

    def test_value_with_newlines(self):
        val = "line1\nline2\nline3"
        set_secret("KEY", val)
        self.assertEqual(get_secret("KEY"), val)

    def test_value_with_yaml_special_chars(self):
        val = "key: value\n- item\n&anchor *alias"
        set_secret("KEY", val)
        self.assertEqual(get_secret("KEY"), val)

    def test_unicode_key(self):
        set_secret("密钥", "value")
        self.assertEqual(get_secret("密钥"), "value")

    def test_emoji_key(self):
        set_secret("🔑", "value")
        self.assertEqual(get_secret("🔑"), "value")

    def test_overwrite_zeroes_old_value(self):
        """When overwriting, the old value should be zeroed in memory.
        We cannot directly verify memory zeroing, but we verify the new value is correct."""
        set_secret("KEY", "sensitive_old")
        set_secret("KEY", "sensitive_new")
        self.assertEqual(get_secret("KEY"), "sensitive_new")


# ---------------------------------------------------------------------------
# has_secret
# ---------------------------------------------------------------------------

class TestHasSecret(unittest.TestCase):
    """Tests for has_secret(key)."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_has_secret_false_when_not_set(self):
        self.assertFalse(has_secret("NO_KEY"))

    def test_has_secret_true_after_set(self):
        set_secret("KEY", "val")
        self.assertTrue(has_secret("KEY"))

    def test_has_secret_true_for_empty_value(self):
        set_secret("KEY", "")
        self.assertTrue(has_secret("KEY"))

    def test_has_secret_false_after_delete(self):
        set_secret("KEY", "val")
        delete_secret("KEY")
        self.assertFalse(has_secret("KEY"))

    def test_has_secret_after_overwrite(self):
        set_secret("KEY", "old")
        set_secret("KEY", "new")
        self.assertTrue(has_secret("KEY"))

    def test_has_secret_independent_keys(self):
        set_secret("A", "1")
        self.assertTrue(has_secret("A"))
        self.assertFalse(has_secret("B"))

    def test_has_secret_after_clear(self):
        set_secret("KEY", "val")
        clear_all()
        self.assertFalse(has_secret("KEY"))


# ---------------------------------------------------------------------------
# delete_secret
# ---------------------------------------------------------------------------

class TestDeleteSecret(unittest.TestCase):
    """Tests for delete_secret(key)."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_delete_existing_key(self):
        set_secret("KEY", "val")
        delete_secret("KEY")
        self.assertFalse(has_secret("KEY"))
        self.assertEqual(get_secret("KEY"), "")

    def test_delete_nonexistent_key_no_error(self):
        delete_secret("NONEXISTENT")

    def test_delete_twice_no_error(self):
        set_secret("KEY", "val")
        delete_secret("KEY")
        delete_secret("KEY")

    def test_delete_one_does_not_affect_others(self):
        set_secret("A", "1")
        set_secret("B", "2")
        delete_secret("A")
        self.assertFalse(has_secret("A"))
        self.assertTrue(has_secret("B"))
        self.assertEqual(get_secret("B"), "2")

    def test_delete_all_keys(self):
        for i in range(5):
            set_secret(f"KEY_{i}", f"val_{i}")
        for i in range(5):
            delete_secret(f"KEY_{i}")
        for i in range(5):
            self.assertFalse(has_secret(f"KEY_{i}"))

    def test_delete_zeroes_old_value(self):
        """After deletion, the key should not be retrievable."""
        set_secret("KEY", "sensitive_data")
        delete_secret("KEY")
        self.assertEqual(get_secret("KEY"), "")
        self.assertFalse(has_secret("KEY"))


# ---------------------------------------------------------------------------
# clear_all
# ---------------------------------------------------------------------------

class TestClearAll(unittest.TestCase):
    """Tests for clear_all()."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_clear_all_removes_everything(self):
        for i in range(10):
            set_secret(f"KEY_{i}", f"val_{i}")
        clear_all()
        for i in range(10):
            self.assertFalse(has_secret(f"KEY_{i}"))

    def test_clear_all_when_empty(self):
        clear_all()

    def test_clear_all_twice(self):
        set_secret("KEY", "val")
        clear_all()
        clear_all()

    def test_can_set_after_clear(self):
        set_secret("KEY", "old")
        clear_all()
        set_secret("KEY", "new")
        self.assertEqual(get_secret("KEY"), "new")

    def test_clear_all_zeroes_values(self):
        """After clear_all, all keys should be gone."""
        set_secret("A", "secret_a")
        set_secret("B", "secret_b")
        clear_all()
        self.assertEqual(get_all_keys(), [])
        self.assertFalse(has_secret("A"))
        self.assertFalse(has_secret("B"))


# ---------------------------------------------------------------------------
# get_all_keys
# ---------------------------------------------------------------------------

class TestGetAllKeys(unittest.TestCase):
    """Tests for get_all_keys()."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_empty_keys(self):
        self.assertEqual(get_all_keys(), [])

    def test_single_key(self):
        set_secret("A", "1")
        self.assertEqual(get_all_keys(), ["A"])

    def test_multiple_keys(self):
        set_secret("A", "1")
        set_secret("B", "2")
        set_secret("C", "3")
        keys = set(get_all_keys())
        self.assertEqual(keys, {"A", "B", "C"})

    def test_keys_after_delete(self):
        set_secret("A", "1")
        set_secret("B", "2")
        delete_secret("A")
        self.assertEqual(get_all_keys(), ["B"])

    def test_keys_after_clear(self):
        set_secret("A", "1")
        clear_all()
        self.assertEqual(get_all_keys(), [])

    def test_overwrite_does_not_duplicate_key(self):
        set_secret("KEY", "old")
        set_secret("KEY", "new")
        self.assertEqual(get_all_keys(), ["KEY"])

    def test_keys_returns_list(self):
        set_secret("A", "1")
        result = get_all_keys()
        self.assertIsInstance(result, list)

    def test_many_keys(self):
        for i in range(50):
            set_secret(f"KEY_{i}", f"val_{i}")
        keys = set(get_all_keys())
        self.assertEqual(len(keys), 50)

    def test_keys_after_partial_delete(self):
        for i in range(10):
            set_secret(f"KEY_{i}", f"val_{i}")
        for i in range(0, 10, 2):  # delete even keys
            delete_secret(f"KEY_{i}")
        keys = set(get_all_keys())
        expected = {f"KEY_{i}" for i in range(1, 10, 2)}
        self.assertEqual(keys, expected)


# ---------------------------------------------------------------------------
# _find_secret_index (indirect)
# ---------------------------------------------------------------------------

class TestFindSecretIndex(unittest.TestCase):
    """Indirect tests for _find_secret_index(key) via other functions."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_find_existing_key(self):
        set_secret("KEY", "val")
        # get_secret uses _find_secret_index internally
        self.assertEqual(get_secret("KEY"), "val")

    def test_find_nonexistent_key(self):
        # get_secret returns default when index is -1
        self.assertEqual(get_secret("MISSING", "default"), "default")

    def test_find_after_overwrite(self):
        set_secret("KEY", "v1")
        set_secret("KEY", "v2")
        self.assertEqual(get_secret("KEY"), "v2")


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestSecretsConcurrency(unittest.TestCase):
    """Tests for thread-safe concurrent access."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_concurrent_writes(self):
        errors = []

        def writer(idx):
            try:
                for i in range(50):
                    set_secret("SHARED_KEY", f"writer_{idx}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_concurrent_reads_and_writes(self):
        errors = []
        set_secret("KEY", "initial")

        def writer():
            try:
                for i in range(100):
                    set_secret("KEY", f"value_{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    result = get_secret("KEY")
                    self.assertIsInstance(result, str)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_concurrent_has_and_set(self):
        errors = []

        def writer():
            try:
                for i in range(50):
                    set_secret(f"KEY_{i % 10}", f"val_{i}")
            except Exception as e:
                errors.append(e)

        def checker():
            try:
                for i in range(50):
                    has_secret(f"KEY_{i % 10}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=checker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_concurrent_delete_and_get(self):
        errors = []
        for i in range(10):
            set_secret(f"KEY_{i}", f"val_{i}")

        def deleter():
            try:
                for i in range(10):
                    delete_secret(f"KEY_{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(10):
                    get_secret(f"KEY_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=deleter),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_concurrent_clear_and_set(self):
        errors = []

        def setter():
            try:
                for i in range(50):
                    set_secret("KEY", f"val_{i}")
            except Exception as e:
                errors.append(e)

        def clearer():
            try:
                for _ in range(10):
                    clear_all()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=setter),
            threading.Thread(target=clearer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_concurrent_get_all_keys(self):
        errors = []

        def writer():
            try:
                for i in range(50):
                    set_secret(f"KEY_{i}", f"val_{i}")
            except Exception as e:
                errors.append(e)

        def key_reader():
            try:
                for _ in range(50):
                    keys = get_all_keys()
                    self.assertIsInstance(keys, list)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=key_reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_stress_test(self):
        """Stress test with many threads performing mixed operations."""
        errors = []

        def worker(idx):
            try:
                for i in range(20):
                    key = f"WORKER_{idx}_KEY_{i}"
                    set_secret(key, f"val_{i}")
                    self.assertTrue(has_secret(key))
                    self.assertEqual(get_secret(key), f"val_{i}")
                    delete_secret(key)
                    self.assertFalse(has_secret(key))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(len(errors), 0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestSecretsEdgeCases(unittest.TestCase):
    """Tests for edge cases with keys and values."""

    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_key_with_spaces(self):
        set_secret("key with spaces", "value")
        self.assertEqual(get_secret("key with spaces"), "value")

    def test_key_with_special_chars(self):
        set_secret("key/with\\special:chars", "value")
        self.assertEqual(get_secret("key/with\\special:chars"), "value")

    def test_numeric_string_key(self):
        set_secret("12345", "value")
        self.assertEqual(get_secret("12345"), "value")

    def test_case_sensitive_keys(self):
        set_secret("key", "lower")
        set_secret("KEY", "upper")
        self.assertEqual(get_secret("key"), "lower")
        self.assertEqual(get_secret("KEY"), "upper")

    def test_very_long_key(self):
        key = "k" * 1000
        set_secret(key, "value")
        self.assertEqual(get_secret(key), "value")

    def test_set_secret_with_env_key_names(self):
        set_secret("GLM_API_KEY", "test-key")
        set_secret("GLM_MODEL", "test-model")
        set_secret("GLM_BASE_URL", "https://api.test.com")
        self.assertEqual(get_secret("GLM_API_KEY"), "test-key")
        self.assertEqual(get_secret("GLM_MODEL"), "test-model")
        self.assertEqual(get_secret("GLM_BASE_URL"), "https://api.test.com")

    def test_empty_value_is_still_stored(self):
        set_secret("KEY", "")
        self.assertTrue(has_secret("KEY"))
        self.assertEqual(get_secret("KEY"), "")

    def test_overwrite_with_empty(self):
        set_secret("KEY", "nonempty")
        set_secret("KEY", "")
        self.assertEqual(get_secret("KEY"), "")
        self.assertTrue(has_secret("KEY"))

    def test_url_value(self):
        url = "https://api.example.com/v1/chat/completions?model=gpt-4"
        set_secret("URL", url)
        self.assertEqual(get_secret("URL"), url)

    def test_json_value(self):
        json_val = '{"key": "value", "nested": {"a": 1}}'
        set_secret("JSON", json_val)
        self.assertEqual(get_secret("JSON"), json_val)

    def test_base64_value(self):
        b64 = "SGVsbG8gV29ybGQ="
        set_secret("B64", b64)
        self.assertEqual(get_secret("B64"), b64)


if __name__ == "__main__":
    unittest.main()
