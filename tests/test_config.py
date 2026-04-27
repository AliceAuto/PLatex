from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from platex_client.config import load_config


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        from platex_client.secrets import clear_all
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        from platex_client.secrets import clear_all
        clear_all()

    def test_load_yaml_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """
glm_api_key: yaml-key
glm_model: glm-test-model
glm_base_url: https://example.invalid/v1
interval: 1.25
""".strip(),
                encoding="utf-8",
            )

            config = load_config(config_path)
            config.apply_environment()

            self.assertEqual(config.glm_api_key, "yaml-key")
            self.assertEqual(config.glm_model, "glm-test-model")
            self.assertEqual(config.glm_base_url, "https://example.invalid/v1")
            self.assertEqual(config.interval, 1.25)

            from platex_client.secrets import get_secret
            self.assertEqual(get_secret("GLM_API_KEY"), "yaml-key")
            self.assertEqual(get_secret("GLM_MODEL"), "glm-test-model")
            self.assertEqual(get_secret("GLM_BASE_URL"), "https://example.invalid/v1")

            self.assertEqual(os.environ.get("GLM_API_KEY"), None)

    def test_secrets_not_in_environ(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "glm_api_key: secret-key-12345\n",
                encoding="utf-8",
            )

            config = load_config(config_path)
            config.apply_environment()

            self.assertIsNone(os.environ.get("GLM_API_KEY"))

            from platex_client.secrets import get_secret
            self.assertEqual(get_secret("GLM_API_KEY"), "secret-key-12345")


if __name__ == "__main__":
    unittest.main()
