from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType

from .models import OcrProcessor
from .script_base import ScriptBase
from .script_registry import ScriptRegistry

logger = logging.getLogger("platex.loader")


def load_script_processor(script_path: Path) -> "OcrProcessorAdapter":
    """Load a script file and return an OcrProcessor-compatible adapter.

    Supports both:
    - New-style scripts with create_script() -> ScriptBase
    - Legacy scripts with process_image(image_bytes, context) function
    """
    if not script_path.exists():
        raise FileNotFoundError(f"OCR script not found: {script_path}")

    module_name = f"platex_script_{script_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Try new-style: module has create_script() -> ScriptBase
    create_fn = getattr(module, "create_script", None)
    if callable(create_fn):
        script = create_fn()
        if isinstance(script, ScriptBase):
            return OcrProcessorAdapter(script)

    # Try legacy: module has process_image() function
    process_image_fn = getattr(module, "process_image", None)
    if callable(process_image_fn):
        return LegacyProcessor(module, script_path)

    raise RuntimeError(f"Script {script_path} has neither create_script() nor process_image()")


class OcrProcessorAdapter(OcrProcessor):
    """Wraps a ScriptBase with OCR capability as an OcrProcessor."""

    def __init__(self, script: ScriptBase) -> None:
        self._script = script

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        return self._script.process_image(image_bytes, context)


class LegacyProcessor(OcrProcessor):
    """Wraps a legacy module-level process_image function as an OcrProcessor."""

    def __init__(self, module: ModuleType, source_path: Path) -> None:
        self._module = module
        self._source_path = source_path

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        process_image = getattr(self._module, "process_image", None)
        if not callable(process_image):
            raise RuntimeError(f"Script {self._source_path} does not define process_image(image_bytes, context)")

        result = process_image(image_bytes, context or {})
        if isinstance(result, str):
            latex = result
        elif isinstance(result, dict) and "latex" in result:
            latex = str(result["latex"])
        else:
            raise RuntimeError(f"Script {self._source_path} returned an unsupported result")

        latex = latex.strip()
        if not latex:
            raise RuntimeError(f"Script {self._source_path} returned empty LaTeX")
        return latex