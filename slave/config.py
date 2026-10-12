import json
import os
import sys

# Find the correct root path whether running as a script or a "frozen" .exe
if getattr(sys, 'frozen', False):
    APP_ROOT = os.path.dirname(sys.executable)
else:
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))

config_path = os.path.join(APP_ROOT, 'config.json')

# Load all settings from the external file
try:
    with open(config_path, 'r') as f:
        settings = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"CRITICAL: Configuration file 'config.json' not found next to the executable or script.")
except json.JSONDecodeError:
    raise ValueError(f"CRITICAL: Configuration file 'config.json' is not valid JSON.")

# --- Assign settings to variables ---
PROJECT_ROOT = os.path.dirname(APP_ROOT)
PORTS = settings.get('PORTS', {})
TIMEOUTS = settings.get('TIMEOUTS', {})
FTP = settings.get('FTP', {})
SUSPICIOUS_PROCESSES = settings.get('SUSPICIOUS_PROCESSES', [])
SERVICE_NAME = settings.get('SERVICE_NAME', 'SoftwareDeployerAgent')

# Source 1: Credentials from the config.json file
FTP_CONFIG = settings.get('FTP', {})

# Source 2: Credentials from system environment variables
FTP_ENV = {
    'host': os.getenv('DEPLOYER_FTP_HOST'),
    'user': os.getenv('DEPLOYER_FTP_USER'),
    'pass': os.getenv('DEPLOYER_FTP_PASS'),
    # Copy non-credential settings from the config file for completeness
    'secure': FTP_CONFIG.get('secure', True),
    'remote_dir': FTP_CONFIG.get('remote_dir', '/')
}
MASTER_IP = settings.get('MASTER_IP') or os.getenv('DEPLOYER_MASTER_IP')