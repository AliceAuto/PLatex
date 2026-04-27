# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

datas = [
    ('scripts/glm_vision_ocr.py', 'scripts'),
    ('scripts/hotkey_click.py', 'scripts'),
    ('src/platex_client/locales', 'platex_client/locales'),
    ('assets', 'assets'),
]
binaries = []
hiddenimports = []

hiddenimports += collect_submodules('pynput')
hiddenimports += collect_submodules('platex_client')

_pyqt6_needed = [
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
]
for mod in _pyqt6_needed:
    hiddenimports += collect_submodules(mod)

datas += collect_data_files('PyQt6.QtCore')
datas += collect_data_files('PyQt6.QtGui')
datas += collect_data_files('PyQt6.QtWidgets')
binaries += collect_dynamic_libs('PyQt6.QtCore')
binaries += collect_dynamic_libs('PyQt6.QtGui')
binaries += collect_dynamic_libs('PyQt6.QtWidgets')

if IS_LINUX:
    try:
        hiddenimports += collect_submodules('PyQt6.QtDBus')
        datas += collect_data_files('PyQt6.QtDBus')
        binaries += collect_dynamic_libs('PyQt6.QtDBus')
    except Exception:
        pass

excludes = [
    'tkinter',
    'unittest',
    'test',
    'tests',
    'setuptools',
    'pip',
    'wheel',
    'distutils',
    'lib2to3',
    'xmlrpc',
    'pydoc',
    'doctest',
    'ftplib',
    'smtplib',
    'telnetlib',
    'nntplib',
    'imaplib',
    'poplib',
    'webbrowser',
    'http.server',
    'http.cookiejar',
    'xml.dom',
    'xml.sax',
    'xml.etree',
    'curses',
    'pty',
    'resource',
    'PyQt6.Qt3DAnimation',
    'PyQt6.Qt3DCore',
    'PyQt6.Qt3DExtras',
    'PyQt6.Qt3DInput',
    'PyQt6.Qt3DLogic',
    'PyQt6.Qt3DRender',
    'PyQt6.QtBluetooth',
    'PyQt6.QtCharts',
    'PyQt6.QtDataVisualization',
    'PyQt6.QtDesigner',
    'PyQt6.QtGraphs',
    'PyQt6.QtHelp',
    'PyQt6.QtLocation',
    'PyQt6.QtMultimedia',
    'PyQt6.QtMultimediaWidgets',
    'PyQt6.QtNetwork',
    'PyQt6.QtNfc',
    'PyQt6.QtOpenGL',
    'PyQt6.QtOpenGLWidgets',
    'PyQt6.QtPdf',
    'PyQt6.QtPdfWidgets',
    'PyQt6.QtPositioning',
    'PyQt6.QtPrintSupport',
    'PyQt6.QtQml',
    'PyQt6.QtQuick',
    'PyQt6.QtQuick3D',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtRemoteObjects',
    'PyQt6.QtSensors',
    'PyQt6.QtSerialPort',
    'PyQt6.QtSpatialAudio',
    'PyQt6.QtSql',
    'PyQt6.QtStateMachine',
    'PyQt6.QtSvg',
    'PyQt6.QtSvgWidgets',
    'PyQt6.QtTest',
    'PyQt6.QtTextToSpeech',
    'PyQt6.QtWebChannel',
    'PyQt6.QtWebEngine',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebEngineQuick',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebSockets',
    'PyQt6.QtXml',
]

a = Analysis(
    ['launcher.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if IS_WINDOWS:
    icon_path = str(Path('assets') / 'platex-client.ico')
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
        icon=[icon_path],
        contents_directory='.',
    )
elif IS_LINUX:
    icon_path = str(Path('assets') / 'platex-client.png')
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
        icon=[icon_path],
    )
else:
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
