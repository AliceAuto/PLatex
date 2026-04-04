from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from .models import OcrProcessor


@dataclass(slots=True)
class ScriptProcessor(OcrProcessor):
    module: ModuleType
    source_path: Path

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        process_image = getattr(self.module, "process_image", None)
        if not callable(process_image):
            raise RuntimeError(f"Script {self.source_path} does not define process_image(image_bytes, context)")

        result = process_image(image_bytes, context or {})
        if isinstance(result, str):
            latex = result
        elif isinstance(result, dict) and "latex" in result:
            latex = str(result["latex"])
        else:
            raise RuntimeError(f"Script {self.source_path} returned an unsupported result")

        latex = latex.strip()
        if not latex:
            raise RuntimeError(f"Script {self.source_path} returned empty LaTeX")
        return latex


def load_script_processor(script_path: Path) -> ScriptProcessor:
    if not script_path.exists():
        raise FileNotFoundError(f"OCR script not found: {script_path}")

    module_name = f"platex_script_{script_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return ScriptProcessor(module=module, source_path=script_path)