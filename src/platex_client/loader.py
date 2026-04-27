from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType

from .models import OcrProcessor
from .script_base import ScriptBase
from .script_safety import (
    _check_dangerous_patterns,
    _extract_legacy_result,
    _load_script_module,
    validate_script_path,
)

logger = logging.getLogger("platex.loader")


def load_script_processor(script_path: Path) -> OcrProcessorAdapter | LegacyProcessor:
    validate_script_path(script_path)

    resolved = script_path.resolve()
    logger.info("Loading script processor from %s (size=%d)", resolved, resolved.stat().st_size)

    _check_dangerous_patterns(script_path)

    module = _load_script_module(script_path)

    create_fn = getattr(module, "create_script", None)
    if callable(create_fn):
        script = create_fn()
        if isinstance(script, ScriptBase):
            return OcrProcessorAdapter(script)
        if script is not None:
            logger.warning("create_script() returned %s (expected ScriptBase)", type(script).__name__)

    process_image_fn = getattr(module, "process_image", None)
    if callable(process_image_fn):
        return LegacyProcessor(module, script_path)

    raise RuntimeError(f"Script {script_path} has neither create_script() nor process_image()")


class OcrProcessorAdapter(OcrProcessor):
    def __init__(self, script: ScriptBase) -> None:
        self._script = script

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        return self._script.process_image(image_bytes, context)


class LegacyProcessor(OcrProcessor):
    def __init__(self, module: ModuleType, source_path: Path) -> None:
        self._module = module
        self._source_path = source_path

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        process_image = getattr(self._module, "process_image", None)
        if not callable(process_image):
            raise RuntimeError(f"Script {self._source_path} does not define process_image(image_bytes, context)")

        result = process_image(image_bytes, context or {})
        return _extract_legacy_result(self._module, self._source_path, result)
