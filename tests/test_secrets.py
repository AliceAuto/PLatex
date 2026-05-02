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


class TestSetAndGet(unittest.TestCase):
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


class TestHasSecret(unittest.TestCase):
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


class TestDeleteSecret(unittest.TestCase):
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


class TestClearAll(unittest.TestCase):
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


class TestGetAllKeys(unittest.TestCase):
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


class TestSecretsConcurrency(unittest.TestCase):
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


class TestSecretsEdgeCases(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
