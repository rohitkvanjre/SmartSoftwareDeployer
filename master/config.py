import json
import os
import sys

# This logic finds the correct base path whether running as a script or a compiled .exe
if getattr(sys, 'frozen', False):
    # A frozen build is installed under Program Files, which a standard
    # (non-admin) launch of the app cannot write to at runtime. All mutable
    # data (config.json, TLS certs, the database, the catalog, the installers
    # folder, logs) instead lives under %ProgramData%, the standard Windows
    # location for machine-wide app data - the installer creates this folder
    # and grants standard users write access to it (see MasterSetup.iss).
    base_path = os.path.join(
        os.environ.get('ProgramData', os.path.dirname(sys.executable)),
        'SmartSoftwareDeployer', 'Master'
    )
else:
    # We are running as a normal script
    base_path = os.path.dirname(os.path.abspath(__file__))

# MASTER_DIR must match base_path exactly (both point at the directory that
# actually holds data/cert.pem etc.)
MASTER_DIR = base_path

# In master/config.py
config_path = os.path.join(base_path, 'data', 'config.json') # <-- Look inside the 'data' folder
# Load all settings from the external file
try:
    with open(config_path, 'r') as f:
        settings = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"CRITICAL: Configuration file 'config.json' not found next to the executable or script.")
except json.JSONDecodeError:
    raise ValueError(f"CRITICAL: Configuration file 'config.json' is not valid JSON.")

# --- Assign settings to variables ---
PROJECT_ROOT = os.path.dirname(base_path)
PORTS = settings.get('PORTS', {})
# Always an absolute path resolved against MASTER_DIR (the one writable data
# root), so it stays correct whether frozen or running from source.
CATALOG = {"path": os.path.join(MASTER_DIR, "data", "catalog.csv")}

# Where the "installers" folder (deployable .exe/.msi/.zip files an admin
# drops in via the catalog editor) lives. Frozen: inside the same writable
# ProgramData root as everything else. Dev/source: unchanged, a sibling of
# the master/ package (i.e. the repo root), matching this repo's existing
# layout.
if getattr(sys, 'frozen', False):
    INSTALLERS_DIR = os.path.join(MASTER_DIR, "installers")
else:
    INSTALLERS_DIR = os.path.join(os.path.dirname(MASTER_DIR), "installers")
TLS = settings.get('TLS', {})
RETRY = settings.get('RETRY', {})
SCHEDULER = settings.get('SCHEDULER', {})
POLICIES = settings.get('POLICIES', {})
AUTO_UPDATE = {} # Kept for compatibility
FTP = settings.get('FTP', {})
HEALTH = settings.get('HEALTH', {})
FTP_CONFIG = settings.get('FTP', {})

# --- For security, prioritize environment variables for secrets ---
# This allows overriding the JSON file with more secure environment variables.
shared_token = os.getenv('DEPLOYER_SHARED_TOKEN')
if not shared_token:
    raise Exception("FATAL: DEPLOYER_SHARED_TOKEN environment variable is not set!")

FTP_ENV = {
    "host": os.getenv('DEPLOYER_FTP_HOST'),
    "user": os.getenv('DEPLOYER_FTP_USER'),
    "pass": os.getenv('DEPLOYER_FTP_PASS'),
    # Copy non-credential settings from the primary config for completeness
    "enabled": FTP_CONFIG.get('enabled', False),
    "secure": FTP_CONFIG.get('secure', False),
    "threshold": FTP_CONFIG.get('threshold', 0),
    "remote_dir": FTP_CONFIG.get('remote_dir', '/'),
    "is_local_path": FTP_CONFIG.get('is_local_path', False)
}