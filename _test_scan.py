from pathlib import Path
from platex_client.script_safety import scan_script_source

w, b = scan_script_source(Path(r'D:\Projects\PLatex\scripts\glm_vision_ocr.py'))
with open(r'D:\Projects\PLatex\_scan_result.txt', 'w', encoding='utf-8') as f:
    f.write(f"Dangerous: {w}\nBlocked: {b}\n")
