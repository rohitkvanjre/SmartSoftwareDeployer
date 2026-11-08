"""
build_installers.py
====================

One-shot build script that produces the two final, self-contained
installers: installer_build/out/master.exe and installer_build/out/slave.exe.

Steps:
  1. Run PyInstaller for master.spec and slave.spec (onedir builds).
  2. Compile MasterSetup.iss and SlaveSetup.iss with ISCC.

The installers contain no secrets. Slaves pair with the master using a
short-lived code shown in the master app, so any master.exe works with any
slave.exe.

Usage (from repo root):
    python installer_build/build_installers.py
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO_ROOT / "installer_build"
DIST_DIR = BUILD_DIR / "dist"
WORK_DIR = BUILD_DIR / "work"
OUT_DIR = BUILD_DIR / "out"

# Standard Inno Setup 6 locations: a system-wide install, then a per-user one.
ISCC_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
]
ISCC_PATH = next((p for p in ISCC_CANDIDATES if p.exists()), ISCC_CANDIDATES[0])


def run(cmd, **kwargs):
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"Command failed with exit code {result.returncode}: {cmd}")


def main():
    if not ISCC_PATH.exists():
        raise SystemExit(f"Inno Setup compiler not found at {ISCC_PATH}")

    print("=== Step 1/3: Building master.exe payload with PyInstaller ===")
    run([sys.executable, "-m", "PyInstaller", str(BUILD_DIR / "master.spec"),
         "--distpath", str(DIST_DIR), "--workpath", str(WORK_DIR), "--noconfirm"])

    print("\n=== Step 2/3: Building slave.exe payload with PyInstaller ===")
    run([sys.executable, "-m", "PyInstaller", str(BUILD_DIR / "slave.spec"),
         "--distpath", str(DIST_DIR), "--workpath", str(WORK_DIR), "--noconfirm"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== Step 3/3: Compiling installers with Inno Setup ===")
    run([
        str(ISCC_PATH),
        str(BUILD_DIR / "MasterSetup.iss"),
        f"/DSourceDist={DIST_DIR / 'master'}",
        f"/DOutputDir={OUT_DIR}",
    ])
    run([
        str(ISCC_PATH),
        str(BUILD_DIR / "SlaveSetup.iss"),
        f"/DSourceDist={DIST_DIR / 'slave'}",
        f"/DOutputDir={OUT_DIR}",
    ])

    print("\n=== Build complete ===")
    print(f"master.exe -> {OUT_DIR / 'master.exe'}")
    print(f"slave.exe  -> {OUT_DIR / 'slave.exe'}")
    print("\nCopy master.exe to the master PC and slave.exe to each lab PC.")
    print("Pair each slave using the code from the master's 'Pair New Slaves' screen.")


if __name__ == "__main__":
    main()
