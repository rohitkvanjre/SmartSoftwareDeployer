# PyInstaller spec for the Master application.
# Build with: pyinstaller installer_build/master.spec --distpath installer_build/dist --workpath installer_build/work --noconfirm
# Run from the repo root so relative paths below resolve correctly.

import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))

block_cipher = None

datas = [
    (os.path.join(REPO_ROOT, "master", "assets"), "master/assets"),
    (os.path.join(REPO_ROOT, "master", "app.ico"), "master"),
    (os.path.join(REPO_ROOT, "master", "data", "config.json.example"), "master/data"),
    (os.path.join(REPO_ROOT, "master", "data", "catalog.csv"), "master/data"),
    (os.path.join(REPO_ROOT, "master", "auth_manager", "users.json.example"), "master/auth_manager"),
    (os.path.join(REPO_ROOT, "installers"), "installers"),
]

hiddenimports = [
    "PIL._tkinter_finder",
    "sqlite3",
]

a = Analysis(
    [os.path.join(REPO_ROOT, "master", "main.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # matplotlib was removed along with the Dashboard tab (nothing imports it
    # anymore); numpy was only ever a transitive dependency of matplotlib and
    # PIL/cryptography's optional integrations pull it into static analysis
    # even though this app never imports it directly -- excluding both saves
    # ~27MB in the bundled build.
    excludes=["matplotlib", "numpy"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartDeployerMaster",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(REPO_ROOT, "master", "app.ico"),
    # The master's data folder is readable and writable only by
    # Administrators and SYSTEM (see MasterSetup.iss), so the app must run
    # with admin rights. Windows shows a UAC prompt on launch.
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="master",
)
