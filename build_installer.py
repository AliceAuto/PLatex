from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd or ROOT)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _find_iscc() -> str:
    import os

    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise FileNotFoundError(
        "ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php"
    )


def _get_version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from platex_client import __version__

    return __version__


def build_pyinstaller() -> None:
    _run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "platex-client.spec"]
    )


def build_windows_installer(version: str) -> None:
    iscc = _find_iscc()
    _run([iscc, f"/DMyAppVersion={version}", "platex-client.iss"])


def build_linux_appimage(version: str) -> None:
    _run(
        [sys.executable, "build_linux.py", "--skip-pyinstaller", "--version", version]
    )


def verify() -> None:
    errors: list[str] = []

    if IS_WINDOWS:
        exe = ROOT / "dist" / "platex-client" / "platex-client.exe"
    else:
        exe = ROOT / "dist" / "platex-client" / "platex-client"

    if not exe.is_file():
        errors.append(f"Missing: {exe}")

    for script in ("glm_vision_ocr.py", "hotkey_click.py"):
        found = False
        for base in (ROOT / "dist" / "platex-client", ROOT / "dist" / "platex-client" / "_internal"):
            candidate = base / "scripts" / script
            if candidate.is_file():
                found = True
                break
        if not found:
            errors.append(f"Missing bundled script: {script}")

    if IS_WINDOWS:
        installers = list((ROOT / "dist" / "installer").glob("PLatexClient-*-win64-setup.exe"))
        if not installers:
            errors.append("No Windows installer found in dist/installer/")
    elif IS_LINUX:
        installers = list((ROOT / "dist" / "installer").glob("PLatexClient-*-x86_64.AppImage"))
        if not installers:
            errors.append("No Linux AppImage found in dist/installer/")

    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        raise SystemExit(1)

    print("OK: All verifications passed")
    if IS_WINDOWS:
        for inst in (ROOT / "dist" / "installer").glob("PLatexClient-*-win64-setup.exe"):
            size_mb = round(inst.stat().st_size / 1024 / 1024, 2)
            print(f"  Installer: {inst.name} ({size_mb} MB)")
    elif IS_LINUX:
        for inst in (ROOT / "dist" / "installer").glob("PLatexClient-*-x86_64.AppImage"):
            size_mb = round(inst.stat().st_size / 1024 / 1024, 2)
            print(f"  AppImage: {inst.name} ({size_mb} MB)")


def main() -> None:
    version = _get_version()
    print(f"Building PLatex Client v{version}")

    build_pyinstaller()

    if IS_WINDOWS:
        build_windows_installer(version)
    elif IS_LINUX:
        build_linux_appimage(version)

    verify()

    print(f"\nBuild complete! Output is in dist/installer/")


if __name__ == "__main__":
    main()
