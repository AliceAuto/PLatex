from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC_FILE = ROOT / "platex-client.spec"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
INSTALLER_DIR = DIST_DIR / "installer"
APPDIR = DIST_DIR / "platex-client.AppDir"

APPRUN_URL = "https://github.com/AppImage/AppImageKit/releases/download/continuous/AppRun-x86_64"
APPIMAGETOOL_URL = "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"

DESKTOP_ENTRY = """\
[Desktop Entry]
Name=PLatex Client
Exec=platex-client
Icon=platex-client
Type=Application
Categories=Utility;Office;
Comment=Clipboard OCR to LaTeX assistant
StartupNotify=true
"""


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
    print(f"[linux] Running PyInstaller: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(ROOT))


def verify_build() -> None:
    exe_name = "platex-client"
    exe_path = DIST_DIR / "platex-client" / exe_name
    if not exe_path.exists():
        raise FileNotFoundError(f"Build output missing: {exe_path}")

    for script in ("glm_vision_ocr.py", "hotkey_click.py"):
        script_path = DIST_DIR / "platex-client" / "scripts" / script
        if not script_path.exists():
            script_path = DIST_DIR / "platex-client" / "_internal" / "scripts" / script
        if not script_path.exists():
            raise FileNotFoundError(f"Bundled script missing: {script}")

    print(f"[linux] Verified: {exe_path} exists")
    print("[linux] Verified: bundled scripts found")


def _download(url: str, dest: Path) -> None:
    print(f"[linux] Downloading {url} -> {dest}")
    try:
        subprocess.check_call(["wget", "-q", "-O", str(dest), url])
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    try:
        subprocess.check_call(["curl", "-sL", "-o", str(dest), url])
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    import urllib.request
    urllib.request.urlretrieve(url, str(dest))


def build_appdir() -> None:
    if APPDIR.exists():
        shutil.rmtree(APPDIR)

    src_dist = DIST_DIR / "platex-client"
    if not src_dist.exists():
        raise FileNotFoundError(f"PyInstaller output not found: {src_dist}")

    print(f"[linux] Creating AppDir: {APPDIR}")
    shutil.copytree(src_dist, APPDIR / "usr", symlinks=True)

    bin_dir = APPDIR / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    src_exe = APPDIR / "usr" / "platex-client"
    dst_exe = bin_dir / "platex-client"
    if src_exe.exists() and not dst_exe.exists():
        shutil.copy2(src_exe, dst_exe)
    exe_path = bin_dir / "platex-client"
    exe_path.chmod(exe_path.stat().st_mode | stat.S_IEXEC)

    icon_src = ROOT / "assets" / "platex-client.png"
    if icon_src.exists():
        shutil.copy2(icon_src, APPDIR / "platex-client.png")
        icons_dir = APPDIR / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icons_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, icons_dir / "platex-client.png")

    desktop_path = APPDIR / "platex-client.desktop"
    desktop_path.write_text(DESKTOP_ENTRY, encoding="utf-8")

    apprun_path = APPDIR / "AppRun"
    _download(APPRUN_URL, apprun_path)
    apprun_path.chmod(apprun_path.stat().st_mode | stat.S_IEXEC)

    print(f"[linux] AppDir created: {APPDIR}")


def build_appimage(version: str) -> Path:
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)

    output_name = f"PLatexClient-{version}-x86_64.AppImage"
    output_path = INSTALLER_DIR / output_name

    with tempfile.TemporaryDirectory(prefix="appimagetool-") as tmpdir:
        tool_path = Path(tmpdir) / "appimagetool"
        _download(APPIMAGETOOL_URL, tool_path)
        tool_path.chmod(tool_path.stat().st_mode | stat.S_IEXEC)

        env = os.environ.copy()
        env["ARCH"] = "x86_64"

        cmd = [str(tool_path), str(APPDIR), str(output_path)]
        print(f"[linux] Running appimagetool: {' '.join(cmd)}")
        subprocess.check_call(cmd, cwd=str(ROOT), env=env)

    if not output_path.exists():
        raise FileNotFoundError(f"AppImage not found at {output_path}")

    output_path.chmod(output_path.stat().st_mode | stat.S_IEXEC)
    print(f"[linux] AppImage created: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PLatex Client Linux AppImage")
    parser.add_argument(
        "--skip-pyinstaller", action="store_true",
        help="Skip PyInstaller step (use existing dist/)",
    )
    parser.add_argument(
        "--skip-appimage", action="store_true",
        help="Skip AppImage packaging step",
    )
    parser.add_argument(
        "--version", default=None,
        help="Override version (default: read from pyproject.toml)",
    )
    args = parser.parse_args()

    version = args.version or read_version()
    print(f"[linux] Version: {version}")

    if not args.skip_pyinstaller:
        run_pyinstaller(clean=True)

    verify_build()

    if not args.skip_appimage:
        build_appdir()
        installer_path = build_appimage(version)
        size_mb = installer_path.stat().st_size / (1024 * 1024)
        print(f"[linux] AppImage size: {size_mb:.1f} MB")
        print(f"[linux] Done! AppImage: {installer_path}")
    else:
        print("[linux] Skipped AppImage packaging step")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
