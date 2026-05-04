from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from urllib.parse import urlparse

from platex_client.script_base import ScriptBase

logger = logging.getLogger("platex.scripts.ocr")

_MAX_IMAGE_BYTES = 10 * 1024 * 1024

_ALLOWED_URL_SCHEMES = {"https", "http"}
_ALLOWED_URL_HOSTNAMES = {
    "open.bigmodel.cn",
    "bigmodel.cn",
    "api.bigmodel.cn",
    "api.zhipuai.com",
    "open.zhipuai.com",
}


def _validate_base_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("base_url is required but was not provided")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"Invalid base_url scheme '{parsed.scheme}': only https and http are allowed. "
            f"Got: {url}"
        )
    if not parsed.hostname:
        raise ValueError(f"Invalid base_url (no hostname): {url}")
    hostname_lower = parsed.hostname.lower()
    is_allowed = any(
        hostname_lower == allowed or hostname_lower.endswith("." + allowed)
        for allowed in _ALLOWED_URL_HOSTNAMES
    )
    if not is_allowed and hostname_lower not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"base_url hostname '{parsed.hostname}' is not in the allowed list. "
            f"Allowed: {', '.join(sorted(_ALLOWED_URL_HOSTNAMES))}. "
            f"If you need to use a custom endpoint, add it to _ALLOWED_URL_HOSTNAMES."
        )
    if parsed.scheme != "https" and hostname_lower not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"base_url uses insecure http scheme for host '{parsed.hostname}'. "
            f"API keys would be sent in cleartext. Use https instead."
        )
    return url


_VISION_MODELS = {
    "glm-4v", "glm-4v-plus", "glm-4v-flash",
    "glm-4.1v", "glm-4.1v-thinking", "glm-4.1v-thinking-flash",
    "glm-4.1v-flash", "glm-4.1v-plus",
}


def _sanitize_response_for_log(data: dict | str, max_len: int = 200) -> str:
    raw = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
    api_key_pattern = re.compile(r'(api[_-]?key|token|secret|authorization)["\s:=]+(["\w\-]{8})["\w\-]*', re.IGNORECASE)
    raw = api_key_pattern.sub(r'\1=***REDACTED***', raw)
    if len(raw) > max_len:
        raw = raw[:max_len] + "..."
    return raw


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


def _sanitize_error_detail(text: str, max_len: int = 200) -> str:
    sanitized = text[:max_len]
    sanitized = re.sub(r'(Bearer\s+)[A-Za-z0-9_\-.]+', r'\1***', sanitized)
    sanitized = re.sub(r'(api[_-]?key["\s:=]+)["\w\-.]+', r'\1***', sanitized)
    return sanitized


def _validate_api_key(api_key: str, model: str, base_url: str) -> tuple[bool, str]:
    if not api_key:
        return False, "API Key is empty"
    try:
        base_url = _validate_base_url(base_url)
    except ValueError as exc:
        return False, str(exc)
    payload = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = json.dumps(payload).encode("utf-8")
    request = Request(base_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8", errors="replace")
        data = json.loads(response_body)
        if isinstance(data.get("choices"), list) and len(data["choices"]) > 0:
            return True, "OK"
        error_msg = str(data.get("error", data.get("message", "")))
        if error_msg:
            return False, _sanitize_error_detail(error_msg)
        return False, _sanitize_response_for_log(data)
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401:
            return False, "Authentication failed: invalid API Key"
        return False, f"HTTP {exc.code}: {_sanitize_error_detail(error_body)}"
    except URLError as exc:
        return False, f"Network error: {exc.reason}"
    except (TimeoutError, ConnectionError, OSError) as exc:
        return False, f"Connection error: {exc}"
    except Exception as exc:
        return False, str(exc)


class OcrScript(ScriptBase):
    """GLM Vision OCR script: captures clipboard images and extracts LaTeX."""

    def __init__(self) -> None:
        super().__init__()
        self._api_key: str | None = None
        self._model: str | None = None
        self._base_url: str | None = None

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
        api_key_val = config.get("api_key", "")
        if api_key_val and not re.match(r"^.{1,4}\*+$", api_key_val):
            self._api_key = api_key_val
        if config.get("model"):
            self._model = config["model"]
        if config.get("base_url"):
            self._base_url = _validate_base_url(config["base_url"])

    def save_config(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self._api_key:
            result["api_key"] = self._api_key
        if self._model:
            result["model"] = self._model
        if self._base_url:
            result["base_url"] = self._base_url
        return result

    def _is_vision_model(self, model: str) -> bool:
        model_lower = model.lower().strip()
        for vm in _VISION_MODELS:
            if model_lower.startswith(vm):
                return True
        if any(kw in model_lower for kw in ("v-plus", "v-flash", "vision", "4v", "4.1v")):
            return True
        return False

    def _resize_image(self, image_bytes: bytes, max_pixels: int = 2048) -> tuple[bytes, str]:
        """Resize image if too large. Returns (image_bytes, format)."""
        try:
            from PIL import Image

            img = Image.open(BytesIO(image_bytes))
            fmt = img.format or "PNG"
            if fmt.upper() == "JPEG":
                fmt = "JPEG"
            else:
                fmt = "PNG"
            w, h = img.size
            if w <= max_pixels and h <= max_pixels and len(image_bytes) <= _MAX_IMAGE_BYTES:
                return image_bytes, fmt
            img.thumbnail((max_pixels, max_pixels))
            buf = BytesIO()
            save_fmt = "JPEG" if fmt == "JPEG" else "PNG"
            kwargs = {"format": save_fmt}
            if save_fmt == "JPEG":
                kwargs["quality"] = 85
            else:
                kwargs["optimize"] = True
            img.save(buf, **kwargs)
            return buf.getvalue(), save_fmt
        except Exception:
            if len(image_bytes) <= _MAX_IMAGE_BYTES:
                return image_bytes, "PNG"
            raise RuntimeError(f"Image is too large ({len(image_bytes)} bytes) and could not be resized")

    _MAX_RETRIES = 2
    _RETRY_DELAY = 1.0

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        api_key = self._api_key
        if not api_key:
            raise RuntimeError("API key not configured. Please set api_key in the OCR script config.")

        model = self._model
        if not model:
            raise RuntimeError("Model not configured. Please set model in the OCR script config.")

        base_url = self._base_url
        if not base_url:
            raise RuntimeError("Base URL not configured. Please set base_url in the OCR script config.")

        image_bytes, img_fmt = self._resize_image(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        mime = "image/jpeg" if img_fmt == "JPEG" else "image/png"

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
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_base64}"}},
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps(payload).encode("utf-8")

        last_exc: Exception | None = None
        for attempt in range(1, self._MAX_RETRIES + 2):
            request = Request(base_url, data=body, headers=headers, method="POST")
            try:
                with urlopen(request, timeout=90) as response:
                    response_body = response.read().decode("utf-8", errors="replace")
                break
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 400 and "does not support image" in error_body:
                    raise RuntimeError(
                        f"Model '{model}' does not support image input. "
                        f"Please switch to a vision model (e.g. glm-4.1v-thinking-flash) "
                        f"in the OCR settings tab."
                    ) from exc
                if exc.code in (429, 500, 502, 503, 504) and attempt <= self._MAX_RETRIES:
                    last_exc = exc
                    delay = self._RETRY_DELAY * attempt
                    logger.warning("GLM HTTP %d, retrying in %.1fs (attempt %d/%d)", exc.code, delay, attempt, self._MAX_RETRIES + 1)
                    import time
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"GLM HTTP error {exc.code}: {_sanitize_error_detail(error_body)}") from exc
            except URLError as exc:
                if attempt <= self._MAX_RETRIES:
                    last_exc = exc
                    delay = self._RETRY_DELAY * attempt
                    logger.warning("GLM URL error, retrying in %.1fs (attempt %d/%d): %s", delay, attempt, self._MAX_RETRIES + 1, exc.reason)
                    import time
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"GLM request failed: {exc.reason}") from exc
            except (TimeoutError, ConnectionError, OSError) as exc:
                if attempt <= self._MAX_RETRIES:
                    last_exc = exc
                    delay = self._RETRY_DELAY * attempt
                    logger.warning("GLM network error, retrying in %.1fs (attempt %d/%d): %s", delay, attempt, self._MAX_RETRIES + 1, exc)
                    import time
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"GLM network error: {exc}") from exc
        else:
            raise RuntimeError(f"GLM request failed after {self._MAX_RETRIES + 1} attempts") from last_exc

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GLM returned invalid JSON: {exc}") from exc
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            error_msg = str(data.get("error", data.get("message", "")))
            if "does not support image" in error_msg or ("not support" in error_msg.lower() and "image" in error_msg.lower()):
                raise RuntimeError(
                    f"Model '{model}' does not support image input. "
                    f"Please switch to a vision model (e.g. glm-4.1v-thinking-flash) "
                    f"in the OCR settings tab."
                )
            raise RuntimeError(f"GLM returned invalid response: {_sanitize_response_for_log(data)}")

        message = choices[0].get("message", {})
        latex = _extract_latex(message.get("content"))
        if not latex:
            raise RuntimeError(f"GLM returned no usable OCR result: {_sanitize_response_for_log(data)}")

        return latex

    def create_settings_widget(self, parent=None):
        try:
            from PyQt6.QtCore import pyqtSignal, QObject
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

        from platex_client.i18n import t as _t

        script_ref = self

        class _ValidateSignals(QObject):
            finished = pyqtSignal(bool, str)

        class _OcrSettingsWidget(QWidget):
            def __init__(self, inner_parent: QWidget | None = None) -> None:
                super().__init__(inner_parent)
                layout = QVBoxLayout(self)
                layout.setContentsMargins(12, 12, 12, 12)
                layout.setSpacing(10)

                layout.addWidget(QLabel("API Key:"))
                api_key_row = QHBoxLayout()
                self._api_key_edit = QLineEdit()
                self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
                self._api_key_edit.setPlaceholderText("GLM API Key")
                if script_ref._api_key:
                    self._api_key_edit.setText(script_ref._api_key)
                api_key_row.addWidget(self._api_key_edit, 1)

                self._btn_verify = QPushButton(_t("btn_verify_api_key"))
                self._btn_verify.setFixedWidth(60)
                api_key_row.addWidget(self._btn_verify)
                layout.addLayout(api_key_row)

                self._verify_status = QLabel("")
                self._verify_status.setWordWrap(True)
                self._verify_status.setStyleSheet("font-size: 12px; color: rgba(138, 144, 168, 200);")
                layout.addWidget(self._verify_status)

                self._validate_signals = _ValidateSignals()
                self._validate_signals.finished.connect(self._on_validate_finished)
                self._btn_verify.clicked.connect(self._start_validate)

                layout.addWidget(QLabel("Model:"))
                self._model_edit = QLineEdit()
                self._model_edit.setPlaceholderText("e.g. glm-4.1v-thinking-flash")
                self._model_edit.setText(script_ref._model)
                layout.addWidget(self._model_edit)

                self._model_warning = QLabel("")
                self._model_warning.setStyleSheet("color: rgba(212, 120, 126, 220); font-size: 12px;")
                self._model_warning.setWordWrap(True)
                layout.addWidget(self._model_warning)
                self._model_edit.textChanged.connect(self._check_model)
                self._check_model()

                layout.addWidget(QLabel("Base URL:"))
                self._base_url_edit = QLineEdit()
                self._base_url_edit.setText(script_ref._base_url)
                layout.addWidget(self._base_url_edit)

                layout.addStretch()

            def _check_model(self) -> None:
                model = self._model_edit.text().strip()
                if model and not script_ref._is_vision_model(model):
                    self._model_warning.setText(
                        "\u26a0 \u5f53\u524d\u6a21\u578b\u4e0d\u652f\u6301\u56fe\u7247\u8f93\u5165\uff0cOCR \u5c06\u5931\u8d25\u3002"
                        "\u8bf7\u4f7f\u7528\u89c6\u89c9\u6a21\u578b\uff08\u5982 glm-4.1v-thinking-flash\uff09\u3002"
                    )
                else:
                    self._model_warning.setText("")

            def _start_validate(self) -> None:
                api_key = self._api_key_edit.text().strip()
                if not api_key:
                    self._verify_status.setStyleSheet("color: rgba(212, 120, 126, 220); font-size: 12px;")
                    self._verify_status.setText(_t("api_key_verify_empty"))
                    return
                if re.match(r"^.{1,4}\*+$", api_key):
                    self._verify_status.setStyleSheet("color: rgba(212, 120, 126, 220); font-size: 12px;")
                    self._verify_status.setText(_t("api_key_verify_masked"))
                    return

                self._btn_verify.setEnabled(False)
                self._btn_verify.setText("...")
                self._verify_status.setStyleSheet("color: rgba(138, 144, 168, 200); font-size: 12px;")
                self._verify_status.setText(_t("api_key_verify_validating"))

                model = self._model_edit.text().strip()
                if not model:
                    self._verify_status.setStyleSheet("color: rgba(212, 120, 126, 220); font-size: 12px;")
                    self._verify_status.setText("Model is required")
                    return
                base_url = self._base_url_edit.text().strip()
                if not base_url:
                    self._verify_status.setStyleSheet("color: rgba(212, 120, 126, 220); font-size: 12px;")
                    self._verify_status.setText("Base URL is required")
                    return
                signals = self._validate_signals

                def _run():
                    ok, msg = _validate_api_key(api_key, model, base_url)
                    signals.finished.emit(ok, msg)

                th = threading.Thread(target=_run, daemon=True)
                th.start()

            def _on_validate_finished(self, ok: bool, msg: str) -> None:
                self._btn_verify.setEnabled(True)
                self._btn_verify.setText(_t("btn_verify_api_key"))
                if ok:
                    self._verify_status.setStyleSheet("color: rgba(140, 196, 144, 220); font-size: 12px;")
                    self._verify_status.setText(_t("api_key_verify_success"))
                else:
                    self._verify_status.setStyleSheet("color: rgba(212, 120, 126, 220); font-size: 12px;")
                    self._verify_status.setText(_t("api_key_verify_failed", error=msg))

            def save_settings(self) -> None:
                script_ref._api_key = self._api_key_edit.text().strip() or None
                script_ref._model = self._model_edit.text().strip() or None
                base_url_val = self._base_url_edit.text().strip()
                if base_url_val:
                    script_ref._base_url = _validate_base_url(base_url_val)
                else:
                    script_ref._base_url = None

        return _OcrSettingsWidget(parent)


def create_script() -> ScriptBase:
    return OcrScript()


# Legacy compatibility: module-level process_image function
def process_image(image_bytes: bytes, context: dict[str, object] | None = None) -> str:
    script = OcrScript()
    script.load_config({})
    return script.process_image(image_bytes, context)