from __future__ import annotations

import base64
import json
import os

import requests


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
    response = requests.post(base_url, headers=headers, json=payload, timeout=90)
    response.raise_for_status()

    data = response.json()
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"GLM returned invalid response: {json.dumps(data, ensure_ascii=False)}")

    message = choices[0].get("message", {})
    latex = _extract_latex(message.get("content"))
    if not latex:
        raise RuntimeError(f"GLM returned no usable OCR result: {json.dumps(data, ensure_ascii=False)}")

    return latex