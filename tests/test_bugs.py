from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from platex_client.config import AppConfig, ConfigStore, _parse_bool, load_config
from platex_client.secrets import set_secret, has_secret, get_secret, delete_secret, clear_all


class TestBug1_ApplyEnvironmentLeaksSecretsToOSEnviron(unittest.TestCase):
    """BUG #1 [严重] → FIXED: apply_environment() 不再将密钥泄露到 os.environ

    修复前：apply_environment() 同时调用了 set_secret() 和
    os.environ[...] = ...，导致密钥泄露到环境变量。
    修复后：密钥仅存入内存 secrets 模块，不再写入 os.environ。
    """

    def setUp(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_api_key_not_leaked_to_os_environ(self):
        cfg = AppConfig(glm_api_key="secret-key-12345")
        cfg.apply_environment()
        self.assertIsNone(os.environ.get("GLM_API_KEY"),
                          "FIXED: apply_environment() 不再将 API 密钥泄露到 os.environ")
        self.assertEqual(get_secret("GLM_API_KEY"), "secret-key-12345",
                         "密钥应存入 secrets 模块")

    def test_model_not_leaked_to_os_environ(self):
        cfg = AppConfig(glm_model="glm-4")
        cfg.apply_environment()
        self.assertIsNone(os.environ.get("GLM_MODEL"),
                          "FIXED: apply_environment() 不再将模型名泄露到 os.environ")
        self.assertEqual(get_secret("GLM_MODEL"), "glm-4",
                         "模型名应存入 secrets 模块")

    def test_base_url_not_leaked_to_os_environ(self):
        cfg = AppConfig(glm_base_url="https://api.test.com")
        cfg.apply_environment()
        self.assertIsNone(os.environ.get("GLM_BASE_URL"),
                          "FIXED: apply_environment() 不再将 base URL 泄露到 os.environ")
        self.assertEqual(get_secret("GLM_BASE_URL"), "https://api.test.com",
                         "base URL 应存入 secrets 模块")

    def test_secrets_stored_in_memory_not_environ(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("glm_api_key: secret-key-12345\n", encoding="utf-8")
            config = load_config(config_path)
            config.apply_environment()
            self.assertIsNone(os.environ.get("GLM_API_KEY"),
                              "FIXED: 密钥不再泄露到 os.environ")
            self.assertEqual(get_secret("GLM_API_KEY"), "secret-key-12345",
                             "密钥应存入 secrets 模块")


class TestBug2_ApplyEnvironmentOverwritesExistingOSEnviron(unittest.TestCase):
    """BUG #2 [严重] → FIXED: apply_environment() 不再操作 os.environ

    修复前：apply_environment() 会覆盖 os.environ 中已有的值。
    修复后：密钥仅存入内存 secrets 模块，不影响 os.environ。
    """

    def setUp(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_does_not_overwrite_existing_api_key(self):
        os.environ["GLM_API_KEY"] = "user-set-key"
        cfg = AppConfig(glm_api_key="config-key")
        cfg.apply_environment()
        self.assertEqual(os.environ.get("GLM_API_KEY"), "user-set-key",
                         "FIXED: apply_environment() 不再覆盖 os.environ 中的值")

    def test_does_not_overwrite_existing_model(self):
        os.environ["GLM_MODEL"] = "user-model"
        cfg = AppConfig(glm_model="config-model")
        cfg.apply_environment()
        self.assertEqual(os.environ.get("GLM_MODEL"), "user-model",
                         "FIXED: apply_environment() 不再覆盖 os.environ 中的 GLM_MODEL")

    def test_respects_existing_secret(self):
        set_secret("GLM_API_KEY", "existing-secret")
        cfg = AppConfig(glm_api_key="new-key")
        cfg.apply_environment()
        self.assertEqual(get_secret("GLM_API_KEY"), "existing-secret",
                         "当 secrets 字典中已有值时，不会被覆盖（正确行为）")


class TestBug9_ScriptRegistryNoPathValidation(unittest.TestCase):
    """BUG #9 [中] → FIXED: ScriptRegistry 现在有危险模式扫描和阻止

    修复前：危险脚本可以无警告地加载执行。
    修复后：包含危险模式（如 os.system）的脚本默认被阻止，
    除非设置 PLATEX_ALLOW_UNSAFE_SCRIPTS=1 环境变量。
    """

    def test_load_from_arbitrary_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            from platex_client.script_registry import ScriptRegistry
            registry = ScriptRegistry()
            entry = registry._load_script_file(script_path)
            self.assertIsNotNone(entry,
                                 "安全脚本应能正常加载")

    def test_dangerous_code_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dangerous.py"
            script_path.write_text(
                "import os\nos.system('echo pwned')\n"
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            from platex_client.script_registry import ScriptRegistry
            registry = ScriptRegistry()
            with self.assertRaises(ValueError,
                                   msg="FIXED: 危险脚本现在被阻止加载"):
                registry._load_script_file(script_path)

    def test_dangerous_code_allowed_with_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dangerous.py"
            script_path.write_text(
                "import socket\n"
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            from platex_client.script_registry import ScriptRegistry
            old_val = os.environ.get("PLATEX_ALLOW_UNSAFE_SCRIPTS")
            try:
                os.environ["PLATEX_ALLOW_UNSAFE_SCRIPTS"] = "1"
                registry = ScriptRegistry()
                entry = registry._load_script_file(script_path)
                self.assertIsNotNone(entry,
                                     "设置环境变量后，危险脚本可加载")
            finally:
                if old_val is None:
                    os.environ.pop("PLATEX_ALLOW_UNSAFE_SCRIPTS", None)
                else:
                    os.environ["PLATEX_ALLOW_UNSAFE_SCRIPTS"] = old_val


class TestBug10_ScheduleRepeatingDeadTimer(unittest.TestCase):
    """BUG #10 [低]: schedule_repeating 创建了从未使用的死定时器

    代码中创建了一个 Timer 和 _ScheduledTask.__new__ 对象，
    但它们从未被启动或取消，造成资源浪费和代码混淆。
    """

    def test_repeating_still_works_despite_dead_timer(self):
        from platex_client.script_context import SchedulerAPI
        scheduler = SchedulerAPI()
        count = {"value": 0}
        event = threading.Event()

        def callback():
            count["value"] += 1
            if count["value"] >= 2:
                event.set()

        task = scheduler.schedule_repeating(0.1, callback)
        event.wait(timeout=3.0)
        task.cancel()
        scheduler.cancel_all()
        self.assertGreaterEqual(count["value"], 2,
                                "尽管有死定时器，重复调度仍应正常工作")


class TestBug11_SecretsModuleNotThreadSafe(unittest.TestCase):
    """BUG #11 [低] → FIXED: secrets 模块现在有线程锁保护

    修复前：并发访问可能导致数据竞争。
    修复后：所有操作都通过 threading.Lock 保护。
    """

    def test_concurrent_access(self):
        errors = []

        def writer():
            try:
                for i in range(100):
                    set_secret("KEY", f"value_{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    get_secret("KEY")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)


class TestBug12_ScriptBaseUndeclaredAttribute(unittest.TestCase):
    """BUG #12 [中]: ScriptBase._tray_action_callback 未声明

    set_tray_action_callback() 设置了 self._tray_action_callback，
    但该属性未在类中声明。如果 ScriptBase 使用 slots=True，
    会导致 AttributeError。
    """

    def _make_script(self):
        from platex_client.script_base import ScriptBase

        class TestScript(ScriptBase):
            @property
            def name(self):
                return "test"

            @property
            def display_name(self):
                return "Test"

            @property
            def description(self):
                return "Test script"

        return TestScript()

    def test_tray_action_callback_undeclared(self):
        script = self._make_script()
        script.set_tray_action_callback(lambda a, p: None)
        self.assertTrue(hasattr(script, "_tray_action_callback"),
                        "BUG: _tray_action_callback 被设置但未在 ScriptBase 中声明")


class TestBug13_ConfigStoreSaveIgnoresCustomPath(unittest.TestCase):
    """BUG #13 [中]: ConfigStore._save_to_disk 总是保存到全局配置目录

    如果用户从自定义路径加载配置，保存时会写入全局配置目录
    而非原始加载路径，可能导致配置文件分散。
    """

    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_save_ignores_custom_load_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_path = Path(temp_dir) / "custom_config.yaml"
            custom_path.write_text("interval: 1.5\n", encoding="utf-8")

            cfg = load_config(custom_path)
            self.assertEqual(cfg.interval, 1.5)

            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 2.0})

            from platex_client.config_manager import config_file_path
            global_path = config_file_path()
            if global_path != custom_path:
                self.assertTrue(global_path.exists(),
                                "BUG: 保存到了全局路径而非自定义路径")


class TestBug8_ConfigStoreNoIntervalValidation(unittest.TestCase):
    """BUG #8 [中] → FIXED: ConfigStore 现在验证 interval 值

    修复前：interval=0 会导致轮询忙循环，负数 interval 无意义。
    修复后：ConfigStore 将这些值钳制到最小值（0.1）。
    """

    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_zero_interval_clamped(self):
        store = ConfigStore.instance()
        store.request_update_and_save({"interval": 0})
        self.assertGreaterEqual(store.config.interval, 0.1,
                                "FIXED: interval=0 is now clamped to 0.1 minimum")

    def test_negative_interval_clamped(self):
        store = ConfigStore.instance()
        store.request_update_and_save({"interval": -1.0})
        self.assertGreaterEqual(store.config.interval, 0.1,
                                "FIXED: negative interval is now clamped to 0.1 minimum")


class TestOriginalTestFailures(unittest.TestCase):
    """验证原始测试套件中的修复效果"""

    def setUp(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_secrets_not_in_environ_after_fix(self):
        """修复后：密钥不再泄露到 os.environ，仅存入 secrets 模块"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "glm_api_key: yaml-key\nglm_model: glm-test-model\n"
                "glm_base_url: https://example.invalid/v1\ninterval: 1.25\n",
                encoding="utf-8",
            )
            config = load_config(config_path)
            config.apply_environment()
            self.assertIsNone(os.environ.get("GLM_API_KEY"),
                              "FIXED: 密钥不再泄露到 os.environ")
            self.assertEqual(get_secret("GLM_API_KEY"), "yaml-key",
                             "密钥应存入 secrets 模块")


if __name__ == "__main__":
    unittest.main()
