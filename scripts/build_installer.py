from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "platex-client.spec"
ISS_FILE = ROOT / "platex-client.iss"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
INSTALLER_DIR = DIST_DIR / "installer"


def read_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise RuntimeError(f"Cannot find version in {pyproject}")
    return m.group(1)


def run_pyinstaller(clean: bool = True) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_FILE)]
    if clean:
        cmd.insert(2, "--noconfirm")
        cmd.insert(3, "--clean")
    print(f"[build] Running PyInstaller: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(ROOT))


def verify_build() -> None:
    exe_path = DIST_DIR / "platex-client" / "platex-client.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"Build output missing: {exe_path}")

    for script in ("glm_vision_ocr.py", "hotkey_click.py"):
        script_path = DIST_DIR / "platex-client" / "scripts" / script
        if not script_path.exists():
            script_path = DIST_DIR / "platex-client" / "_internal" / "scripts" / script
        if not script_path.exists():
            raise FileNotFoundError(f"Bundled script missing: {script}")

    print(f"[build] Verified: {exe_path} exists")
    print(f"[build] Verified: bundled scripts found")


def run_inno_setup(version: str) -> Path:
    iscc_path = _find_iscc()
    cmd = [str(iscc_path), f"/DMyAppVersion={version}", str(ISS_FILE)]
    print(f"[build] Running Inno Setup: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(ROOT))

    installer_pattern = f"PLatexClient-{version}-win64-setup.exe"
    installer_path = INSTALLER_DIR / installer_pattern
    if not installer_path.exists():
        fallback = INSTALLER_DIR / f"PLatexClient-1.0.0-win64-setup.exe"
        if fallback.exists():
            installer_path = fallback
        else:
            installers = list(INSTALLER_DIR.glob("*.exe")) if INSTALLER_DIR.exists() else []
            if installers:
                installer_path = installers[0]
            else:
                raise FileNotFoundError(f"Installer not found in {INSTALLER_DIR}")

    print(f"[build] Installer created: {installer_path}")
    return installer_path


def _find_iscc() -> Path:
    env_path = shutil.which("ISCC")
    if env_path:
        return Path(env_path)

    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(program_files_x86) / "Inno Setup 6" / "ISCC.exe",
        Path(program_files_x86) / "Inno Setup 5" / "ISCC.exe",
    ]
    if local_app_data:
        candidates.insert(0, Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "ISCC.exe not found. Install Inno Setup 6 or add it to PATH."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PLatex Client installer")
    parser.add_argument(
        "--skip-pyinstaller", action="store_true",
        help="Skip PyInstaller step (use existing dist/)",
    )
    parser.add_argument(
        "--skip-inno", action="store_true",
        help="Skip Inno Setup step",
    )
    parser.add_argument(
        "--version", default=None,
        help="Override version (default: read from pyproject.toml)",
    )
    args = parser.parse_args()

    version = args.version or read_version()
    print(f"[build] Version: {version}")

    if not args.skip_pyinstaller:
        run_pyinstaller(clean=True)

    verify_build()

    if not args.skip_inno:
        installer_path = run_inno_setup(version)
        size_mb = installer_path.stat().st_size / (1024 * 1024)
        print(f"[build] Installer size: {size_mb:.1f} MB")
        print(f"[build] Done! Installer: {installer_path}")
    else:
        print("[build] Skipped Inno Setup step")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
