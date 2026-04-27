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

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "platex-client.spec"
ISS_FILE = ROOT / "platex-client.iss"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
INSTALLER_DIR = DIST_DIR / "installer"

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

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
    print(f"[build] Running PyInstaller: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(ROOT))


def verify_build() -> None:
    if IS_WINDOWS:
        exe_path = DIST_DIR / "platex-client" / "platex-client.exe"
    else:
        exe_path = DIST_DIR / "platex-client" / "platex-client"

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


def _download(url: str, dest: Path) -> None:
    print(f"[build] Downloading {url} -> {dest}")
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


def build_appdir() -> Path:
    appdir = DIST_DIR / "platex-client.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    src_dist = DIST_DIR / "platex-client"
    if not src_dist.exists():
        raise FileNotFoundError(f"PyInstaller output not found: {src_dist}")

    print(f"[build] Creating AppDir: {appdir}")
    shutil.copytree(src_dist, appdir / "usr", symlinks=True)

    bin_dir = appdir / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    src_exe = appdir / "usr" / "platex-client"
    dst_exe = bin_dir / "platex-client"
    if src_exe.exists() and not dst_exe.exists():
        shutil.copy2(src_exe, dst_exe)
    exe_path = bin_dir / "platex-client"
    exe_path.chmod(exe_path.stat().st_mode | stat.S_IEXEC)

    icon_src = ROOT / "assets" / "platex-client.png"
    if icon_src.exists():
        shutil.copy2(icon_src, appdir / "platex-client.png")
        icons_dir = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icons_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, icons_dir / "platex-client.png")

    desktop_path = appdir / "platex-client.desktop"
    desktop_path.write_text(DESKTOP_ENTRY, encoding="utf-8")

    apprun_path = appdir / "AppRun"
    _download(APPRUN_URL, apprun_path)
    apprun_path.chmod(apprun_path.stat().st_mode | stat.S_IEXEC)

    print(f"[build] AppDir created: {appdir}")
    return appdir


def build_appimage(version: str) -> Path:
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)

    output_name = f"PLatexClient-{version}-x86_64.AppImage"
    output_path = INSTALLER_DIR / output_name

    appdir = build_appdir()

    with tempfile.TemporaryDirectory(prefix="appimagetool-") as tmpdir:
        tool_path = Path(tmpdir) / "appimagetool"
        _download(APPIMAGETOOL_URL, tool_path)
        tool_path.chmod(tool_path.stat().st_mode | stat.S_IEXEC)

        env = os.environ.copy()
        env["ARCH"] = "x86_64"

        cmd = [str(tool_path), str(appdir), str(output_path)]
        print(f"[build] Running appimagetool: {' '.join(cmd)}")
        subprocess.check_call(cmd, cwd=str(ROOT), env=env)

    if not output_path.exists():
        raise FileNotFoundError(f"AppImage not found at {output_path}")

    output_path.chmod(output_path.stat().st_mode | stat.S_IEXEC)
    print(f"[build] AppImage created: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PLatex Client installer")
    parser.add_argument(
        "--skip-pyinstaller", action="store_true",
        help="Skip PyInstaller step (use existing dist/)",
    )
    parser.add_argument(
        "--skip-packaging", action="store_true",
        help="Skip packaging step (Inno Setup or AppImage)",
    )
    parser.add_argument(
        "--version", default=None,
        help="Override version (default: read from pyproject.toml)",
    )
    args = parser.parse_args()

    version = args.version or read_version()
    print(f"[build] Version: {version}")
    print(f"[build] Platform: {sys.platform}")

    if not args.skip_pyinstaller:
        run_pyinstaller(clean=True)

    verify_build()

    if not args.skip_packaging:
        if IS_WINDOWS:
            installer_path = run_inno_setup(version)
            size_mb = installer_path.stat().st_size / (1024 * 1024)
            print(f"[build] Installer size: {size_mb:.1f} MB")
            print(f"[build] Done! Installer: {installer_path}")
        elif IS_LINUX:
            installer_path = build_appimage(version)
            size_mb = installer_path.stat().st_size / (1024 * 1024)
            print(f"[build] AppImage size: {size_mb:.1f} MB")
            print(f"[build] Done! AppImage: {installer_path}")
        else:
            print(f"[build] No packaging supported on platform: {sys.platform}")
    else:
        print("[build] Skipped packaging step")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
