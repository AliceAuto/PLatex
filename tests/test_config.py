from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from platex_client.config import load_config


class ConfigTests(unittest.TestCase):
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

            previous_api_key = os.environ.get("GLM_API_KEY")
            previous_model = os.environ.get("GLM_MODEL")
            previous_base_url = os.environ.get("GLM_BASE_URL")
            for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
                os.environ.pop(key, None)

            try:
                config = load_config(config_path)
                config.apply_environment()

                self.assertEqual(config.glm_api_key, "yaml-key")
                self.assertEqual(config.glm_model, "glm-test-model")
                self.assertEqual(config.glm_base_url, "https://example.invalid/v1")
                self.assertEqual(config.interval, 1.25)
                self.assertEqual(os.environ.get("GLM_API_KEY"), "yaml-key")
            finally:
                if previous_api_key is None:
                    os.environ.pop("GLM_API_KEY", None)
                else:
                    os.environ["GLM_API_KEY"] = previous_api_key
                if previous_model is None:
                    os.environ.pop("GLM_MODEL", None)
                else:
                    os.environ["GLM_MODEL"] = previous_model
                if previous_base_url is None:
                    os.environ.pop("GLM_BASE_URL", None)
                else:
                    os.environ["GLM_BASE_URL"] = previous_base_url


if __name__ == "__main__":
    unittest.main()