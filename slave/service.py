import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import os
import sys
import time
import threading
import subprocess

# --- IMPORTANT ---
# This assumes your 'slave' package is in the same directory or in your PYTHONPATH
# If running from your project root, we must add the project root to the path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

from slave import logger as slave_logger
from slave.client import SlaveClient, RestartServiceException
from slave import config

# --- CHANGE THESE TO MATCH YOUR SERVICE ---
SERVICE_NAME = config.SERVICE_NAME # Use the name from your config file
SERVICE_DISPLAY_NAME = "Smart Software Deployer - Slave Agent"
SERVICE_DESCRIPTION = "Slave agent for Smart Software Deployer. Runs as LocalSystem."

def configure_service_recovery(service_name):
    import subprocess
    try:
        servicemanager.LogInfoMsg(f"{service_name} - Configuring recovery options...")
        subprocess.run(
            ['sc', 'failure', service_name, 'reset=', '86400', 'actions=', 'restart/5000'],
            check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as e:
        servicemanager.LogErrorMsg(f"{service_name} - Failed to configure recovery: {e.stdout} {e.stderr}")

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def install_tray_autostart():
    """
    Registers slave/tray_app.py to launch for ANY user who logs on to this
    machine, via the classic HKLM "Run" registry key -- the same mechanism
    virtually every tray utility uses (antivirus icons, cloud-sync clients,
    etc). Windows itself launches every HKLM Run entry once per interactive
    logon, for whichever user is logging in, automatically and with no
    extra scheduling logic needed.

    This replaces an earlier Scheduled Task-based approach (-AtLogOn
    trigger + a GroupId "BUILTIN\\Users" principal): registering a
    group-based scheduled task turned out to intermittently fail with
    "Access is denied" in the installer's actual execution context, even
    though the installer itself runs elevated -- a real, reproduced
    failure, not a hypothetical one. HKLM Run has no such principal/
    elevation subtleties: writing the value is the only privileged step
    (done once, here, while already running elevated at install time), and
    Windows' own logon processing handles the rest for every user from
    then on.

    This is best-effort: any failure is logged and swallowed so it can
    never block the actual service install.
    """
    try:
        if getattr(sys, 'frozen', False):
            exe_path = os.path.join(os.path.dirname(sys.executable), "tray_app.exe")
            if not os.path.exists(exe_path):
                servicemanager.LogWarningMsg(
                    f"{SERVICE_NAME} - tray_app.exe not found next to the agent executable; "
                    "skipping tray autostart registration. Compile slave/tray_app.py separately "
                    "(see its header comment) and place tray_app.exe alongside the agent exe."
                )
                return
            command = f'"{exe_path}"'
        else:
            python_dir = os.path.dirname(sys.executable)
            pythonw_path = os.path.join(python_dir, "pythonw.exe")
            if not os.path.exists(pythonw_path):
                pythonw_path = sys.executable
            script_path = os.path.join(project_root, "slave", "tray_app.py")
            command = f'"{pythonw_path}" "{script_path}"'

        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(key, f"{SERVICE_NAME}Tray", 0, winreg.REG_SZ, command)
        finally:
            winreg.CloseKey(key)
        servicemanager.LogInfoMsg(f"{SERVICE_NAME} - Tray app autostart registered via HKLM Run key for all users.")
    except Exception as e:
        servicemanager.LogWarningMsg(f"{SERVICE_NAME} - Unexpected error registering tray autostart (non-fatal): {e}")

def remove_tray_autostart():
    """Removes the tray app's autostart Run-key entry, if present. Best-effort/non-fatal."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            try:
                winreg.DeleteValue(key, f"{SERVICE_NAME}Tray")
            except FileNotFoundError:
                pass
        finally:
            winreg.CloseKey(key)
        servicemanager.LogInfoMsg(f"{SERVICE_NAME} - Tray app autostart registry entry removed (if it existed).")
    except Exception as e:
        servicemanager.LogWarningMsg(f"{SERVICE_NAME} - Unexpected error removing tray autostart (non-fatal): {e}")

def restart_service(service_name, delay=2):
    """Restart the given Windows service safely from within the service process."""
    def _restart():
        try:
            servicemanager.LogInfoMsg(f"{service_name} - Restarting service in {delay} seconds...")
            time.sleep(delay)
            win32serviceutil.RestartService(service_name)
        except Exception as e:
            servicemanager.LogErrorMsg(f"{service_name} - Failed to restart: {e}")

    # Run in a separate thread to avoid blocking the main service loop
    threading.Thread(target=_restart, daemon=True).start()

class SoftwareDeployerAgentSvc(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.client = None
        self.is_running = True

    def SvcStop(self):
        """Called when the Windows Service Manager tries to stop the service."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        servicemanager.LogInfoMsg(f"{SERVICE_NAME} - Stop command received.")
        
        if self.client:
            self.client.is_running = False
            
        self.is_running = False
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        """The main entry point for the service, now with robust connect-then-discover logic."""
        # Use a reliable, service-writable path in ProgramData
        log_dir = os.path.join(os.environ['ProgramData'], 'SoftwareDeployerAgent', 'logs')
        slave_logger.setup_logging(log_dir=log_dir)
        #servicemanager.LogInfoMsg(f"{SERVICE_NAME} - Service starting.")
        
        RECONNECT_DELAY_SECONDS = 15

        while self.is_running:
            try:
                master_ip = None
                control_port = config.PORTS.get("control", 5050)

                # --- STEP 1: Try Configured IP First (New Logic) ---
                configured_ip = config.MASTER_IP
                if configured_ip and configured_ip.lower().strip() not in ['none', 'null', '']:
                    #servicemanager.LogInfoMsg(f"Attempting connection to configured MASTER_IP: {configured_ip}")
                    master_ip = configured_ip
                    
                    self.client = SlaveClient(master_ip, control_port)
                    if not self.client.start():
                        servicemanager.LogErrorMsg("Exiting due to a fatal, unrecoverable error.")
                        self.SvcStop()
                        break

                    servicemanager.LogWarningMsg(f"Connection to configured IP {master_ip} failed or was lost. Falling back to discovery.")
                    master_ip = None

                # --- STEP 2: Fallback to Discovery (New Logic) ---
                if not master_ip and self.is_running:
                    #servicemanager.LogInfoMsg("MASTER_IP not set or failed to connect. Starting discovery...")
                    discovered_ip, discovered_port = SlaveClient.discover_master()

                    if discovered_ip:
                        master_ip = discovered_ip
                        if discovered_port:
                            control_port = discovered_port
                        
                        servicemanager.LogInfoMsg(f"Master discovered at {master_ip}:{control_port}. Connecting...")
                        self.client = SlaveClient(master_ip, control_port)
                        if not self.client.start():
                            servicemanager.LogErrorMsg("Exiting due to fatal error on discovered IP.")
                            self.SvcStop()
                            break
                    else:
                        servicemanager.LogWarningMsg("Could not find master via discovery.")
                
                # --- STEP 3: Wait Before Retrying ---
                if self.is_running:
                    #servicemanager.LogInfoMsg(f"Restarting connection process in {RECONNECT_DELAY_SECONDS} seconds.")
                    time.sleep(RECONNECT_DELAY_SECONDS)

            except RestartServiceException:
                servicemanager.LogInfoMsg(f"{SERVICE_NAME} - Restart triggered. Stopping service to allow SCM recovery.")
                self.SvcStop()
            except Exception as e:
                servicemanager.LogErrorMsg(f"CRITICAL SvcDoRun LOOP FAILURE: {e}")
                if self.is_running:
                    time.sleep(30)

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize(SERVICE_NAME, None)
        servicemanager.PrepareToHostSingle(SoftwareDeployerAgentSvc)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SoftwareDeployerAgentSvc)

        # Configure recovery and tray-app autostart only on 'install'.
        # Checked via membership, not sys.argv[1] == 'install' -- pywin32's
        # HandleCommandLine requires options like --startup=auto to come
        # BEFORE the command (see SlaveSetup.iss's [Run] section), which
        # shifts 'install' to a later argv index. sys.argv[1] == 'install'
        # silently evaluated to False for every real install since the
        # --startup=auto fix shipped, meaning this block (and therefore
        # both service-crash recovery AND tray autostart registration)
        # was never actually running at all.
        if 'install' in sys.argv[1:]:
            configure_service_recovery(SERVICE_NAME)
            install_tray_autostart()
        elif 'remove' in sys.argv[1:]:
            remove_tray_autostart()
