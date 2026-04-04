from __future__ import annotations

import base64
import os

import requests


def process_image(image_bytes: bytes, context: dict[str, object] | None = None) -> str:
    app_id = os.getenv("MATHPIX_APP_ID")
    app_key = os.getenv("MATHPIX_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("Please set MATHPIX_APP_ID and MATHPIX_APP_KEY before starting the client.")

    payload = {
        "src": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}",
        "formats": ["latex_styled"],
        "ocr": ["math", "text"],
        "skip_recrop": True,
    }
    headers = {
        "app_id": app_id,
        "app_key": app_key,
        "Content-type": "application/json",
    }
    response = requests.post("https://api.mathpix.com/v3/text", json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    data = response.json()
    latex = data.get("latex_styled") or data.get("latex") or data.get("text")
    if not latex:
        raise RuntimeError(f"Mathpix returned no usable OCR result: {data}")

    return str(latex).strip()