from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from platex_client.script_base import ScriptBase


def _extract_latex(content: object) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_fragments: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_fragments.append(part["text"])
        return "\n".join(text_fragments).strip()

    return ""


class OcrScript(ScriptBase):
    """GLM Vision OCR script: captures clipboard images and extracts LaTeX."""

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._model: str = "glm-4.1v-thinking-flash"
        self._base_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    @property
    def name(self) -> str:
        return "glm_vision_ocr"

    @property
    def display_name(self) -> str:
        return "OCR \u8bc6\u522b"

    @property
    def description(self) -> str:
        return "\u526a\u8d34\u677f\u56fe\u7247 OCR \u8bc6\u522b\uff0c\u63d0\u53d6\u6570\u5b66\u516c\u5f0f\u4e3a LaTeX"

    def has_ocr_capability(self) -> bool:
        return True

    def load_config(self, config: dict[str, Any]) -> None:
        if config.get("api_key"):
            self._api_key = config["api_key"]
        elif os.getenv("GLM_API_KEY"):
            self._api_key = os.getenv("GLM_API_KEY")
        if config.get("model"):
            self._model = config["model"]
        elif os.getenv("GLM_MODEL"):
            self._model = os.getenv("GLM_MODEL", self._model)
        if config.get("base_url"):
            self._base_url = config["base_url"]
        elif os.getenv("GLM_BASE_URL"):
            self._base_url = os.getenv("GLM_BASE_URL", self._base_url)

    def save_config(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self._api_key:
            result["api_key"] = self._api_key
        result["model"] = self._model
        result["base_url"] = self._base_url
        return result

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        api_key = self._api_key or os.getenv("GLM_API_KEY")
        if not api_key:
            raise RuntimeError("Please set GLM_API_KEY before starting the client.")

        model = self._model
        base_url = self._base_url

        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = (
            "Read the image content and respond according to these rules:\n"
            "1. If the image contains mathematical formulas or equations:\n"
            "   - For inline formulas: wrap in $...$ delimiters\n"
            "   - For display/block formulas: wrap in $$...$$ delimiters\n"
            "   - Output only valid LaTeX code inside the delimiters\n"
            "2. If the image contains text without formulas: output the text as-is\n"
            "3. For mixed content (text + formulas): output text with formulas wrapped in $ or $$\n"
            "4. Do NOT add markdown fences, code blocks, explanations, or any meta-text\n"
            "5. Output only the content itself"
        )

        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(base_url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=90) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GLM HTTP error {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"GLM request failed: {exc.reason}") from exc

        data = json.loads(response_body)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"GLM returned invalid response: {json.dumps(data, ensure_ascii=False)}")

        message = choices[0].get("message", {})
        latex = _extract_latex(message.get("content"))
        if not latex:
            raise RuntimeError(f"GLM returned no usable OCR result: {json.dumps(data, ensure_ascii=False)}")

        return latex

    def create_settings_widget(self, parent=None):
        try:
            from PyQt6.QtWidgets import (
                QWidget,
                QVBoxLayout,
                QHBoxLayout,
                QLabel,
                QLineEdit,
                QPushButton,
                QMessageBox,
            )
        except ImportError:
            return None

        script_ref = self

        class _OcrSettingsWidget(QWidget):
            def __init__(self, inner_parent: QWidget | None = None) -> None:
                super().__init__(inner_parent)
                layout = QVBoxLayout(self)
                layout.setContentsMargins(12, 12, 12, 12)
                layout.setSpacing(10)

                # API Key
                layout.addWidget(QLabel("API Key:"))
                self._api_key_edit = QLineEdit()
                self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
                self._api_key_edit.setPlaceholderText("GLM API Key")
                if script_ref._api_key:
                    self._api_key_edit.setText(script_ref._api_key)
                layout.addWidget(self._api_key_edit)

                # Model
                layout.addWidget(QLabel("Model:"))
                self._model_edit = QLineEdit()
                self._model_edit.setPlaceholderText("e.g. glm-4.1v-thinking-flash")
                self._model_edit.setText(script_ref._model)
                layout.addWidget(self._model_edit)

                # Base URL
                layout.addWidget(QLabel("Base URL:"))
                self._base_url_edit = QLineEdit()
                self._base_url_edit.setText(script_ref._base_url)
                layout.addWidget(self._base_url_edit)

                layout.addStretch()

            def save_settings(self) -> None:
                script_ref._api_key = self._api_key_edit.text().strip() or None
                script_ref._model = self._model_edit.text().strip() or "glm-4.1v-thinking-flash"
                script_ref._base_url = self._base_url_edit.text().strip() or "https://open.bigmodel.cn/api/paas/v4/chat/completions"
                if script_ref._api_key:
                    os.environ["GLM_API_KEY"] = script_ref._api_key
                if script_ref._model:
                    os.environ["GLM_MODEL"] = script_ref._model
                if script_ref._base_url:
                    os.environ["GLM_BASE_URL"] = script_ref._base_url

        return _OcrSettingsWidget(parent)


def create_script() -> ScriptBase:
    return OcrScript()


# Legacy compatibility: module-level process_image function
def process_image(image_bytes: bytes, context: dict[str, object] | None = None) -> str:
    script = OcrScript()
    script.load_config({})
    return script.process_image(image_bytes, context)