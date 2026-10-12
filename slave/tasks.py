"""Module: tasks
This module contains the core operational logic for the slave client.
"""

import os
import subprocess
import json
import platform
import socket
import tempfile
import shutil
import psutil
import shlex
import logging
import hashlib
from . import config
from pathlib import Path
from .config import PORTS, TIMEOUTS
from . import pairing
from datetime import datetime
from . import config
from ftplib import FTP_TLS, FTP as FTP_Client, error_perm
import sys
import time  
import re
from PIL import ImageGrab
import io
import base64
import zipfile
import glob
import ntpath
import stat

BUF = 4096
# DOWNLOADS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
DOWNLOADS_PATH = os.path.join(os.environ.get("ProgramData"), "SoftwareDeployerAgent", "downloads")
# Add this function near the top of slave/tasks.py

def extract_zip_and_create_shortcut(zip_path, filename, send_status_callback):
    """
    Extracts a ZIP file, intelligently searches for the main executable
    (handling single nested folders), and creates a desktop shortcut.
    Sends status updates back to the master via the provided callback.
    """
    base_name = os.path.splitext(filename)[0] # Name without .zip
    # --- Define Extraction Target ---
    extract_destination = f"C:\\{base_name}"
    shortcut_name = f"{base_name}.lnk"
    target_exe_path = None # Will try to find this automatically
    search_directory = extract_destination # Default directory to search for the exe
    working_dir_path = extract_destination # Default working dir
    # --- End Configuration ---

    try:
        logging.info(f"Starting generic extraction of '{filename}' to '{extract_destination}'")
        send_status_callback({"status": "Extracting", "message": f"Extracting {filename}..."})

        # 1. Remove existing directory (Robust removal)
        if os.path.exists(extract_destination):
            logging.info(f"Removing existing directory: {extract_destination}")
            attempts = 3
            while attempts > 0 and os.path.exists(extract_destination):
                try:
                    shutil.rmtree(extract_destination, ignore_errors=False) # Try without ignore_errors first
                except Exception:
                    time.sleep(1) # Wait if immediate removal fails
                    shutil.rmtree(extract_destination, ignore_errors=True) # Force if needed
                time.sleep(2)
                attempts -= 1
            if os.path.exists(extract_destination):
                 logging.error(f"Failed to fully remove existing directory: {extract_destination}")
                 # You might want to stop here if removal fails, depending on desired behavior
                 # send_status_callback({"status": "Extraction Failed", "message": "Could not remove old directory."})
                 # return

        # 2. Validate and extract each member inside the destination only.
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            extraction_root = os.path.realpath(extract_destination)
            for member in zip_ref.infolist():
                member_name = member.filename.replace('\\', '/')
                member_path = os.path.realpath(os.path.join(extraction_root, member_name))
                if ntpath.splitdrive(member_name)[0] or os.path.isabs(member_name):
                    raise ValueError(f"Unsafe archive path: {member.filename}")
                if os.path.commonpath((extraction_root, member_path)) != extraction_root:
                    raise ValueError(f"Unsafe archive path: {member.filename}")
                unix_mode = (member.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(unix_mode):
                    raise ValueError(f"Symbolic links are not allowed in archives: {member.filename}")
                zip_ref.extract(member, extract_destination)
        logging.info(f"Extraction successful to {extract_destination}")
        send_status_callback({"status": "Extraction Complete", "message": f"Extracted {filename}."})

        # --- Wait briefly for filesystem ---
        time.sleep(3)

        # 3. --- INTELLIGENTLY DETERMINE SEARCH DIRECTORY ---
        logging.info(f"Analyzing extracted content in '{extract_destination}'...")
        try:
            extracted_items = os.listdir(extract_destination)
            # --- NEW LOGIC: Check for single nested folder ---
            if len(extracted_items) == 1:
                single_item_path = os.path.join(extract_destination, extracted_items[0])
                if os.path.isdir(single_item_path):
                    # Found a single nested folder, update search directory to look inside it
                    search_directory = single_item_path
                    logging.info(f"Found single nested folder. Searching for executable inside: '{search_directory}'")
                else:
                    # Single item is a file, search in the root
                    logging.info("Found single item (file). Searching in extraction root.")
            # --- END NEW LOGIC ---
            elif len(extracted_items) > 1:
                logging.info(f"Found multiple items ({len(extracted_items)}) in extraction root. Searching for executable in root: '{search_directory}'")
                # Optional: Add specific message for multiple folders if desired
                # if all(os.path.isdir(os.path.join(extract_destination, item)) for item in extracted_items):
                #     send_status_callback({"status": "Extraction Complete", "message": f"Extracted {filename}. Found multiple folders, cannot determine primary."})
                #     # Maybe skip shortcut creation here if too ambiguous?
                #     # return
            else: # Empty extraction?
                 logging.warning("Extraction resulted in an empty directory.")
                 send_status_callback({"status": "Shortcut Skipped", "message": "Extraction was empty."})
                 return
        except Exception as e:
            logging.error(f"Error analyzing extracted content: {e}")
            # Fallback to searching the root anyway
            search_directory = extract_destination

        # --- Automatically Find Executable within search_directory ---
        logging.info(f"Searching for executable in '{search_directory}'...")
        possible_exes = glob.glob(os.path.join(search_directory, "*.exe"))

        if not possible_exes:
            logging.warning(f"No .exe found in determined search directory '{search_directory}'. Cannot create shortcut.")
            send_status_callback({"status": "Shortcut Skipped", "message": f"No executable found for {base_name}."})
            return

        elif len(possible_exes) == 1:
            target_exe_path = possible_exes[0]
            logging.info(f"Found single executable: {target_exe_path}")
        else: # Multiple exes
            logging.info(f"Multiple executables found in '{search_directory}': {possible_exes}. Attempting to guess main executable...")
            # Guess 1: Exe name matches zip base name
            guessed_exe_zip = os.path.join(search_directory, f"{base_name}.exe")
            # Guess 2: Exe name matches the immediate parent folder name (if we searched nested)
            parent_folder_name = os.path.basename(search_directory)
            guessed_exe_folder = os.path.join(search_directory, f"{parent_folder_name}.exe")

            if guessed_exe_zip in possible_exes:
                target_exe_path = guessed_exe_zip
                logging.info(f"Guessed main executable based on ZIP name: {target_exe_path}")
            elif guessed_exe_folder in possible_exes:
                 target_exe_path = guessed_exe_folder
                 logging.info(f"Guessed main executable based on folder name: {target_exe_path}")
            else:
                 # Fallback: Pick the first one found
                 target_exe_path = possible_exes[0]
                 logging.warning(f"Could not reliably guess main executable. Using first found: {target_exe_path}")

        # Set working directory to the folder containing the found exe
        working_dir_path = os.path.dirname(target_exe_path)
        # --- End Find Executable ---

        # 4. Create Shortcut (Only if an executable was found)
        if target_exe_path and platform.system() == "Windows":
            # ... (Shortcut creation logic remains the same as previous version) ...
            public_desktop = os.path.join(os.environ.get('PUBLIC', 'C:\\Users\\Public'), 'Desktop')
            shortcut_full_path = os.path.join(public_desktop, shortcut_name)

            logging.info(f"Attempting shortcut creation:")
            logging.info(f"  Shortcut Path (.lnk): {shortcut_full_path}")
            logging.info(f"  Target Executable: {target_exe_path}")
            logging.info(f"  Working Directory: {working_dir_path}")

            ps_target_exe = target_exe_path.replace("'", "''")
            ps_working_dir = working_dir_path.replace("'", "''")
            ps_shortcut_path = shortcut_full_path.replace("'", "''")

            ps_command = (
                f"$Shell = New-Object -ComObject WScript.Shell; "
                f"$Shortcut = $Shell.CreateShortcut('{ps_shortcut_path}'); "
                f"$Shortcut.TargetPath = '{ps_target_exe}'; "
                f"$Shortcut.WorkingDirectory = '{ps_working_dir}'; "
                f"$Shortcut.Save()"
            )

            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                                    capture_output=True, text=True, check=False,
                                    creationflags=subprocess.CREATE_NO_WINDOW)

            if result.returncode == 0:
                logging.info(f"Shortcut created successfully: {shortcut_full_path}")
                send_status_callback({"status": "Shortcut Created", "message": f"Created desktop shortcut for {base_name}."})
            else:
                logging.error(f"Failed to create shortcut. PowerShell Error: {result.stderr or result.stdout}")
                send_status_callback({"status": "Shortcut Failed", "message": f"Failed to create shortcut: {result.stderr or result.stdout}"})
        elif target_exe_path: # Exe found but not Windows
             logging.warning("Shortcut creation only supported on Windows.")

    # ... (keep existing except blocks for zipfile, PermissionError, Exception) ...
    except Exception as e:
        error_msg = f"Auto-extract/shortcut failed for '{filename}': {e}"
        logging.error(error_msg, exc_info=True)
        send_status_callback({"status": "Extraction Failed", "message": f"Unexpected error: {e}"})

def get_active_user_session():
    # ... (function definition as provided before) ...
    query_cmd = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "query.exe")
    if not os.path.exists(query_cmd):
        logging.error(f"Cannot find '{query_cmd}'. Cannot target specific user session.")
        return None
    try:
        result = subprocess.run([query_cmd, "user"],capture_output=True,text=True,check=True,encoding="utf-8",creationflags=subprocess.CREATE_NO_WINDOW)
        for line in result.stdout.strip().split('\n'):
            if "Active" in line:
                parts = line.split()
                session_id_str = parts[1]
                numeric_id = re.search(r'\d+', session_id_str)
                if numeric_id:
                    session_id = int(numeric_id.group(0))
                    logging.info(f"Found active user session: {session_id}")
                    return session_id
    except Exception as e:
        logging.error(f"Error running '{query_cmd} user': {e}")
        return None
    logging.warning("No active user session found via query.exe.")
    return None
# --- End of get_active_user_session ---

# Add this new function:
def display_broadcast_message(message_text):
    """Uses msg.exe to display a message popup to logged-in users."""
    try:
        # Try to find the specific active user session
        session_id = get_active_user_session() #

        if session_id is not None:
            # Target the specific active session ID
            cmd = ["msg", str(session_id), message_text]
            logging.info(f"Displaying message to session {session_id}: '{message_text}'")
        else:
            # Fallback: Send to all (*) sessions if active one couldn't be found
            cmd = ["msg", "*", message_text]
            logging.info(f"Displaying message to all sessions: '{message_text}'")

        # Execute msg.exe command, hiding its own console window
        result = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)

        if result.returncode == 0:
            logging.info("Message display command executed successfully.")
        else:
            # Log failure details if msg.exe returned an error
            logging.error(f"msg.exe failed. Return code: {result.returncode}. Output: {result.stderr or result.stdout}")

    except FileNotFoundError:
         # This happens if msg.exe isn't available (less common on modern Windows)
         logging.error("msg.exe command not found. Cannot display broadcast message.")
    except Exception as e:
        # Catch any other unexpected errors during the process
        logging.error(f"An unexpected error occurred displaying message: {e}", exc_info=True)

def take_screenshot_and_encode():
    """Takes a screenshot, saves it to memory, and returns it as a Base64
    encoded string.

    Only actually works when called from a process with desktop access.
    The Windows Service itself runs as LocalSystem in Session 0, which has
    NO desktop at all (Session 0 Isolation) -- ImageGrab.grab() there always
    fails. take_screenshot_via_tray_relay() below is what the service
    actually uses; this function is kept for the tray app (tray_app.py),
    which DOES run in the interactive user's own session and calls this
    directly to fulfill a relay request.
    """
    try:
        logging.info("Taking screenshot...")
        # Grab the primary screen
        screenshot = ImageGrab.grab()

        # Save the image to an in-memory buffer
        buffer = io.BytesIO()
        # Save as JPEG for smaller size, adjust quality as needed
        screenshot.save(buffer, format="JPEG", quality=75)
        buffer.seek(0)

        # Encode the image bytes as Base64
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        logging.info(f"Screenshot captured and encoded (length: {len(img_base64)}).")
        return img_base64
    except Exception as e:
        logging.error(f"Failed to take or encode screenshot: {e}", exc_info=True)
        return None


def take_screenshot_via_tray_relay(timeout=10):
    """Requests a screenshot from the interactive-session tray app and waits
    for the result, since the service process itself has no desktop to
    capture from (see take_screenshot_and_encode's docstring). Returns the
    same Base64-JPEG-string shape take_screenshot_and_encode does, or None
    on timeout/failure (e.g. no user is currently logged on to run a tray
    app at all)."""
    ipc_dir = os.path.join(os.environ.get("ProgramData"), "SoftwareDeployerAgent", "ipc")
    os.makedirs(ipc_dir, exist_ok=True)
    request_path = os.path.join(ipc_dir, "screenshot_request.flag")
    result_path = os.path.join(ipc_dir, "screenshot_result.jpg")

    # Clear out any stale result left over from an earlier request so we
    # never accidentally pick up old image data.
    try:
        os.remove(result_path)
    except FileNotFoundError:
        pass

    with open(request_path, "w") as f:
        f.write(str(time.time()))

    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(result_path):
            time.sleep(0.2)  # give the tray app's write a moment to finish
            try:
                with open(result_path, "rb") as f:
                    data = f.read()
                os.remove(result_path)
                return base64.b64encode(data).decode('utf-8')
            except Exception as e:
                logging.error(f"Failed to read screenshot result from tray app: {e}")
                return None
        time.sleep(0.3)

    logging.error("Timed out waiting for the tray app to capture a screenshot "
                  "(is a user currently logged on to this machine?).")
    return None
    
def get_active_user_session():
    """
    Finds the active user session by calling query.exe with its full path.
    This is the most reliable method if the command exists on the system.
    """
    # Use the full, absolute path to the command to bypass PATH issues.
    query_cmd = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "query.exe")

    if not os.path.exists(query_cmd):
        logging.error(f"Cannot find '{query_cmd}'. This feature may not be available on this version of Windows (e.g., Home Edition).")
        return None
        
    try:
        # Run the Windows 'query user' command using the full path
        result = subprocess.run(
            [query_cmd, "user"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW # Hide the command window
        )
        
        # Loop through each line of the output
        for line in result.stdout.strip().split('\n'):
            # Look for the line containing the "Active" user
            if "Active" in line:
                parts = line.split()
                session_id_str = parts[1]
                numeric_id = re.search(r'\d+', session_id_str)
                if numeric_id:
                    session_id = int(numeric_id.group(0))
                    logging.info(f"Found active user session: {session_id}")
                    return session_id
                    
    except Exception as e:
        logging.error(f"Error running '{query_cmd} user': {e}")
        return None

    # If no 'Active' user was found
    logging.warning("No active user session found via query.exe.")
    return None

def _run_process_cleanup(process_list_json_str, task_name="cleanup"):
    """
    Safely parses a JSON list of process names and attempts to terminate them.
    """
    if not process_list_json_str:
        return  # Nothing to do

    try:
        process_names = json.loads(process_list_json_str)
        if not isinstance(process_names, list):
            logging.warning(f"{task_name}: Invalid kill list format (not a JSON list).")
            return

        logging.info(f"{task_name}: Terminating {len(process_names)} process(es)...")
        for proc in process_names:
            try:
                # Use taskkill for robust termination of the process and its children
                cmd = ["taskkill", "/F", "/IM", proc, "/T"]
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logging.info(f"{task_name}: Sent terminate command for '{proc}'")
            except Exception as e_inner:
                logging.warning(f"{task_name}: Failed to run taskkill for '{proc}': {e_inner}")

    except json.JSONDecodeError:
        logging.error(f"{task_name}: Failed to parse process kill list (bad JSON): {process_list_json_str}")
    except Exception as e:
        logging.error(f"{task_name}: Error during process cleanup: {e}")

def sha256_file(filepath):
    """Calculates the SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def _attempt_ftp_download(filename, ftp_settings, progress_cb=None):
    """A helper function that performs a single FTP download attempt."""
    host = ftp_settings.get('host')
    user = ftp_settings.get('user')
    password = ftp_settings.get('pass')

    # If credentials for this source are not set, don't even try.
    if not all([host, user]):
        logging.info(f"FTP settings are incomplete for this source. Skipping attempt.")
        return None, "Incomplete credentials"

    logging.info(f"FTP: Attempting download of {filename} from {host}...")
    cache_path = os.path.join(DOWNLOADS_PATH, os.path.basename(filename))
    os.makedirs(DOWNLOADS_PATH, exist_ok=True)
    remote_path = os.path.join(ftp_settings.get("remote_dir", "/"), filename)

    try:
        use_secure = ftp_settings.get("secure", True)
        ftp_client = FTP_TLS(host) if use_secure else FTP_Client(host)

        with ftp_client as ftp:
            ftp.login(user, password)
            if use_secure:
                ftp.prot_p()

            total_size = ftp.size(remote_path)
            bytes_received = 0
            with open(cache_path, "wb") as f:
                def write_chunk(chunk):
                    nonlocal bytes_received
                    f.write(chunk)
                    bytes_received += len(chunk)
                    if progress_cb:
                        progress_cb(int(bytes_received * 100 / total_size))
                ftp.retrbinary(f"RETR {remote_path}", write_chunk)

        if os.path.getsize(cache_path) == total_size:
            logging.info(f"FTP: Download to cache complete: {cache_path}")
            return cache_path, "Success"
        else:
            if os.path.exists(cache_path): os.remove(cache_path)
            return None, "Incomplete download"
            
    except error_perm as e:
        # Re-raise the login error so the main function can catch it and trigger the fallback
        logging.warning(f"FTP: Login failed for user '{user}' on host '{host}'. Error: {e}")
        raise
    except Exception as e:
        logging.error(f"FTP: Download failed with an unexpected error: {e}", exc_info=True)
        return None, str(e)

def download_from_ftp(filename, progress_cb=None):
    """
    Downloads a file from FTP with a robust fallback mechanism.
    Correctly retries if the first source has incomplete credentials OR a login failure.
    """
    should_fallback = False
    
    # --- Attempt 1: Using credentials from config.json ---
    logging.info("FTP Download: Trying credentials from config.json...")
    try:
        path, msg = _attempt_ftp_download(filename, config.FTP_CONFIG, progress_cb)
        if path:
            return path  # Success on the first try!

        # Check if the failure was due to bad config, which warrants a retry
        if msg == "Incomplete credentials":
            should_fallback = True
            logging.warning("FTP (config.json) failed: Incomplete credentials.")
        else:
            # A different failure (e.g., file not found), so we do NOT retry
            logging.error(f"FTP download failed with config.json credentials: {msg}")
            return None

    except error_perm:
        # A login failure also warrants a retry
        should_fallback = True
        logging.warning("FTP (config.json) failed: Login incorrect.")
    except Exception as e:
        # A critical, unexpected error on the first attempt
        logging.error(f"FTP (config.json) failed with an unexpected error: {e}")
        return None

    # --- Fallback Attempt ---
    if should_fallback:
        logging.info("Falling back to environment variables for FTP credentials...")
        try:
            path, msg = _attempt_ftp_download(filename, config.FTP_ENV, progress_cb)
            if path:
                return path  # Success on fallback!

            # If we're here, the fallback also failed.
            logging.error(f"FTP (environment variables) also failed: {msg}")
            return None
        except Exception as e:
            logging.error(f"FTP fallback attempt failed critically: {e}")
            return None
            
    return None

def _powershell(cmd):
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]

def has_enough_disk(bytes_required: int) -> bool:
    try:
        _, _, free = shutil.disk_usage(os.getcwd())
        return free >= bytes_required
    except Exception:
        return True # Fail open if we can't check

def download_from_master(master_ip, filename, progress_cb=None):
    """Downloads a file to the local cache using a secure SSL connection if enabled."""
    logging.info(f"Initiating download of {filename} to local cache...")
    cache_path = os.path.join(DOWNLOADS_PATH, os.path.basename(filename))
    os.makedirs(DOWNLOADS_PATH, exist_ok=True)

    try:
        creds = pairing.load_credentials()
        if not creds:
            logging.error("Cannot download from the master: this PC is not paired.")
            return None
        sock, _ = pairing.connect_to_master(master_ip, PORTS["files"], creds["master_fingerprint"])

        with sock:
            request = json.dumps({"filename": filename, "hostname": socket.gethostname(),
                                  "auth": creds["token"]}).encode('utf-8') + b'\n'
            sock.sendall(request)
            
            buffer = b""
            while b'\n' not in buffer:
                chunk = sock.recv(1024)
                if not chunk: raise ConnectionError("Master did not send file header.")
                buffer += chunk
            
            header_str, buffer = buffer.split(b'\n', 1)
            meta = json.loads(header_str.decode('utf-8'))
            total_size = meta.get("size", 0)

            bytes_received = 0
            with open(cache_path, "wb") as f:
                f.write(buffer)
                bytes_received += len(buffer)
                while bytes_received < total_size:
                    chunk = sock.recv(4096)
                    if not chunk: break
                    f.write(chunk)
                    bytes_received += len(chunk)
                    if progress_cb:
                        progress_cb(int(bytes_received * 100 / total_size))

        if bytes_received == total_size:
            logging.info(f"Download to cache complete: {cache_path}")
            return cache_path
        else:
            logging.error(f"Download of {filename} incomplete.")
            return None
    except Exception as e:
        logging.error(f"Download failed: {e}", exc_info=True)
        return None
    
# In slave/tasks.py
# Make sure these are imported at the top of the file
import os
import shlex
import time
import uuid
import psutil
import logging
import subprocess
from . import config

TIMEOUTS = {
    'exe': 1800,
    'msi': 600,
    'script': 900,
}


def _find_active_desktop_user():
    """Return username of the active desktop user (explorer.exe owner) or None."""
    try:
        logged_in_users = {u.name for u in psutil.users()}
        for p in psutil.process_iter(['name', 'username']):
            if p.info['name'] and p.info['name'].lower() == 'explorer.exe':
                if p.info['username'] in logged_in_users:
                    return p.info['username']
    except Exception as e:
        logging.error(f"Error finding active desktop user: {e}", exc_info=True)
    return None


def _poll_task(task_name, timeout=600):
    """Poll a scheduled task until it finishes running or timeout is reached."""
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"],
            capture_output=True, text=True
        )
        output = result.stdout

        if "Running" in output:
            time.sleep(5)
            continue  # still running
        elif "Ready" in output or "Could not find" in output:
            return True, "Task completed."
        else:
            time.sleep(5)

    return False, f"Task '{task_name}' timed out after {timeout} seconds."


TIMEOUTS = {
    'exe': 1800,
    'msi': 600,
    'script': 900,
}

# Known installer-building frameworks, detected by a byte signature they
# embed in the compiled .exe, mapped to that framework's well-known standard
# silent-install flags. This lets most installers be deployed silently
# without ever needing a manual "silent_flags" catalog entry -- only exotic/
# custom installers that don't match any of these need one, as a fallback.
#
# Signatures are checked in order; the first match wins. Each is a
# pre-tokenized argv list (NOT a shell string) because some conventions
# (InstallShield's /v"/qn") rely on literal quote characters being passed
# through to the child process as-is -- shlex.split() would strip them,
# since shlex's quoting rules are for shell-style strings, not this.
INSTALLER_SIGNATURES = [
    ("NSIS", b"NullsoftInst", ["/S"]),
    ("Inno Setup", b"Inno Setup", ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]),
    ("InstallShield", b"InstallShield", ["/s", '/v"/qn"']),
    ("WiX Burn", b".wixburn", ["/quiet", "/norestart"]),
]

# Signatures live in the installer's stub/header, always near the start of
# the file even for multi-GB installers (the actual payload is appended
# after), so scanning a bounded prefix is enough and keeps this fast.
_SIGNATURE_SCAN_BYTES = 8 * 1024 * 1024


def detect_installer_type(local_path):
    """Sniffs local_path for a known installer-framework signature.

    Returns (type_name, default_flags_list) for the first match, or
    (None, None) if no known signature is found.
    """
    try:
        with open(local_path, "rb") as f:
            data = f.read(_SIGNATURE_SCAN_BYTES)
    except Exception as e:
        logging.warning(f"Could not read '{local_path}' for installer-type detection: {e}")
        return None, None

    for type_name, signature, default_flags in INSTALLER_SIGNATURES:
        if signature in data:
            return type_name, default_flags
    return None, None


class Installer:
    @staticmethod
    def install(local_path, silent_flags="", friendly_name="",
                pre_install_kill_list="", post_install_kill_list="",
                install_context="system"): # This parameter is now ignored but kept for compatibility
        """
        Final, simplified installer.
        It runs the command directly, inheriting the permissions of the service's "Log On As" user.
        This single method works for both system and user installers.
        """
        try:
            _run_process_cleanup(pre_install_kill_list, "Pre-Install Cleanup")

            timeout = TIMEOUTS.get('exe', 1800)
            base_cmd_list = []

            # --- Build the base command string ---
            if local_path.lower().endswith(".msi"):
                timeout = TIMEOUTS.get('msi', 600)
                # Note: msiexec works better when called directly by the shell
                base_cmd_list = ["msiexec", "/i", local_path, "/quiet", "/norestart"]
            elif local_path.lower().endswith((".bat", ".ps1")):
                timeout = TIMEOUTS.get('script', 900)
                cmd_path = local_path
                if local_path.lower().endswith(".ps1"):
                    base_cmd_list = ["powershell", "-ExecutionPolicy", "Bypass", "-File", cmd_path]
                else:
                    base_cmd_list = [cmd_path]
            elif local_path.lower().endswith(".exe"):
                if silent_flags:
                    # A manual catalog override always takes priority over
                    # auto-detection.
                    flags_list = shlex.split(silent_flags)
                else:
                    detected_type, default_flags = detect_installer_type(local_path)
                    if default_flags:
                        flags_list = default_flags
                        logging.info(
                            f"Auto-detected '{detected_type}' installer for "
                            f"'{friendly_name or local_path}'; using its standard "
                            f"silent flags: {flags_list}"
                        )
                    else:
                        flags_list = ["/S"]
                        logging.warning(
                            f"Could not auto-detect installer type for "
                            f"'{friendly_name or local_path}'; falling back to '/S' "
                            "(add explicit silent_flags in the catalog if this fails)."
                        )
                base_cmd_list = [local_path] + flags_list
            else:
                return False, f"Unsupported file type: {local_path}"

            # --- Simplified Direct Execution ---
            # All complex logic is removed. The service's "Log On As" account handles everything.
            logging.info(f"Executing command directly as service user: {base_cmd_list}")

            # Use subprocess.run for a simpler, blocking call with a hidden window.
            # shell=False with a list argv ensures shell metacharacters in silent_flags
            # are never re-interpreted by cmd.exe and reach the child process as literal args.
            result = subprocess.run(
                base_cmd_list,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # Check the result
            if result.returncode != 0:
                error_details = result.stderr or result.stdout
                logging.error(f"Installer exited with code {result.returncode}. Details:\n{error_details}")
                return False, f"Installation failed with exit code {result.returncode}."

            _run_process_cleanup(post_install_kill_list, "Post-Install Cleanup")
            return True, "Installation completed successfully."

        except subprocess.TimeoutExpired:
            logging.error(f"Installation of '{friendly_name}' timed out after {timeout} seconds.")
            return False, f"Installation timed out after {timeout} seconds."
        except Exception as e:
            error_message = f"An unexpected critical error occurred: {e}"
            logging.error(f"{error_message}", exc_info=True)
            return False, error_message
## Action Pl
 
    # def install(local_path, silent_flags="", friendly_name="", 
    #             pre_install_kill_list="", post_install_kill_list="", 
    #             install_context="system"):
    #     """
    #     Final robust installer.
    #     - Runs pre/post kill lists.
    #     - Handles MSI, Script, and EXE files.
    #     - Uses context: "user" runs directly, "system" uses PsExec -s.
    #     - If flags are empty for an EXE, it "intelligently guesses" from a list.
    #     """
    #     try:
    #         # 1. Pre-cleanup (always runs)
    #         _run_process_cleanup(pre_install_kill_list, "Pre-Install Cleanup")

    #         timeout = TIMEOUTS.get('exe', 1800) # Default EXE timeout
            
    #         # This list will hold one or more "base" commands to try
    #         base_commands_to_try = []

    #         # --- 2. Build the list of base commands ---
    #         if local_path.lower().endswith(".msi"):
    #             timeout = TIMEOUTS.get('msi', 600)
    #             base_commands_to_try.append(["msiexec", "/i", local_path, "/quiet", "/norestart"])
    #             install_context = "system" # MSIs must always run as System

    #         elif local_path.lower().endswith((".bat", ".ps1")):
    #             timeout = TIMEOUTS.get('script', 900)
    #             cmd = [local_path]
    #             if local_path.lower().endswith(".ps1"):
    #                 cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", local_path]
    #             base_commands_to_try.append(cmd)
            
    #         elif local_path.lower().endswith(".exe"):
    #             if silent_flags:
    #                 # FLAGS ARE PROVIDED: Trust the catalog. Only try this one command.
    #                 logging.info(f"Using provided catalog flags: {silent_flags}")
    #                 base_commands_to_try.append([local_path] + shlex.split(silent_flags))
    #             else:
    #                 # NO FLAGS: This is "Intelligent Guessing" mode. Build a list to try.
    #                 logging.warning(f"No silent flags provided for {friendly_name}. Attempting common defaults...")
    #                 for flags in [
    #                     ["/S"]
    #                     ["/S", "/NORESTART"],                 # NSIS (7-Zip, Notepad++)
    #                     ["/VERYSILENT", "/NORESTART"],        # Inno Setup (VLC)
    #                     ["/SILENT", "/NORESTART"],            # Alternate Inno Setup
    #                     ["/q", "/norestart"]                  # Basic quiet
    #                 ]:
    #                     base_commands_to_try.append([local_path] + flags)
            
    #         else:
    #             return False, f"Unsupported file type: {local_path}"

    #         # --- 3. Find PsExec (if we need it) ---
    #         # --- 3. Find PsExec (unconditionally) ---
    #         # MOVED: This now runs for both 'user' and 'system' contexts.
    #         psexec_path = os.path.join(config.APP_ROOT, "PsExec64.exe")
    #         if not os.path.exists(psexec_path): 
    #             psexec_path = os.path.join(config.APP_ROOT, "PsExec.exe")
    #         if not os.path.exists(psexec_path): 
    #             return False, "PsExec.exe not found. This is required for all install contexts."

    #         # --- 4. Loop and execute ... ---
    #         install_successful = False
    #         last_error_code = -1
    #         for base_cmd in base_commands_to_try:
    #             final_cmd = []
    #             if install_context == "user":
    #                 session_id = get_active_user_session() # Find the logged-in user
    #                 if session_id is not None:
    #                     # Run interactively in the user's session. -d detaches.
    #                     logging.info(f"Found active user session {session_id}. Running installer interactively.")
    #                     final_cmd = [psexec_path, "-d", "-i", str(session_id), "-accepteula"] + base_cmd
    #                 else:
    #                     # Fallback if no user is logged in
    #                     logging.warning("No active user session found. Falling back to system context.")
    #                     final_cmd = [psexec_path, "-s", "-accepteula"] + base_cmd
    #             else: # system context
    #                 final_cmd = [psexec_path, "-s", "-accepteula"] + base_cmd
                
    #             logging.info(f"Attempting command: {' '.join(final_cmd)}")
    #             try:
    #                 # Use the robust Popen/wait logic for each attempt
    #                 process = subprocess.Popen(final_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    #                 process.wait(timeout=timeout)
                    
    #                 if process.returncode == 0:
    #                     logging.info(f"✅ Success with command: {' '.join(final_cmd)}")
    #                     install_successful = True
    #                     break # Success! Exit the for-loop.
    #                 else:
    #                     last_error_code = process.returncode
    #                     logging.warning(f"Attempt failed (Exit Code: {last_error_code}). Trying next...")
                
    #             except subprocess.TimeoutExpired:
    #                 logging.warning("Attempt timed out. Trying next...")
    #                 if 'process' in locals() and process.poll() is None: process.kill()
    #             except Exception as e:
    #                 logging.warning(f"Attempt raised OS error: {e}. Trying next...")

    #         # --- 5. Final Report ---
    #         if not install_successful:
    #             return False, f"All install attempts failed. Last exit code: {last_error_code}"
            
    #         # Run post-install cleanup ONLY if successful
    #         _run_process_cleanup(post_install_kill_list, "Post-Install Cleanup")
    #         return True, "Installation completed successfully."

    #     except Exception as e: # Catch-all for any setup errors
    #         error_message = f"An unexpected critical error occurred: {e}"
    #         logging.error(f"❌ {error_message}", exc_info=True)
    #         return False, error_message

def _parse_windows_command_line(command_line):
    """Splits a Windows command-line string into argv exactly like Windows
    itself does (via CommandLineToArgvW), instead of shlex.split()'s POSIX
    shell rules.

    Registry UninstallString values are Windows command lines: backslash is
    just a path separator (never an escape character), and an unquoted path
    containing spaces is valid there even though it isn't valid shell syntax.
    shlex.split() assumes POSIX rules -- it strips backslashes as escape
    characters and splits on every unquoted space -- so an unquoted
    UninstallString like `C:\\Program Files\\Android\\Android Studio\\uninstall.exe`
    comes out mangled into garbage tokens with the backslashes stripped
    entirely (seen in practice: ['C:Program', 'FilesAndroidAndroid',
    'Studiouninstall.exe']). Quoted strings (e.g. 7-Zip's
    "C:\\Program Files (x86)\\7-Zip\\Uninstall.exe") happened to survive
    shlex intact, which is why this only ever showed up for some apps.
    """
    if not command_line:
        return []
    import ctypes
    # Explicit argtypes/restype are required here -- without them ctypes
    # assumes a plain c_int return, which truncates CommandLineToArgvW's
    # pointer result on 64-bit Windows.
    CommandLineToArgvW = ctypes.windll.shell32.CommandLineToArgvW
    CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    LocalFree = ctypes.windll.kernel32.LocalFree
    LocalFree.argtypes = [ctypes.c_void_p]

    argc = ctypes.c_int(0)
    argv_p = CommandLineToArgvW(command_line, ctypes.byref(argc))
    if not argv_p:
        raise ctypes.WinError()
    try:
        return [argv_p[i] for i in range(argc.value)]
    finally:
        LocalFree(argv_p)


def _split_uninstall_command(uninstall_string):
    """Splits a registry UninstallString into [executable, *args].

    A quoted path (e.g. 7-Zip's "C:\\Program Files (x86)\\7-Zip\\Uninstall.exe")
    is unambiguous -- CommandLineToArgvW parses it correctly.

    An UNQUOTED path containing spaces (e.g. Android Studio's bare
    C:\\Program Files\\Android\\Android Studio\\uninstall.exe) is genuinely
    ambiguous to ANY command-line parser, including Windows' own -- there's
    no way to tell "is a directory name with a space" apart from "two
    separate arguments" from the string alone. Windows itself resolves this
    exact ambiguity for unquoted service paths by trying progressively
    longer prefixes (splitting at each space) and taking the longest one
    that's an actual file on disk; we do the same thing here rather than
    guessing via shell-style tokenizing rules that don't apply to Windows
    paths at all.
    """
    uninstall_string = uninstall_string.strip()
    if uninstall_string.startswith('"'):
        return _parse_windows_command_line(uninstall_string)

    parts = uninstall_string.split(' ')
    for i in range(len(parts), 0, -1):
        candidate = ' '.join(parts[:i])
        if os.path.isfile(candidate):
            return [candidate] + parts[i:]
    # Nothing on disk matched any prefix -- fall back to the naive split so
    # the caller still gets a reasonable error instead of an empty list.
    return _parse_windows_command_line(uninstall_string)


class Uninstaller:
    @staticmethod
    def uninstall(name: str, inventory: dict, pre_uninstall_kill_list: str = ""):
        """
        Attempts to silently uninstall software on Windows, Linux, or macOS.
        Requires admin/sudo rights. Returns (success, message).
        """
        
        
        try:
            _run_process_cleanup(pre_uninstall_kill_list, "Pre-Uninstall Cleanup")
            time.sleep(2) # Give processes a moment to terminate
            
            system = platform.system()
            cmd = []

            if system == "Windows":
                target_software = next((s for s in inventory.get("installed_software", []) if s.get("name") == name and s.get("uninstall")), None)
                if not target_software:
                    return False, f"No uninstall command found for '{name}' in the inventory."
                
                uninstall_string = target_software["uninstall"]
                logging.info(f"Found Windows uninstall command: {uninstall_string}")
                
                # --- THIS IS THE CORRECTED LOGIC ---
                if 'msiexec.exe' in uninstall_string.lower():
                    # Find the MSI product code (the GUID in curly braces)
                    import re
                    match = re.search(r'\{([A-F0-9-]+)\}', uninstall_string, re.IGNORECASE)
                    if not match:
                        return False, f"Could not determine MSI product code from '{uninstall_string}'"
                    
                    product_code = match.group(0)
                    cmd = ["msiexec.exe", '/X', product_code, '/quiet', '/norestart']
                else:
                    # Windows command-line rules, not shlex's POSIX rules --
                    # see _split_uninstall_command's docstring for why (an
                    # unquoted UninstallString like Android Studio's
                    # otherwise comes out mangled).
                    parts = _split_uninstall_command(uninstall_string)
                    executable = parts[0]
                    args = parts[1:]
                    silent_flags = ['/s', '/q', '/quiet', '/silent', '/verysilent']
                    if not any(flag in arg.lower() for arg in args for flag in silent_flags):
                        args.append('/S')
                    cmd = [executable] + args
                # --- END OF CORRECTION ---

                logging.info(f"Running parsed command: {cmd}")
                # A silent uninstaller can still pop a dialog it can never
                # get an answer to (e.g. "please close the running
                # application first") -- a Windows Service has no desktop to
                # show it on, so without a timeout this would hang forever.
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)

            elif system == "Linux":
                if not os.geteuid() == 0:
                    return False, "Error: Slave must be run with sudo on Linux to uninstall software."
                if shutil.which("apt-get"):
                    cmd = ["apt-get", "remove", "-y", name]
                elif shutil.which("dnf"):
                    cmd = ["dnf", "remove", "-y", name]
                else:
                    return False, "Could not find a supported package manager (apt-get, dnf)."
                logging.info(f"Running uninstall command: {' '.join(cmd)}")
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)

            elif system == "Darwin": # macOS
                if not os.geteuid() == 0:
                    return False, "Error: Slave must be run with sudo on macOS to uninstall software."
                if shutil.which("brew"):
                    cmd = ["brew", "uninstall", name]
                else:
                    return False, "Could not find Homebrew. Only brew uninstalls are supported on macOS."
                logging.info(f"Running uninstall command: {' '.join(cmd)}")
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)

            else:
                return False, f"Uninstall is not supported for OS: {system}"

            success_message = f"Successfully uninstalled '{name}'."
            logging.info(f"{success_message}")
            return True, success_message

        except subprocess.TimeoutExpired:
            error_message = (
                f"Uninstaller for '{name}' did not finish within 300 seconds and was aborted. "
                "It may have been waiting on a dialog (e.g. 'close the running application first') "
                "that a background service can never see or answer -- try closing the application "
                "on the target machine before uninstalling, or uninstall it manually."
            )
            logging.error(error_message)
            return False, error_message
        except subprocess.CalledProcessError as e:
            error_output = e.stderr or e.stdout
            error_message = f"Uninstaller failed with exit code {e.returncode}. Details: {error_output.strip()}"
            logging.error(f"{error_message}")
            return False, error_message
        except Exception as e:
            error_message = f"An unexpected error occurred during uninstall: {e}"
            logging.error(f"{error_message}", exc_info=True)
            return False, error_message
        

def get_system_info():
    """Gathers a comprehensive system inventory."""
    logging.info("Gathering detailed system inventory...")
    inventory = {}
    software_list = []
    try:
        # --- OS Info ---
        uname = platform.uname()
        inventory["os_info"] = {
            "system": uname.system, "hostname": uname.node, "release": uname.release,
            "version": uname.version, "architecture": uname.machine
        }
        # --- CPU Info ---
        inventory["cpu_info"] = {
            "processor": uname.processor, "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True), "max_frequency": f"{psutil.cpu_freq().max:.2f} Mhz",
            "cpu_usage_percent": f"{psutil.cpu_percent(interval=1)}%"
        }
        # --- RAM Info ---
        ram = psutil.virtual_memory()
        inventory["ram_info"] = {
            "total": f"{ram.total/(1024**3):.2f} GB", "used": f"{ram.used/(1024**3):.2f} GB",
            "available": f"{ram.available/(1024**3):.2f} GB", "percentage_used": f"{ram.percent}%"
        }
        # --- Disk Info ---
        disk_info = {}
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_info[part.device] = {
                    "total_size": f"{usage.total/(1024**3):.2f} GB", "used": f"{usage.used/(1024**3):.2f} GB",
                    "free": f"{usage.free/(1024**3):.2f} GB", "percentage_used": f"{usage.percent}%"
                }
            except PermissionError: continue
        inventory["disk_info"] = disk_info
        # --- Boot Time ---
        bt = datetime.fromtimestamp(psutil.boot_time())
        inventory["boot_info"] = {"last_boot_time": bt.strftime("%Y/%m/%d %H:%M")}
        # --- Network Info ---
        net_info = {}
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    net_info["interface"] = name; net_info["ip_address"] = addr.address; net_info["netmask"] = addr.netmask
        inventory["network_info"] = net_info

        # --- Installed Software (Windows) ---
        if platform.system() == "Windows":
            try:
                # --- THIS IS THE MODIFIED PART ---
                cmd = ('''
                    $paths = @(
                        "HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
                        "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
                        "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*"
                    )
                    $results = @()
                    foreach ($path in $paths) {
                        try {
                            $results += Get-ItemProperty -Path $path -ErrorAction Stop | Select-Object DisplayName, DisplayVersion, Publisher, UninstallString
                        } catch {
                            # Ignore errors for paths that don't exist or are inaccessible
                        }
                    }
                    $results | Where-Object {$_.DisplayName -ne $null} | Sort-Object DisplayName | ConvertTo-Json -Compress
                ''')
                # --- END OF MODIFICATION ---
                
                result = subprocess.run(
                    ["powershell", "-Command", cmd],
                    capture_output=True, text=True, check=True, encoding="utf-8", timeout=60
                )
                parsed_json = json.loads(result.stdout)
                if isinstance(parsed_json, dict): parsed_json = [parsed_json]
                for item in parsed_json:
                    software_list.append({
                        "name": item.get("DisplayName"), "version": item.get("DisplayVersion", "N/A"),
                        "publisher": item.get("Publisher", "N/A"), "uninstall": item.get("UninstallString", "")
                    })
            except Exception as e:
                logging.error(f"Could not get software list from registry: {e}")

        inventory["installed_software"] = software_list
        return inventory
    except Exception as e:
        print(f"CRITICAL ERROR in get_inventory: {e}")
        logging.error(f"CRITICAL ERROR in get_inventory: {e}", exc_info=True)
        return {}
    
def run_shell_command(command):
    """Executes a shell command and captures its stdout, stderr, and return code."""
    try:
        # On Windows, built-in commands like 'ipconfig' require shell=True 
        # and work more reliably when passed as a single string.
        if platform.system() == "Windows":
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                shell=True,
                timeout=60  # Add a timeout to prevent hanging
            )
        else:
            # On Linux/macOS, it's safer to split the command and avoid using the shell.
            cmd_parts = shlex.split(command)
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=60
            )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except FileNotFoundError:
        # This can happen on Linux/macOS if the command isn't found
        return {
            "stdout": "",
            "stderr": f"Command not found: '{command}'",
            "returncode": 1
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"An unexpected error occurred: {e}",
            "returncode": 1
        }
    
def _powershell(cmd):
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]

# --- Replace your old run_health_check function with these four new ones ---

def _check_disk_space():
    """Checks for at least 5GB of free disk space."""
    if not has_enough_disk(5 * 1024**3):
        return False, "Low disk space (< 5GB free)"
    return True, "Disk space OK"

def _check_antivirus_windows():
    """On Windows, checks if an active antivirus is registered."""
    try:
        cmd = "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | Select-Object -First 1"
        result = subprocess.run(_powershell(cmd), capture_output=True, text=True, timeout=10)
        if not result.stdout.strip():
            return False, "No active antivirus product found."
        return True, "Antivirus OK"
    except Exception as e:
        logging.warning(f"Could not check antivirus status: {e}")
        return True, "Antivirus check skipped" # Fail open if check fails

def _check_processes():
    """Scans for suspicious processes from the config blacklist."""
    blacklisted = config.SUSPICIOUS_PROCESSES
    if not blacklisted:
        return True, "No processes to check"
    
    try:
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] in blacklisted:
                return False, f"Suspicious process found: {proc.info['name']}"
        return True, "Processes OK"
    except Exception as e:
        logging.warning(f"Could not check for suspicious processes: {e}")
        return True, "Process check skipped" # Fail open if check fails

def run_health_check():
    """Performs a series of pre-flight health checks on the slave system."""
    logging.info("Running pre-flight health checks...")
    
    checks = [
        _check_disk_space,
        _check_processes
    ]
    if platform.system() == "Windows":
        checks.append(_check_antivirus_windows)

    for check_func in checks:
        is_healthy, message = check_func()
        if not is_healthy:
            logging.warning(f"Health check failed: {message}")
            return False, message # Return immediately on the first failure
            
    logging.info("System health checks passed.")
    return True, "System Healthy"


class SystemPower:
    """Handles OS-level power operations like shutdown, restart, and sleep."""
    @staticmethod
    def _run(cmd, shell=False):
        """Executes a power command."""
        try:
            # The shell parameter is added to handle special cases
            subprocess.run(cmd, check=True, capture_output=True, text=True, shell=shell)
            # Command is a list for logging, convert string to list if needed
            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
            return True, f"Command '{cmd_str}' executed."
        except Exception as e:
            return False, f"Failed to execute power command: {e}"

    @staticmethod
    def shutdown():
        system = platform.system()
        if system == "Windows":
            return SystemPower._run(["shutdown", "/s", "/t", "1", "/f"])
        else: # Linux and macOS
            return SystemPower._run(["shutdown", "-h", "now"])

    @staticmethod
    def restart():
        system = platform.system()
        if system == "Windows":
            return SystemPower._run(["shutdown", "/r", "/t", "1", "/f"])
        else: # Linux and macOS
            return SystemPower._run(["shutdown", "-r", "now"])

    @staticmethod
    def sleep():
        system = platform.system()
        if system == "Windows":
            # CORRECTED: This specific command must be run with shell=True
            return SystemPower._run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
        elif system == "Linux":
            return SystemPower._run(["systemctl", "suspend"])
        elif system == "Darwin": # macOS
            return SystemPower._run(["pmset", "sleepnow"])
        return False, "Sleep not supported on this OS."


def find_installer_locally(filename):
    """
    Searches for an installer file in two local locations.
    Priority 1: The slave's dedicated cache folder.
    Priority 2: The system's main Downloads folder.
    Returns the full path if found, otherwise None.
    """
    # Location 1: Slave's local cache
    cache_path = Path(DOWNLOADS_PATH) / filename
    if cache_path.is_file():
        logging.info(f"Installer '{filename}' found in local cache.")
        return str(cache_path)

    # Location 2: User's main Downloads folder
    try:
        user_downloads_path = Path.home() / "Downloads" / filename
        if user_downloads_path.is_file():
            logging.info(f"Installer '{filename}' found in user's Downloads folder.")
            return str(user_downloads_path)
    except Exception as e:
        # Path.home() can fail in some environments, so we log errors gracefully.
        logging.warning(f"Could not check user's Downloads folder: {e}")

    # If not found in either location
    logging.info(f"Installer '{filename}' not found in any local search paths.")
    return None

def get_log_tail(num_lines=200):
    """Reads the last N lines from the slave's log file in ProgramData."""
    try:
        # Use the correct, reliable path in ProgramData
        log_dir = os.path.join(os.environ.get("ProgramData"), "SoftwareDeployerAgent", "logs")
        log_file = os.path.join(log_dir, "slave.log")

        if not os.path.exists(log_file):
            return f"Log file not found at the correct location: {log_file}"
        
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Get the last num_lines, or all lines if the file is short
        tail = lines[-num_lines:]
        return "".join(tail)
    except Exception as e:
        return f"Error reading log file: {e}"
    
def write_config_file(content):
    """Safely overwrites the slave's config.json file.

    Must target the same file get_config_content() reads (config.json) --
    this previously wrote to slave/config.py (the PYTHON SOURCE FILE)
    instead, a leftover from before settings lived in config.json. Using the
    master's remote "Get/Save Configuration" editor would have silently
    overwritten the agent's own source file with JSON text (and in a frozen
    build, config.py doesn't even exist as a real file to write to at all).
    """
    try:
        json.loads(content)  # reject malformed JSON before ever touching the file
        config_json_path = os.path.join(config.APP_ROOT, "config.json")
        with open(config_json_path, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info("Successfully updated config.json.")
        return True, "Config file updated."
    except json.JSONDecodeError as e:
        logging.error(f"Rejected config.json write: invalid JSON: {e}")
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        logging.error(f"Failed to write to config.json: {e}")
        return False, str(e)

#restart while it still in terminal not in services

# def restart_agent():
#     """Restarts the slave agent process by re-running it as a module."""
#     logging.info("Restarting agent to apply new settings...")
#     try:
#         # Construct the command to run the 'slave' package as a module.
#         # This ensures that relative imports work correctly on restart.
#         args = [sys.executable, "-m", "slave"]
#         logging.info(f"Relaunching with command: {args}")

#         # Use Popen to launch a new, independent process.
#         subprocess.Popen(args)

#         # Exit the current process cleanly.
#         sys.exit(0)
#     except Exception as e:
#         logging.error(f"Failed to restart agent: {e}")

class RestartServiceException(Exception):
    """Custom exception to signal that the service needs to restart."""
    pass

def is_running_as_service():
    """
    Checks if the current script is likely running as a Windows service by
    checking if the parent process is services.exe.
    """
    try:
        import psutil
        # The parent of a service process is usually services.exe
        parent = psutil.Process(os.getppid())
        return parent.name().lower() == "services.exe"
    except (ImportError, psutil.Error):
        # If psutil is not available or we can't get the parent, assume not a service.
        return False

def restart_agent():
    """
    Restarts the agent. Uses the correct method depending on whether
    it's running as a service or from a terminal.
    """
    if is_running_as_service():
        # --- MODIFIED: Raise the custom exception for services ---
        logging.info("Signaling service manager to restart the agent...")
        raise RestartServiceException()
    else:
        # --- NO CHANGE: Terminal restart logic is the same ---
        logging.info("Restarting agent process from terminal...")
        try:
            args = [sys.executable] + sys.argv
            logging.info(f"Relaunching with command: {args}")
            subprocess.Popen(args)
            sys.exit(0)
        except Exception as e:
            logging.error(f"Failed to restart agent from terminal: {e}")

def get_config_content():
    """Reads the raw text content of the slave's config.json file."""
    try:
        # Use the reliable APP_ROOT from the config module to find config.json
        config_json_path = os.path.join(config.APP_ROOT, "config.json")
        with open(config_json_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Could not read own config.json file: {e}")
        return f"# Error reading slave config.json file:\n# {e}"       

def execute_script_file(script_path):
    """Executes a .bat or .ps1 file and captures the output."""
    system = platform.system()
    if system != "Windows":
        return { "stdout": "", "stderr": f"Script execution is not supported on {system}.", "returncode": 1 }

    cmd = []
    if script_path.lower().endswith(".ps1"):
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path]
    elif script_path.lower().endswith(".bat"):
        cmd = [script_path]
    else:
        return { "stdout": "", "stderr": "Unsupported script file type.", "returncode": 1 }

    try:
        logging.info(f"Executing script: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=config.TIMEOUTS.get('script', 900)
        )
        return {
            "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return { "stdout": "", "stderr": "Script execution timed out.", "returncode": -1 }
    except Exception as e:
        return { "stdout": "", "stderr": f"An unexpected error occurred: {e}", "returncode": -1 }    
    
def handle_self_update(command, service_name, master_ip):
    """
    Handles the entire agent self-update process.
    Downloads new agent, creates an updater script, and executes it.
    """
    try:
        filename = command.get("filename")
        expected_hash = command.get("sha256")
        download_method = command.get("download_method", "direct")

        if not all([filename, expected_hash, service_name]):
            logging.error("AGENT_UPDATE: Invalid update command. Missing data.")
            return

        # 1. Download the new agent executable
        logging.info(f"AGENT_UPDATE: Downloading new agent: {filename} via {download_method}")
        
        # Download to a named temporary file
        temp_dir = tempfile.gettempdir()
        new_agent_path = os.path.join(temp_dir, filename)

        downloader = download_from_ftp if download_method == "ftp" else lambda f: download_from_master(master_ip, f)
        downloaded_path = downloader(filename)
        
        if not downloaded_path:
            logging.error("AGENT_UPDATE: Download of new agent failed.")
            return

        # Manually move from our cache to the temp path if they are different
        # (This is safer as the cache dir might be part of the running agent)
        if downloaded_path != new_agent_path:
             shutil.move(downloaded_path, new_agent_path)

        # 2. Verify hash
        actual_hash = sha256_file(new_agent_path)
        if actual_hash != expected_hash:
            logging.error(f"AGENT_UPDATE: HASH MISMATCH! Expected {expected_hash} but got {actual_hash}. Deleting file.")
            os.remove(new_agent_path)
            return

        logging.info("AGENT_UPDATE: Hash verified. Preparing update script.")

        # 3. Get path to current running executable
        current_exe_path = sys.executable  # This points to the slave-service.exe itself
        backup_exe_path = current_exe_path + ".bak"
        updater_bat_path = os.path.join(temp_dir, "agent_updater.bat")

        # 4. Create the updater batch script.
        # Stops the service, backs up the CURRENT (working) exe, swaps in the
        # new one, starts the service, then verifies it actually reaches
        # RUNNING within ~20s -- if it doesn't (e.g. an admin accidentally
        # pushed the wrong file, such as the Inno Setup installer package
        # instead of the real agent exe, which can't run as a service at
        # all), automatically rolls back to the backup and restarts it,
        # instead of leaving the machine with a permanently broken agent
        # that then needs physical/remote-desktop access to fix by hand.
        bat_content = f"""
@echo off
echo Stopping {service_name} for update...
sc stop "{service_name}"

:loop
echo Waiting for service to stop...
sc query "{service_name}" | find "STATE" | find "STOPPED" > NUL
if %errorlevel% == 0 (
    echo Service is stopped. Proceeding with update.
    goto proceed
)
timeout /t 3 /nobreak > NUL
goto loop

:proceed
echo Backing up current agent executable...
copy /Y "{current_exe_path}" "{backup_exe_path}"

echo Replacing executable...
move /Y "{new_agent_path}" "{current_exe_path}"

echo Starting new agent service...
sc start "{service_name}"

echo Verifying the new agent actually started...
set VERIFY_ATTEMPTS=0
:verify_loop
set /a VERIFY_ATTEMPTS+=1
sc query "{service_name}" | find "RUNNING" > NUL
if %errorlevel% == 0 (
    echo Update verified successful - new agent is running.
    del "{backup_exe_path}"
    goto cleanup
)
if %VERIFY_ATTEMPTS% GEQ 10 (
    echo New agent failed to start after update! Rolling back to the previous version...
    sc stop "{service_name}"
    timeout /t 2 /nobreak > NUL
    move /Y "{backup_exe_path}" "{current_exe_path}"
    sc start "{service_name}"
    echo Rollback complete.
    goto cleanup
)
timeout /t 2 /nobreak > NUL
goto verify_loop

:cleanup
echo Cleaning up updater...
del "{updater_bat_path}"
"""
        with open(updater_bat_path, "w") as f:
            f.write(bat_content)

        # 5. Launch the updater.bat as a completely detached process
        # This is CRITICAL. The .bat file must run independently of the Python script
        # that is about to be terminated by the 'sc stop' command.
        logging.info(f"AGENT_UPDATE: Launching detached updater: {updater_bat_path}")
        subprocess.Popen(
            [updater_bat_path],
            shell=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # 6. Gracefully shut down this (old) agent
        logging.info("AGENT_UPDATE: Handed off to updater. Shutting down current process.")
        # We raise the service exception to tell the Windows Service Manager we are stopping
        # This will be caught by your service wrapper (if you have one) or just kill the proc.
        raise RestartServiceException("Handing off to updater") 

    except Exception as e:
        logging.error(f"AGENT_UPDATE: A critical error occurred during update: {e}", exc_info=True)    
