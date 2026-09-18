"""
build_installers.py
====================

One-shot build script that produces the two final, self-contained
installers: installer_build/out/master.exe and installer_build/out/slave.exe.

Steps:
  1. Run PyInstaller for master.spec and slave.spec (onedir builds).
  2. Generate ONE random shared token.
  3. Compile MasterSetup.iss and SlaveSetup.iss with ISCC, passing that same
     token to both via a preprocessor define -- so the two installers work
     together with zero manual configuration when run on separate machines.

Usage (from repo root):
    python installer_build/build_installers.py
"""

import secrets
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO_ROOT / "installer_build"
DIST_DIR = BUILD_DIR / "dist"
WORK_DIR = BUILD_DIR / "work"
OUT_DIR = BUILD_DIR / "out"

ISCC_PATH = Path(r"C:\Users\vanjr\AppData\Local\Programs\Inno Setup 6\ISCC.exe")


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

    shared_token = secrets.token_urlsafe(32)
    print(f"\n=== Generated a fresh shared token for this build pair ===")
    print("(This token is baked into both installers below and is not stored anywhere else.)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== Step 3/3: Compiling installers with Inno Setup ===")
    run([
        str(ISCC_PATH),
        str(BUILD_DIR / "MasterSetup.iss"),
        f"/DSharedToken={shared_token}",
        f"/DSourceDist={DIST_DIR / 'master'}",
        f"/DOutputDir={OUT_DIR}",
    ])
    run([
        str(ISCC_PATH),
        str(BUILD_DIR / "SlaveSetup.iss"),
        f"/DSharedToken={shared_token}",
        f"/DSourceDist={DIST_DIR / 'slave'}",
        f"/DOutputDir={OUT_DIR}",
    ])

    print("\n=== Build complete ===")
    print(f"master.exe -> {OUT_DIR / 'master.exe'}")
    print(f"slave.exe  -> {OUT_DIR / 'slave.exe'}")
    print("\nThese two files are fully self-contained: copy master.exe to the")
    print("master PC and slave.exe to each lab PC. No manual configuration,")
    print("shared tokens, or project files need to be shared alongside them.")


if __name__ == "__main__":
    main()
