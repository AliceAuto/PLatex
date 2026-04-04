from __future__ import annotations

import base64
import json
import os
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


logger = logging.getLogger("platex.script.glm")


def _copy_text_to_clipboard(text: str) -> None:
    # Prefer the client's hardened Windows clipboard path when available.
    try:
        from platex_client.windows_clipboard import set_text  # type: ignore

        set_text(text)
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clipboard write failed: %s", exc)
        raise


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


def process_image(image_bytes: bytes, context: dict[str, object] | None = None) -> str:
    api_key = os.getenv("GLM_API_KEY")
    if not api_key:
        raise RuntimeError("Please set GLM_API_KEY before starting the client.")

    model = os.getenv("GLM_MODEL", "glm-4.1v-thinking-flash")
    base_url = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")

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

    try:
        _copy_text_to_clipboard(latex)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR result was not copied to clipboard: %s", exc)
    return latex