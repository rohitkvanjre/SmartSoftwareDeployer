# PyInstaller spec for BOTH slave executables (the Windows Service agent and
# the tray-icon status app), combined into ONE spec file so a single COLLECT
# call places them side by side in the same output folder.
# (Two separate spec files can't safely share one COLLECT output directory --
# each run's COLLECT step wipes and rebuilds its target from scratch, so a
# second spec run would delete the first exe's output.)
#
# Build with: pyinstaller installer_build/slave.spec --distpath installer_build/dist --workpath installer_build/work --noconfirm

import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))

block_cipher = None

# ---------------------------------------------------------------------------
# Executable 1: SoftwareDeployerAgent.exe (the Windows Service)
# ---------------------------------------------------------------------------

service_hiddenimports = [
    "win32timezone",
    "win32api",
    "win32con",
    "win32event",
    "win32service",
    "win32serviceutil",
    "servicemanager",
    "pythoncom",
    "pywintypes",
    "psutil",
    "packaging.version",
    "PIL._tkinter_finder",
]

service_analysis = Analysis(
    [os.path.join(REPO_ROOT, "slave", "service.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=service_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

service_pyz = PYZ(service_analysis.pure, service_analysis.zipped_data, cipher=block_cipher)

service_exe = EXE(
    service_pyz,
    service_analysis.scripts,
    [],
    exclude_binaries=True,
    name="SoftwareDeployerAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

# ---------------------------------------------------------------------------
# Executable 2: tray_app.exe (the tray-icon status app)
# ---------------------------------------------------------------------------

tray_hiddenimports = [
    "pystray._win32",
    "PIL._tkinter_finder",
]

tray_analysis = Analysis(
    [os.path.join(REPO_ROOT, "slave", "tray_app.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=tray_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

tray_pyz = PYZ(tray_analysis.pure, tray_analysis.zipped_data, cipher=block_cipher)

tray_exe = EXE(
    tray_pyz,
    tray_analysis.scripts,
    [],
    exclude_binaries=True,
    name="tray_app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

# ---------------------------------------------------------------------------
# Single COLLECT: both executables land side by side in dist/slave/
# ---------------------------------------------------------------------------

coll = COLLECT(
    service_exe,
    service_analysis.binaries,
    service_analysis.zipfiles,
    service_analysis.datas,
    tray_exe,
    tray_analysis.binaries,
    tray_analysis.zipfiles,
    tray_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="slave",
)
