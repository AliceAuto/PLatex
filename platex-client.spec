# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules

datas = [('scripts/glm_vision_ocr.py', 'scripts'), ('scripts/hotkey_click.py', 'scripts')]
binaries = []
hiddenimports = ['pynput.keyboard', 'pynput.mouse', 'pynput._util', 'platex_client', 'platex_client.app', 'platex_client.cli', 'platex_client.clipboard', 'platex_client.config', 'platex_client.config_manager', 'platex_client.history', 'platex_client.hotkey_listener', 'platex_client.loader', 'platex_client.logging_utils', 'platex_client.models', 'platex_client.script_base', 'platex_client.script_registry', 'platex_client.tray', 'platex_client.watcher', 'platex_client.windows_clipboard']
datas += collect_data_files('PyQt6')
binaries += collect_dynamic_libs('PyQt6')
hiddenimports += collect_submodules('PyQt6')


a = Analysis(
    ['launcher.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='platex-client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\platex-client.ico'],
    contents_directory='.',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='platex-client',
)
