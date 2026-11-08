"""Module: app
The main controller for the master server application.
"""

import os, json, threading, time, hashlib, csv, platform, traceback, shutil
from datetime import datetime, timezone
import queue
from .networking import NetworkServer
from .pairing import PairingManager
# from .db import insert, read_all, find_one
from . import db
from .config import RETRY, SCHEDULER, AUTO_UPDATE, CATALOG, FTP, POLICIES
from .gui_modern import MainGUI, ScheduleTimeDialog, SlaveLogPopup
import socket
import logging
from . import logger as master_logger
from ftplib import FTP_TLS,FTP as FTP_Client, error_perm
import tkinter as tk
from tkinter import ttk, messagebox
import importlib # <-- Add this import
from . import config
from .config import FTP_CONFIG, FTP_ENV, RETRY
import os
from . import config



def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# In master/app.py

class MasterAppController:
    def __init__(self, root, authenticated_user):
        self.current_user = authenticated_user
        db.init_database()
        self.last_inventories = {}
        self.slave_connection_times = {}
        self.root = root

        # Tracks in-flight group screenshot requests: hostname -> group_name,
        # so an incoming "screenshot_data" status can be routed to the right
        # multi-host results window instead of always popping up a lone popup.
        self._current_screenshot_request = {}

        # Tracks in-flight multi-app install batches: batch_id -> list of
        # {"hostname", "filename", "friendly_name", "status"} dicts. Only
        # created when 3+ apps are queued together via "Install from
        # Catalog" -- for 1-2 apps the existing per-item toast notifications
        # (see _handle_status_received) are enough on their own. As matching
        # per-item status updates arrive, _update_install_batches fills in
        # each row's final status in the popup opened for that batch.
        self._active_install_batches = {}
        self._install_batch_seq = 0

        # --- Policy Management / Compliance Engine state ---
        self.compliance_engine_enabled = db.get_setting('compliance_engine_enabled', 'False') == 'True'
        # Seed with "now" (not 0) so the Block 2 scheduled check in
        # _scheduler_loop waits a full interval before firing, rather than
        # firing immediately on top of the startup check below.
        self.last_policy_check_time = time.time()

        self.running = True

        # CORRECTED: Consolidated callbacks dictionary with no duplicates
        gui_callbacks = {
            "on_request_inventory": self.request_inventory,
            "on_deploy_file": self.deploy_file_to_host,
            "on_deploy_catalog": self.deploy_to_selected_nodes,
            "on_uninstall": self.uninstall_on_host,
            "on_disconnect": self.disconnect_slave,
            "on_add_group": self.add_to_group,
            "on_remove_from_group": self.remove_from_group,
            "on_delete_group": self.delete_group_from_storage,
            "on_bulk_install_group": self.bulk_install_group,
            "on_schedule_install": self.schedule_install,
            "on_bulk_uninstall": self.bulk_uninstall_from_group,
            "on_slave_log": self.handle_slave_log,
            "on_get_all_slave_statuses": self.get_all_slave_statuses,
            "on_get_dashboard_stats": self.get_dashboard_stats,
            "get_online_hosts": lambda: self.network.clients.keys(),
            "get_last_inventory": lambda host: self.last_inventories.get(host),
            "on_get_catalog_names": self.get_catalog_software_names,
            "on_get_installable_software": self.get_installable_catalog_software,
            "on_get_installer_filenames": self._get_installers_from_folder,
            "get_offline_count": self.get_offline_slave_count,
            "on_retry_deployment": self.retry_deployment,
            "on_get_hosts_with_software": self.get_hosts_with_software,
            "on_get_catalog_data": self.get_catalog_data,
            "on_save_catalog_data": self.save_catalog_data,
            "on_send_file_group": self.send_file_to_group,
            "on_send_file_hosts": self.send_file_to_hosts,
            "on_request_slave_log": self.request_slave_log,
            "on_rename_group": self.rename_group,
            "on_set_slave_alias": self.set_slave_alias,
            "on_get_audit_log": self.get_audit_log_data,
            "on_get_all_groups": self.get_all_groups_data,
            "on_view_master_log": self.view_master_log_file,
            "on_verify_catalog_files": self.verify_catalog_files,
            "on_create_group": self.create_group,
            "on_reconnect": self.reconnect_slave,
            "on_get_config_file": self.get_config_content,
            "on_save_config_file": self.save_app_settings,
            "on_save_slave_config": self.save_slave_config, # <-- Add this line
            "on_restart_slave_agent": self.restart_slave_agent,
            "on_request_slave_config": self.request_slave_config,
            "on_update_agents": self.update_slave_agents,
            "on_update_agents_group": self.update_agents_in_group,
            "on_get_hostnames_for_group": self._get_hostnames_for_group, # Add this helper if not already exposed
            "on_send_and_extract_zip": self.send_and_extract_zip,

            # --- Slave Pairing ---
            "on_start_pairing": self.start_pairing,
            "on_stop_pairing": self.stop_pairing,
            "on_get_pairing_status": self.get_pairing_status,
            "on_revoke_pairing": self.revoke_pairing,

            # --- Power Control ---
            "on_system_shutdown": self.system_shutdown,
            "on_system_restart": self.system_restart,
            "on_system_sleep": self.system_sleep,

            # --- Broadcast Message ---
            "on_broadcast_message": self.broadcast_message_to_slaves,

            # --- Screenshot Capture ---
            "on_request_screenshot": self.request_screenshot,
            "on_request_group_screenshots": self.request_group_screenshots,

            # --- Scripts tab + remote command/script execution ---
            "on_get_all_scripts": self.get_all_scripts,
            "on_save_script": self.save_script,
            "on_delete_script": self.delete_script,
            "on_run_command_on_nodes": self.run_command_on_nodes,
            "on_run_script_file": self.run_script_file_on_nodes,

            # --- Policy Management ---
            "on_create_policy": self.create_policy,
            "on_get_policies": self.get_all_policies,
            "on_delete_policy": self.delete_policy,
            "on_rename_policy": self.rename_policy,
            "on_assign_policy_to_group": self.assign_policy_to_group,
            "on_get_policy_rules": self.get_policy_rules,
            "on_add_rule_to_policy": self.add_rule_to_policy,
            "on_remove_rule": self.remove_rule_from_policy,
            "on_set_policy_auto_check": self.set_policy_auto_check,
            "on_set_compliance_state": self.set_compliance_engine_state,
            "on_run_compliance_check": self.trigger_manual_compliance_check,
            "on_remove_policy_from_group": self.remove_policy_from_group,
            "on_export_compliance": self.show_compliance_report,
            "on_get_group_assignments": self.get_group_assignments,
            "on_save_csv": self.save_report_to_csv,

        }

        admin_only_callbacks = {
            "on_deploy_file", "on_deploy_catalog", "on_uninstall",
            "on_add_group", "on_remove_from_group", "on_delete_group",
            "on_bulk_install_group", "on_schedule_install", "on_bulk_uninstall",
            "on_retry_deployment", "on_save_catalog_data", "on_send_file_group",
            "on_send_file_hosts", "on_rename_group", "on_set_slave_alias",
            "on_create_group", "on_reconnect",
            "on_save_config_file", "on_save_slave_config", "on_restart_slave_agent",
            "on_update_agents", "on_update_agents_group",
            "on_send_and_extract_zip",
            "on_start_pairing", "on_stop_pairing", "on_revoke_pairing",
            "on_system_shutdown", "on_system_restart", "on_system_sleep",
            "on_broadcast_message",
            "on_save_script", "on_delete_script",
            "on_run_command_on_nodes", "on_run_script_file",
            "on_create_policy", "on_delete_policy", "on_rename_policy",
            "on_assign_policy_to_group", "on_add_rule_to_policy", "on_remove_rule",
            "on_set_policy_auto_check", "on_set_compliance_state",
            "on_remove_policy_from_group",
        }
        for callback_name in admin_only_callbacks:
            if callback_name in gui_callbacks:
                gui_callbacks[callback_name] = self._admin_only(gui_callbacks[callback_name])

        self.gui = MainGUI(root, gui_callbacks)
        self.gui.set_user(self.current_user)
        self.gui.set_compliance_toggle_state(self.compliance_engine_enabled)
        self.gui_queue = queue.Queue()

        self.pairing = PairingManager(on_event=lambda message: self.gui_queue.put(("pairing_event", message)))
        self.network = NetworkServer(
            pairing=self.pairing,
            on_slave_connected=lambda h, i: self.gui_queue.put(("slave_connected", h, i)),
            on_slave_disconnected=lambda h: self.gui_queue.put(("slave_disconnected", h)),
            on_inventory=lambda h, i: self.gui_queue.put(("inventory_received", h, i)),
            on_status=lambda h, m: self.gui_queue.put(("status_received", h, m)),
            on_slave_log=lambda h, d: self.gui_queue.put(("slave_log_received", h, d)),
            on_slave_log_file=lambda h, d: self.gui_queue.put(("log_content_received", h, d)),
            on_slave_config_file=lambda h, d: self.gui_queue.put(("config_content_received", h, d))
        )
        self.network.start()
        self.scheduled = []
        threading.Thread(target=self._scheduler_loop, daemon=True).start()

        # One-time compliance check shortly after startup, so newly-applied
        # policies get enforced even if no scheduled interval has elapsed yet.
        def _startup_compliance_check():
            time.sleep(15)
            self._run_compliance_check(trigger_source="Automatic Startup")
        threading.Thread(target=_startup_compliance_check, daemon=True).start()

        self._load_persisted_inventory()
        self._load_all_known_slaves()

        self.root.after(100, self._process_gui_queue)

    def _admin_only(self, callback):
        """Guard destructive GUI actions for administrator accounts."""
        def guarded_callback(*args, **kwargs):
            if str(self.current_user.get("role", "user")).lower() != "admin":
                messagebox.showerror(
                    "Permission denied",
                    "Administrator permission is required for this action.",
                    parent=self.root,
                )
                return None
            return callback(*args, **kwargs)

        return guarded_callback

    # Inside class MasterAppController:
    def send_and_extract_zip(self, hostnames, filepath):
        """Handles the dedicated workflow for sending and auto-extracting a ZIP."""
        if not hostnames: return
        if not filepath or not filepath.lower().endswith(".zip"):
            self.gui.append_log("❌ ERROR: Invalid file path or not a ZIP file provided for send_and_extract_zip.")
            return

        filename = os.path.basename(filepath)
        digest = sha256_file(filepath) #

        # --- HYBRID FTP/Direct Logic ---
        use_ftp = False
        if FTP.get("enabled") and len(hostnames) > FTP.get("threshold", 0):
            self.gui.append_log(f"FTP: Target count exceeds threshold for '{filename}'. Using FTP.")
            success, _ = self._upload_to_ftp(filepath) #
            if not success:
                self.gui.append_log(f"❌ CRITICAL: FTP upload failed for '{filename}'. Aborting Send & Extract.")
                messagebox.showerror("FTP Error", f"Failed to upload {filename} to FTP server. Cannot proceed.", parent=self.root)
                return
            use_ftp = True
        else:
            # Direct transfer relies on the master's own file server, which
            # only serves files physically inside INSTALLERS_DIR.
            self._ensure_file_in_installers_dir(filepath)
        # --- END HYBRID ---

        # --- Construct the NEW Command ---
        msg = {
            "action": "receive_and_extract_zip", # New action name
            "filename": filename,
            "sha256": digest,
            "download_method": "ftp" if use_ftp else "direct",
        }

        self.gui.append_log(f"Queueing Send & Extract ZIP for '{filename}' to {len(hostnames)} target(s)...")

        online_count = 0
        offline_count = 0
        for hostname in hostnames:
            if hostname in self.network.clients:
                self.network.send_to_client(hostname, msg) #
                online_count += 1
            else:
                db.queue_command(hostname, msg) #
                offline_count += 1

        if online_count > 0: self.gui.append_log(f"  -> Sent command to {online_count} online slave(s).")
        if offline_count > 0: self.gui.append_log(f"  -> Queued command for {offline_count} offline slave(s).")

        self._log_action("SEND_EXTRACT_ZIP", f"{len(hostnames)} hosts", filename)

    # ------------------------------------------------------------------------
    def update_agents_in_group(self, group_name):
        """Resolves a group name into hosts and triggers the bulk agent update."""
        self.gui.append_log(f"Resolving hosts for group '{group_name}' for agent update...")
        
        # This helper function already knows how to get all hosts for "All Nodes"
        hostnames = self._get_hostnames_for_group(group_name) 
        
        if not hostnames:
            self.gui.append_log(f"Warning: Group '{group_name}' contains no hosts. Aborting update.")
            return
        
        # We just call the existing bulk update function with the resolved list of hosts
        self.update_slave_agents(hostnames)

    def update_slave_agents(self, hostnames):
        """Prompts for a new agent .exe and sends an update command to target hosts."""
        
        # 1. Ask user to find the new compiled agent executable
        initial_dir = os.path.join(config.PROJECT_ROOT, "dist")

        filepath = tk.filedialog.askopenfilename(
            title="Select New Agent Executable",
            initialdir=initial_dir, # <-- ADD THIS LINE
            filetypes=[("Executable", "*.exe"), ("All Files", "*.*")],
            parent=self.root
        )
        if not filepath:
            self.gui.append_log("Agent update cancelled by user.")
            return

        filename = os.path.basename(filepath)

        # A wrong-file mistake here is expensive: the updater stops the live
        # service and swaps this file in as the new agent binary. Picking
        # the Inno Setup INSTALLER package (e.g. slave.exe/master.exe from
        # installer_build\out) instead of the actual compiled agent
        # (SoftwareDeployerAgent.exe from installer_build\dist\slave) breaks
        # the service on every target, since an installer wizard can't run
        # as a Windows Service at all. Force an explicit, filename-shown
        # confirmation whenever the name doesn't match what's expected.
        expected_name = "SoftwareDeployerAgent.exe"
        if filename.lower() != expected_name.lower():
            if not messagebox.askyesno(
                "Confirm Agent Executable",
                f"You selected:\n\n  {filename}\n\n"
                f"The real agent executable is normally named '{expected_name}'. "
                "If this is actually the Inno Setup INSTALLER package (e.g. slave.exe or "
                "master.exe from installer_build\\out) rather than the raw agent build "
                "from installer_build\\dist\\slave, pushing it will break the agent "
                "service on every target and require fixing each machine by hand.\n\n"
                f"Are you certain '{filename}' is the correct agent executable to push?",
                icon="warning", parent=self.root
            ):
                self.gui.append_log("Agent update cancelled by user (file confirmation declined).")
                return

        digest = sha256_file(filepath)
        self.gui.append_log(f"Preparing to update {len(hostnames)} agents with new file: {filename}")

        # 2. Determine download method (use existing hybrid logic)
        use_ftp = False
        if FTP.get("enabled") and len(hostnames) > FTP.get("threshold", 0):
            self.gui.append_log(f"FTP: Target count exceeds threshold. Using FTP for agent transfer.")
            success, _ = self._upload_to_ftp(filepath)
            if not success:
                self.gui.append_log(f"❌ CRITICAL: FTP upload of new agent failed. Aborting update.")
                return
            use_ftp = True
        else:
            # Direct transfer relies on the master's own file server, which
            # only serves files physically inside INSTALLERS_DIR.
            filepath = self._ensure_file_in_installers_dir(filepath)

        # 3. Build the new "update_agent" command
        msg = {
            "action": "update_agent",
            "filename": filename,
            "sha256": digest,
            "download_method": "ftp" if use_ftp else "direct",
        }

        # 4. Send the command to all hosts (send or queue)
        online_count = 0
        offline_count = 0
        for hostname in hostnames:
            if hostname in self.network.clients:
                self.network.send_to_client(hostname, msg)
                online_count += 1
            else:
                db.queue_command(hostname, msg) # This will run when the agent comes online
                offline_count += 1

        if online_count > 0:
            self.gui.append_log(f"Sent update command to {online_count} online agent(s).")
        if offline_count > 0:
            self.gui.append_log(f"Queued update command for {offline_count} offline agent(s).")
            
        self._log_action("UPDATE_AGENT", f"{len(hostnames)} hosts", filename)

    def _get_hostnames_for_group(self, group_name):
        """Resolves a group name into a list of hostnames, handling the special 'All Nodes' case."""
        if group_name == "All Nodes":
            # If 'All Nodes' is selected, get every slave from the database
            return [s.get("hostname") for s in db.read_all("slaves")]
        else:
            # Otherwise, get only the members of the specified group
            return [r.get("hostname") for r in db.read_all("group_members") if r.get("group_name") == group_name]
        
    def request_slave_config(self, hostname):
        """Sends a command to a slave to request its config file."""
        self.gui.append_log(f"Requesting config file from '{hostname}'...")
        msg = {"action": "get_config"}
        self.network.send_to_client(hostname, msg)

    def save_slave_config(self, hostname, content):
        """Sends new config content to a slave to be written to its file."""
        self.gui.append_log(f"Sending updated config file to '{hostname}'...")
        msg = {"action": "write_config", "data": content}
        self.network.send_to_client(hostname, msg)

    def restart_slave_agent(self, hostname):
        """Commands a slave agent to restart itself."""
        self.gui.append_log(f"Requesting agent restart for '{hostname}'...")
        msg = {"action": "restart_agent"}
        self.network.send_to_client(hostname, msg)

    # --- Slave Pairing ---
    def start_pairing(self):
        self.pairing.start()

    def stop_pairing(self):
        self.pairing.stop()

    def get_pairing_status(self):
        return self.pairing.status()

    def revoke_pairing(self, hostname):
        """Deletes a slave's credential and drops its connection; it can't
        reconnect until it's paired again."""
        db.delete_slave_credential(hostname)
        self.network.close_client_connection(hostname)
        self.gui.append_log(f"PAIRING: Revoked pairing for '{hostname}'. It must be paired again to reconnect.")
        self._log_action("REVOKE_PAIRING", hostname, "")

    def get_config_content(self):
        """Reads the raw text content of the config.json file."""
        try:
            # Import the config module which already knows the correct path
            from . import config
            # Read the content from the correct config.json path
            with open(config.config_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            self.gui.append_log(f"❌ Could not read config.json: {e}")
            return f"# Error reading config.json:\n# {e}"
        
    def save_app_settings(self, config_content):
        """Saves the raw content back to the config.json file."""
        try:
            # We don't need the settings_manager anymore for saving, we can write directly.
            from . import config
            # Validate the content is well-formed JSON before writing it, since
            # config.json is what get_config_content() reads and the GUI edits.
            json.loads(config_content)
            with open(config.config_path, "w", encoding="utf-8") as f:
                f.write(config_content)

            # Reload the config module to apply settings for the current session
            importlib.reload(config)
            self.gui.append_log("✅ Configuration file saved successfully.")
            return True
        except Exception as e:
            self.gui.append_log(f"❌ Failed to save config file: {e}")
            return False

    def _attempt_ftp_upload(self, filepath, ftp_settings):
        """A helper function that performs a single FTP upload attempt."""
        host = ftp_settings.get('host')
        user = ftp_settings.get('user')
        password = ftp_settings.get('pass')

        if not all([host, user]):
            self.gui.append_log(f"FTP: Incomplete credentials for this source.")
            return False, "Incomplete credentials"

        if ftp_settings.get("is_local_path", False):
            self.gui.append_log("FTP: Path is local. Skipping redundant upload.")
            return True, "Local path, upload skipped."

        if not ftp_settings.get("enabled"):
            return True, "FTP is disabled."

        if not ftp_settings.get('secure', True):
            warning_msg = f"SECURITY WARNING: FTP transfer to {host} is unencrypted (secure=False) — installer files and credentials are sent in plaintext."
            self.gui.append_log(warning_msg)
            logging.warning(warning_msg)

        filename = os.path.basename(filepath)
        remote_path = os.path.join(ftp_settings.get("remote_dir", "/"), filename)

        try:
            use_secure = ftp_settings.get("secure", True)
            ftp_client = FTP_TLS(host) if use_secure else FTP_Client(host)

            with ftp_client as ftp:
                ftp.login(user, password)
                if use_secure:
                    ftp.prot_p()

                try:
                    if ftp.size(remote_path) == os.path.getsize(filepath):
                        self.gui.append_log(f"FTP: File '{filename}' already exists on server. Skipping.")
                        return True, "File already exists."
                except Exception:
                    pass

                self.gui.append_log(f"FTP: Uploading '{filename}' to {host}...")
                with open(filepath, "rb") as f:
                    ftp.storbinary(f"STOR {remote_path}", f)
                self.gui.append_log("FTP: Upload successful.")
                return True, "Upload successful."

        except (error_perm, OSError) as e:
            # THIS IS THE KEY CHANGE: Re-raise login and network errors
            # so the main controller function can see them and trigger the fallback.
            raise
        except Exception as e:
            # Catch other, non-recoverable errors and show a message.
            error_msg = f"FTP: Upload failed with an unexpected error: {e}"
            self.gui.append_log(f"❌ {error_msg}")
            messagebox.showerror("FTP Error", error_msg, parent=self.root)
            return False, str(e)

    def _upload_to_ftp(self, filepath):
        """
        Uploads a file to FTP with a robust fallback mechanism.
        Correctly retries on incomplete config, login errors, AND network/DNS errors.
        """
        should_fallback = False
        
        # --- Attempt 1: Using credentials from config.json ---
        self.gui.append_log("FTP Upload: Trying credentials from config.json...")
        try:
            success, msg = self._attempt_ftp_upload(filepath, FTP_CONFIG)
            if success:
                return True, msg  # Success on the first try!

            if msg == "Incomplete credentials":
                should_fallback = True  # Trigger fallback for bad config
            else:
                # Any other failure message means we stop.
                return False, msg

        except (error_perm, OSError) as e:  # <-- THIS IS THE KEY CHANGE
            # Catches both login errors (error_perm) and network/DNS errors (OSError)
            self.gui.append_log(f"FTP (config.json) failed: {e}")
            should_fallback = True  # Trigger fallback for login or network errors

        except Exception as e:
            # Catch any other unexpected error and do NOT fall back
            self.gui.append_log(f"❌ FTP (config.json) failed with a critical unexpected error: {e}")
            return False, str(e)

        # --- Fallback Attempt ---
        if should_fallback:
            self.gui.append_log("FTP: Falling back to environment variables...")
            try:
                # The result of the fallback attempt is now the final result.
                return self._attempt_ftp_upload(filepath, FTP_ENV)
            except Exception as fallback_e:
                self.gui.append_log(f"❌ FTP fallback attempt also failed critically: {fallback_e}")
                return False, str(fallback_e)
                
        return False, "FTP upload failed and no fallback was triggered."
                
    def reconnect_slave(self, hostname):
        """Sends a reconnect command and then force-closes the connection from the master side."""
        self.gui.append_log(f"[{hostname}] connection restart requested")
        # Send the command to the slave
        self.network.send_to_client(hostname, {"action": "reconnect"})
        # Immediately close the connection from our side to force a disconnect event
        self.network.close_client_connection(hostname)

    def create_group(self, group_name):
        """Controller method to create a new, persistent group."""
        try:
            db.create_group(group_name)
            self.gui.append_log(f"✅ Created new group: '{group_name}'.")
            # Trigger a refresh of the group list in the GUI
            self.gui.update_group_list()
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not create group: {e}")
            messagebox.showerror("Database Error", f"Could not create group.\n\n{e}", parent=self.root)

    def verify_catalog_files(self):
        """Checks if all installers in the catalog exist in the installers folder."""
        self.gui.append_log("Verifying integrity of software catalog files...")
        try:
            catalog_data = self._read_catalog()
            installers_dir = config.INSTALLERS_DIR
            
            missing_files = []
            for entry in catalog_data:
                filename = entry.get("filename")
                if not filename:
                    continue # Skip entries that don't have a filename
                
                expected_path = os.path.join(installers_dir, filename)
                if not os.path.exists(expected_path):
                    missing_files.append(filename)
            
            if not missing_files:
                self.gui.append_log("✅ Catalog verification successful. All files found.")
                messagebox.showinfo(
                    "Verification Complete", 
                    "All installer files listed in the catalog were found successfully.",
                    parent=self.root
                )
            else:
                self.gui.append_log(f"❌ Catalog verification found {len(missing_files)} missing file(s).")
                message = "The following installer files listed in the catalog could not be found in the 'installers' folder:\n\n" + "\n".join(f"• {f}" for f in missing_files)
                messagebox.showwarning(
                    "Missing Installer Files",
                    message,
                    parent=self.root
                )

        except Exception as e:
            self.gui.append_log(f"❌ ERROR during catalog verification: {e}")
            messagebox.showerror("Error", f"An error occurred during verification:\n{e}", parent=self.root)




    def view_master_log_file(self):
        """Reads the master log file and displays it in a popup."""
        try:
            log_path = master_logger.LOG_FILE
            if not os.path.exists(log_path):
                messagebox.showinfo("Log Not Found", "The master.log file does not exist yet.", parent=self.root)
                return

            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            content = "".join(lines[-500:]) # Get the last 500 lines
            # Reuse the existing popup, just with a different title!
            SlaveLogPopup(self.root, "Master Log", content)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read log file:\n{e}", parent=self.root)    

    def shutdown(self):
        """Cleanly shuts down the application components."""
        logging.info("Shutting down network server...")
        self.network.running = False
        # A small trick to unblock the server socket accept call
        try:
            # This is not strictly necessary on all OSes but is good practice
            dummy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dummy_socket.connect(('127.0.0.1', self.network.port))
            dummy_socket.close()
        except Exception:
            pass # Ignore errors if server is already down
        
        logging.info("Closing database connection...")
        db.close_db_connection()
        
        logging.info("Exiting.")
        self.root.destroy()

    def get_all_groups_data(self):
        """Callback to get all groups and their members from the database."""
        return db.get_all_groups()    

    def get_audit_log_data(self, search_term=None):
        """Callback to get data from the audit log, with an optional search term."""
        return db.get_audit_log(search_term=search_term)    

    def _log_action(self, action, target, detail):
        """Helper function to log an audit event with the current user."""
        user = self.current_user.get('username', 'unknown') if self.current_user else 'system'
        db.log_audit_event(user, action, target, detail)    

    def set_slave_alias(self, hostname, alias):
        """Controller method to set a slave's alias in the database."""
        try:
            db.set_slave_alias(hostname, alias)
            self.gui.append_log(f"✅ Set alias for '{hostname}' to '{alias}'.")
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not set alias: {e}")
            messagebox.showerror("Database Error", f"Could not set alias for {hostname}.\n\n{e}", parent=self.root)    

    def rename_group(self, old_name, new_name):
        """Controller method to handle renaming a group."""
        try:
            db.rename_group(old_name, new_name)
            self.gui.append_log(f"✅ Group '{old_name}' renamed to '{new_name}'.")
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not rename group: {e}")
            messagebox.showerror("Database Error", f"Could not rename group.\n\n{e}", parent=self.root)    

    def request_slave_log(self, hostname):
        """Sends a command to a slave to request its log file."""
        self.gui.append_log(f"Requesting log file from '{hostname}'...")
        msg = {"action": "get_log", "lines": 200}
        self.network.send_to_client(hostname, msg)    

    def send_file_to_hosts(self, hostnames):
        """Sends one or more files to a specific list of hosts using the hybrid model."""
        if not hostnames:
            messagebox.showwarning("No Selection", "No slaves were selected.", parent=self.root)
            return

        installer_files = self._get_installers_from_folder()
        if not installer_files:
            messagebox.showinfo("No Installers", "No files found in the 'installers' directory.", parent=self.root)
            return

        # This will now return a tuple of all selected indices
        selected_indices = self._choose_from_list(f"Select file(s) to send to {len(hostnames)} slave(s)", installer_files)
        if not selected_indices:
            return # User cancelled or selected nothing

        # Loop through each selected file
        for idx in selected_indices:
            filename = installer_files[idx]
            filepath = os.path.join(config.INSTALLERS_DIR, filename)

            # --- HYBRID FTP/DIRECT LOGIC (runs for each file) ---
            use_ftp = False
            if FTP.get("enabled") and len(hostnames) > FTP.get("threshold", 0):
                self.gui.append_log(f"FTP: Target count ({len(hostnames)}) exceeds threshold ({FTP.get('threshold', 0)}). Using FTP for file transfer.")
                success, _ = self._upload_to_ftp(filepath)
                if not success:
                    self.gui.append_log(f"❌ Skipping '{filename}' due to FTP upload failure.")
                    continue # Skip to the next file if upload fails
                use_ftp = True
            
            # --- MESSAGE CONSTRUCTION ---
            msg = {
                "action": "receive_file", 
                "filename": filename, 
                "download_method": "ftp" if use_ftp else "direct",
            }

            self.gui.append_log(f"Preparing to send file '{filename}' to {len(hostnames)} selected slave(s) (Method: {msg['download_method']})...")
            online_count = 0
            offline_count = 0

            for hostname in hostnames:
                if hostname in self.network.clients:
                    self.network.send_to_client(hostname, msg)
                    online_count += 1
                else:
                    db.queue_command(hostname, msg)
                    offline_count += 1

            if online_count > 0:
                self.gui.append_log(f"  -> Sent command to {online_count} online slave(s).")
            if offline_count > 0:
                self.gui.append_log(f"  -> Queued command for {offline_count} offline slave(s).")
                
            self._log_action("SEND_FILE", f"{len(hostnames)} hosts", filename)
    # def send_file_to_group(self, group_name):
    #     """Sends a file to all members of a group, queuing for offline slaves."""
    #     installer_files = self._get_installers_from_folder()
    #     if not installer_files:
    #         messagebox.showinfo("No Installers", "No files found in the 'installers' directory.", parent=self.root)
    #         return
            
    #     idx = self._choose_from_list(f"Select file to send to group '{group_name}'", installer_files)
    #     if idx is None:
    #         return

    #     filename = installer_files[idx]
    #     msg = {"action": "receive_file", "filename": filename}
        
    #     group_members = [r.get("hostname") for r in db.read_all("group_members") if r.get("group_name") == group_name]
    #     if not group_members:
    #         self.gui.append_log(f"Warning: No nodes found in group '{group_name}'.")
    #         return

    #     self.gui.append_log(f"Preparing to send file '{filename}' to {len(group_members)} member(s) of '{group_name}'...")
    #     online_count = 0
    #     offline_count = 0

    #     # --- NEW: Logic to handle both online and offline slaves ---
    #     for hostname in group_members:
    #         # Check if the slave is currently connected
    #         if hostname in self.network.clients:
    #             self.network.send_to_client(hostname, msg)
    #             online_count += 1
    #         else:
    #             # If offline, queue the command in the database
    #             db.queue_command(hostname, msg)
    #             offline_count += 1
        
    #     # Provide better feedback in the log
    #     if online_count > 0:
    #         self.gui.append_log(f"  -> Sent command to {online_count} online slave(s).")
    #     if offline_count > 0:
    #         self.gui.append_log(f"  -> Queued command for {offline_count} offline slave(s).")    
    def send_file_to_group(self, group_name):
        """Gets members of a group (or all nodes) and calls the send_file_to_hosts function."""
        group_members = self._get_hostnames_for_group(group_name)
        if not group_members:
            self.gui.append_log(f"Warning: No nodes found for selection '{group_name}'.")
            return
        self.send_file_to_hosts(group_members)

    def _write_catalog(self, catalog_data):
        """Writes the entire catalog data list back to the CSV file."""
        path = CATALOG.get("path")
        real_path = path
        
        # --- MODIFIED: Add the new fields to the list of columns to save ---
        fieldnames = [
            "name", "version", "filename", "silent_flags", "post_install_cmd", 
            "required_os", "required_arch",
            "pre_install_kill", "post_install_kill", "pre_uninstall_kill",
            "install_context" # <-- ADD THIS LINE
        ]
        
        sanitized_data = []
        for row in catalog_data:
            sanitized_row = {key: row.get(key, "") for key in fieldnames}
            sanitized_data.append(sanitized_row)
        
        try:
            with open(real_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(sanitized_data)
            self.gui.append_log("✅ Software catalog saved successfully.")
            return True
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not save catalog to {real_path}: {e}")
            messagebox.showerror("File Error", f"Could not save catalog:\n{e}", parent=self.root)
            return False


    def get_catalog_data(self):
        """Callback to get all data from the catalog.csv file."""
        return self._read_catalog()

    def save_catalog_data(self, catalog_data):
        """Callback to save new data to the catalog.csv file."""
        return self._write_catalog(catalog_data)    

    def get_hosts_with_software(self, software_filename):
        """Controller method to fetch hosts with a specific software from the DB."""
        return db.get_hosts_with_software(software_filename)

    def retry_deployment(self, hostname, software_filename):
        """Finds an installer by its filename and re-deploys it to a specific host."""
        self.gui.append_log(f"Retrying deployment of '{software_filename}' to '{hostname}'...")

        installers_dir = config.INSTALLERS_DIR
        filepath = os.path.join(installers_dir, software_filename)

        if os.path.exists(filepath):
            # --- THIS IS THE FIX: Pass [hostname] as a list ---
            self.deploy_file_to_host([hostname], filepath)
        else:
            error_msg = f"Retry failed: Installer file '{software_filename}' not found on master."
            self.gui.append_log(f"❌ {error_msg}")
            messagebox.showerror("File Not Found", error_msg, parent=self.root)   

    def get_offline_slave_count(self):
        """Calculates the number of known slaves that are not currently connected."""
        all_slaves = db.read_all("slaves")
        online_hosts = self.network.clients.keys()
        offline_count = len([s for s in all_slaves if s.get("hostname") not in online_hosts])
        return offline_count    

    def remove_from_group(self, hostname, group_name):
        """Removes a host from a group and updates the GUI."""
        db.remove_group_member(group_name, hostname)
        self.gui.remove_node_from_group(hostname, group_name)
        self.gui.append_log(f"Removed '{hostname}' from group '{group_name}'")

    def get_all_slave_statuses(self):
        """Fetches the consolidated slave status report from the database."""
        return db.get_all_slave_statuses()

    def get_dashboard_stats(self):
        """Fetches the data the Dashboard tab needs: today's deployment count
        and the all-time Success/Failed/Skipped breakdown."""
        return {
            "deployments_today": db.get_deployments_today_count(),
            "status_summary": db.get_deployment_status_summary(),
        }

    def handle_slave_log(self, hostname, log_data):
        """Handles a log message received from a slave."""
        level = log_data.get('level', 'INFO')
        message = log_data.get('message', '')
        db.add_slave_log(hostname, level, message)
        # Also append it to the live logs for visibility
        self.gui.append_log(f"LOG from {hostname} [{level}]: {message}")

    def _load_all_known_slaves(self):
        """Loads all previously seen slaves from the database to populate the GUI."""
        logging.info("Loading all known slaves from database...")
        all_slaves = db.read_all("slaves")
        for slave in all_slaves:
            hostname = slave.get("hostname")
            if not hostname:
                continue
            
            # If the slave is not in the list of currently connected clients, mark it as offline
            if hostname not in self.network.clients:
                groups = ",".join([r.get("group_name") for r in db.read_all("group_members") if r.get("hostname")==hostname])
                self.gui.add_or_update_slave(hostname, slave.get("ip", ""), "offline", groups)
                logging.info(f"  - Loaded offline slave: {hostname}")

    def _dispatch_queued_commands(self, hostname):
        """Checks for and sends any pending commands for a newly connected host."""
        pending_commands = db.get_pending_commands(hostname)
        if not pending_commands:
            return

        self.gui.append_log(f"NOTE: Found {len(pending_commands)} pending command(s) for {hostname}. Dispatching now...")
        for cmd in pending_commands:
            try:
                command_id = cmd['id']
                command_dict = json.loads(cmd['command_json'])
                
                # Send the command to the now-online slave
                self.network.send_to_client(hostname, command_dict)
                
                # Update the command's status in the database to prevent re-sending
                db.update_command_status(command_id, "dispatched")
                
                self.gui.append_log(f"  -> Dispatched queued install for '{command_dict.get('filename')}'")
            except Exception as e:
                print(f"Failed to dispatch queued command {cmd.get('id')}: {e}")


    def get_installable_catalog_software(self):
        """
        Returns a list of software names from the catalog for which an installer
        file actually exists in the installers folder.
        """
        try:
            catalog_items = self._read_catalog()
            installer_filenames = self._get_installers_from_folder()
            
            installable_software_names = []
            for item in catalog_items:
                if item.get("name") and item.get("filename") in installer_filenames:
                    installable_software_names.append(item["name"])
            
            return sorted(list(set(installable_software_names)))
        except Exception as e:
            print(f"Error getting installable software: {e}")
            return []

    def get_catalog_software_names(self):
        """Returns a list of all software names from the catalog."""
        try:
            return [row['name'] for row in self._read_catalog() if row.get('name')]
        except Exception as e:
            print(f"Could not read catalog names: {e}")
            return []

    def _get_installers_from_folder(self):
        """Scans the installers folder and returns a list of ALL files."""
        try:
            installers_dir = config.INSTALLERS_DIR
            if not os.path.exists(installers_dir):
                messagebox.showerror("Directory Not Found", "The 'installers' directory does not exist.", parent=self.root)
                return []
            
            all_items = os.listdir(installers_dir)
            
            # --- THIS IS THE MODIFIED LOGIC ---
            # It now returns all items that are files, ignoring any sub-folders.
            all_files = [f for f in all_items if os.path.isfile(os.path.join(installers_dir, f))]
            return all_files
            # --- END OF MODIFICATION ---

        except Exception as e:
            messagebox.showerror("Error", f"Could not read installers directory: {e}", parent=self.root)
            return []

    def bulk_uninstall_from_group(self, group_name, software_name):
        """Sends an uninstall command to all members of a group or to all nodes."""
        self.gui.append_log(f"Initiating bulk uninstall of '{software_name}' for '{group_name}'...")
        group_members = self._get_hostnames_for_group(group_name)
        if not group_members:
            self.gui.append_log(f"Warning: No nodes found for selection '{group_name}'.")
            return
        for hostname in group_members:
            self.uninstall_on_host(hostname, software_name)

    def schedule_install(self, hostnames):
        """Schedules one or more software deployments for a list of hosts."""
        if not hostnames:
            return

        installer_files = self._get_installers_from_folder()
        if not installer_files:
            messagebox.showinfo("No Installers", "The 'installers' folder is empty.", parent=self.root)
            return

        selected_indices = self._choose_from_list(f"Select Installer(s) to Schedule for {len(hostnames)} hosts", installer_files)
        if not selected_indices:
            return # User cancelled

        # Get the scheduled time ONCE for the whole batch
        time_dialog = ScheduleTimeDialog(self.root)
        timestamp = time_dialog.show()

        if not timestamp:
            return # User cancelled the time selection

        readable_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
        
        # Loop through each selected file
        for idx in selected_indices:
            filename = installer_files[idx]
            filepath = os.path.join(config.INSTALLERS_DIR, filename)
            digest = sha256_file(filepath)
            
            # Add a separate scheduled job for each host and each file
            for host in hostnames:
                self.scheduled.append((timestamp, host, filepath, digest))
                self.gui.append_log(f"✅ Scheduled install of '{filename}' for {host} at {readable_time}")
                
        self._log_action("SCHEDULE_INSTALL", f"{len(hostnames)} hosts", f"{len(selected_indices)} file(s) at {readable_time}")             

    def _normalize_inventory(self, info):
        """
        Ensure inventory is a dict with sensible keys.
        - if info is already a dict => return it.
        - if info is a list, try to convert:
            * if list looks like installed_software (dicts with 'name') -> {'installed_software': list}
            * if list looks like [{'category':..., 'details':...}, ...] -> reconstruct dict
            * otherwise fallback to {'installed_software': info}
        """
        if isinstance(info, dict):
            return info

        if isinstance(info, list):
            # case A: list of software dicts (each has 'name')
            if all(isinstance(i, dict) and 'name' in i for i in info):
                return {'installed_software': info}

            # case B: list of category/details pairs
            reconstructed = {}
            try:
                for item in info:
                    if not isinstance(item, dict):
                        continue
                    cat = item.get('category') or item.get('type')
                    details = item.get('details')
                    if cat and details is not None:
                        reconstructed[cat] = details
                    else:
                        # fall back: if dict has typical keys of os_info etc, merge it
                        for key in ('os_info','cpu_info','ram_info','disk_info','network_info','installed_software'):
                            if key in item:
                                reconstructed.update(item)
                                break
                if reconstructed:
                    return reconstructed
            except Exception:
                pass

            # fallback: treat entire list as installed_software
            return {'installed_software': info}

        # completely unexpected type -> put it under installed_software fallback
        return {'installed_software': []}


    def _load_persisted_inventory(self):
        """Pre-populates the GUI's cache with the latest inventory from the database."""
        print("Loading persisted inventory from disk...")
        latest_inventory = {}
        
        # Corrected to use 'db.read_all' and the correct 'inventory' table
        for record in db.read_all("inventory"):
            hostname = record.get("hostname")
            if not hostname:
                continue
            # Logic to find the most recent inventory record for each host
            if hostname not in latest_inventory or record.get("timestamp") > latest_inventory[hostname].get("timestamp"):
                latest_inventory[hostname] = record
        
        # Now, load the latest records into the GUI cache
        for hostname, record in latest_inventory.items():
            try:
                # Corrected to read from the 'info_json' column in the database
                info_dict = json.loads(record.get("info_json", "{}"))
                self.gui.update_inventory(hostname, info_dict)
                print(f"  - Loaded inventory for {hostname}")
            except json.JSONDecodeError:
                print(f"  - Failed to load corrupt inventory for {hostname}")


    def _process_gui_queue(self):
        try:
            while not self.gui_queue.empty():
                message = self.gui_queue.get_nowait()
                msg_type = message[0]
                
                if msg_type == "slave_connected":
                    _, hostname, ip = message
                    self._handle_slave_connected(hostname, ip)
                
                elif msg_type == "slave_disconnected":
                    _, hostname = message
                    self._handle_slave_disconnected(hostname)

                elif msg_type == "pairing_event":
                    _, text = message
                    self.gui.append_log(f"PAIRING: {text}")
                    self._log_action("PAIRING", "-", text)
                
                elif msg_type == "inventory_received":
                    _, hostname, info = message
                    self._handle_inventory_received(hostname, info)

                elif msg_type == "config_content_received":
                    _, hostname, content = message
                    # This now correctly calls the GUI to show the editor
                    self.gui.show_config_editor(f"Slave Config - {hostname}", content, hostname)
                
                elif msg_type == "log_content_received":
                    _, hostname, data = message
                    self.gui.show_slave_log_popup(hostname, data)

                elif msg_type == "slave_log_received":
                    _, hostname, data = message
                    self.handle_slave_log(hostname, data)
                
                elif msg_type == "status_received":
                    _, hostname, msg = message
                    # Safely get the status from the message dictionary
                    status = msg.get("status")

                    if status == "config_saved":
                        if messagebox.askyesno("Save Successful", f"Configuration for '{hostname}' was saved successfully.\n\nDo you want to restart the slave agent now to apply the changes?", parent=self.root):
                            self.restart_slave_agent(hostname)

                    elif status == "slave_log":
                        self.handle_slave_log(hostname, msg.get("data", {}))

                    elif status == "screenshot_data":
                        self._handle_screenshot_data(hostname, msg)

                    elif status == "command_output":
                        self._handle_command_output(hostname, msg)

                    else:
                        # Handle all other general statuses
                        self._handle_status_received(hostname, msg)

        finally:
            self.root.after(100, self._process_gui_queue)
    # New function to make the host click only once rather then multiple times
    def deploy_to_selected_nodes(self, hostnames):
        """Deploys one or more software packages chosen from the installers folder to selected nodes."""
        if not hostnames:
            return

        installer_files = self._get_installers_from_folder()
        if not installer_files:
            messagebox.showinfo("No Installers", "No installer files found in the 'installers' directory.", parent=self.root)
            return
        
        selected_indices = self._choose_from_list(f"Select installer(s) for {len(hostnames)} nodes", installer_files)
        if not selected_indices:
            return

        # Only worth a summary popup for more than two apps at once -- for
        # one or two, the existing per-item success/failure toasts (shown in
        # _handle_status_received) are enough and a popup would just be one
        # more thing to dismiss.
        if len(selected_indices) > 2:
            self._install_batch_seq += 1
            batch_id = self._install_batch_seq
            catalog = self._read_catalog()
            catalog_by_filename = {row.get("filename"): row for row in catalog if row.get("filename")}
            items = []
            for idx in selected_indices:
                filename = installer_files[idx]
                friendly_name = catalog_by_filename.get(filename, {}).get("name", filename)
                for hostname in hostnames:
                    items.append({
                        "hostname": hostname,
                        "filename": filename,
                        "friendly_name": friendly_name,
                        "status": "Queued",
                    })
            self._active_install_batches[batch_id] = items
            self.gui.open_install_batch_popup(batch_id, items)

        # Loop through each selected file and deploy it
        for idx in selected_indices:
            filename = installer_files[idx]
            fp = os.path.join(config.INSTALLERS_DIR, filename)
            self.gui.append_log(f"Queueing install of '{filename}' for {len(hostnames)} node(s)...")
            self.deploy_file_to_host(hostnames, fp)

    # ==================== Policy Management ====================
    def create_policy(self, name):
        name = (name or "").strip()
        if not name:
            return
        try:
            db.create_policy(name)
            self.gui.append_log(f"✅ Created policy '{name}'.")
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not create policy: {e}")
            messagebox.showerror("Database Error", f"Could not create policy.\n\n{e}", parent=self.root)

    def get_all_policies(self):
        return db.get_policies()

    def delete_policy(self, policy_id):
        try:
            db.delete_policy(policy_id)
            self.gui.append_log(f"Deleted policy id {policy_id} (and its rules/group assignments).")
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not delete policy: {e}")
            messagebox.showerror("Database Error", f"Could not delete policy.\n\n{e}", parent=self.root)

    def rename_policy(self, policy_id, new_name):
        try:
            db.rename_policy(policy_id, new_name)
            self.gui.append_log(f"Renamed policy id {policy_id} to '{new_name}'.")
        except ValueError as e:
            messagebox.showerror("Error", str(e), parent=self.root)
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not rename policy: {e}")
            messagebox.showerror("Database Error", f"Could not rename policy.\n\n{e}", parent=self.root)

    def assign_policy_to_group(self, group_name, policy_id):
        try:
            db.assign_policy_to_group(group_name, policy_id)
            self.gui.append_log(f"Assigned policy id {policy_id} to group '{group_name}'.")
            self.gui.update_group_list()
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not assign policy: {e}")
            messagebox.showerror("Database Error", f"Could not assign policy.\n\n{e}", parent=self.root)

    def get_policy_rules(self, policy_id):
        return db.get_policy_rules(policy_id)

    def add_rule_to_policy(self, policy_id, rule_details: dict):
        """rule_details: {'rule_type': 'Must Have'|'Must Not Have', 'software_name': ..., 'version': ...}"""
        rule_type_map = {"Must Have": "must_have", "Must Not Have": "must_not_have"}
        rule_type = rule_type_map.get(rule_details.get("rule_type"), rule_details.get("rule_type"))
        software_name = rule_details.get("software_name")
        version = rule_details.get("version") or None

        if not software_name:
            messagebox.showwarning("Input Required", "A software name is required for the rule.", parent=self.root)
            return

        try:
            db.add_rule_to_policy(policy_id, rule_type, software_name, version)
            self.gui.append_log(f"Added rule '{rule_type}: {software_name}' to policy id {policy_id}.")
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not add rule: {e}")
            messagebox.showerror("Database Error", f"Could not add rule.\n\n{e}", parent=self.root)

    def remove_rule_from_policy(self, rule_id):
        try:
            db.remove_rule_from_policy(rule_id)
            self.gui.append_log(f"Removed policy rule id {rule_id}.")
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not remove rule: {e}")

    def set_policy_auto_check(self, policy_id, enabled):
        db.set_policy_auto_check(policy_id, enabled)
        self.gui.append_log(f"Policy id {policy_id} auto-check set to {bool(enabled)}.")

    def remove_policy_from_group(self, group_name):
        db.remove_policy_from_group(group_name)
        self.gui.append_log(f"Removed policy assignment from group '{group_name}'.")
        self.gui.update_group_list()

    def get_group_assignments(self):
        return db.get_group_assignments()

    def set_compliance_engine_state(self, enabled):
        self.compliance_engine_enabled = bool(enabled)
        db.set_setting('compliance_engine_enabled', self.compliance_engine_enabled)
        self.gui.append_log(f"Compliance engine {'enabled' if self.compliance_engine_enabled else 'disabled'}.")

    def trigger_manual_compliance_check(self):
        """Runs the compliance check in a background thread so the GUI doesn't block."""
        threading.Thread(target=self._run_compliance_check, kwargs={"trigger_source": "Manual"}, daemon=True).start()

    def _run_compliance_check(self, trigger_source="Manual"):
        """The core compliance-check engine: for every hostname+rule currently
        in effect (db.get_all_group_policy_rules), compares the host's latest
        inventory against the rule and auto-deploys/auto-uninstalls as needed.

        policy_rules.software_name actually stores a catalog FILENAME (set that
        way by AddRuleDialog), which is cross-referenced against the catalog
        via self._read_catalog() to get the friendly display name used to
        check installed_software and to call uninstall_on_host.
        """
        if not self.compliance_engine_enabled:
            self.gui.append_log(f"POLICY: Compliance check ({trigger_source}) skipped - compliance engine is disabled.")
            return

        self.gui.append_log(f"POLICY: Starting compliance check (trigger: {trigger_source})...")
        try:
            rules = db.get_all_group_policy_rules()
        except Exception as e:
            self.gui.append_log(f"❌ POLICY: Could not load policy rules: {e}")
            return

        if not rules:
            self.gui.append_log("POLICY: No policy rules currently in effect.")
            return

        catalog = self._read_catalog()
        catalog_by_filename = {row.get("filename"): row for row in catalog if row.get("filename")}

        actions_taken = 0
        for rule in rules:
            hostname = rule.get("hostname")

            # For unattended triggers, respect each policy's own auto-check flag.
            # A manual "Run Compliance Check Now" always runs every rule.
            if trigger_source in ("Automatic Startup", "Scheduled") and not rule.get("auto_check_enabled"):
                continue

            inventory = db.get_latest_inventory(hostname)
            installed_names = set()
            if inventory and isinstance(inventory.get("installed_software"), list):
                for app in inventory["installed_software"]:
                    if isinstance(app, dict) and app.get("name"):
                        installed_names.add(app["name"])

            software_filename = rule.get("software_name")
            catalog_entry = catalog_by_filename.get(software_filename)
            friendly_name = catalog_entry.get("name") if catalog_entry else software_filename
            is_installed = friendly_name in installed_names
            rule_type = rule.get("rule_type")

            if rule_type == "must_have" and not is_installed:
                if not catalog_entry:
                    self.gui.append_log(f"POLICY: Cannot enforce 'must have {software_filename}' on {hostname} - not found in catalog.")
                    continue
                filepath = os.path.join(config.INSTALLERS_DIR, catalog_entry.get("filename"))
                if not os.path.exists(filepath):
                    self.gui.append_log(f"POLICY: Cannot deploy '{friendly_name}' to {hostname} - installer file missing.")
                    continue
                self.gui.append_log(f"POLICY: {hostname} is missing required software '{friendly_name}' - deploying...")
                self.deploy_file_to_host([hostname], filepath)
                actions_taken += 1

            elif rule_type == "must_not_have" and is_installed:
                self.gui.append_log(f"POLICY: {hostname} has disallowed software '{friendly_name}' - uninstalling...")
                self.uninstall_on_host(hostname, friendly_name)
                actions_taken += 1

        self.gui.append_log(f"POLICY: Compliance check ({trigger_source}) complete. {actions_taken} action(s) taken.")

    def show_compliance_report(self):
        """Builds a READ-ONLY compliance report (no deploy/uninstall actions)
        by cross-referencing every group's assigned policy rules against the
        latest inventory, then hands it to the GUI to display."""
        try:
            assignments = db.get_group_assignments()
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not load group assignments for report: {e}")
            return

        catalog = self._read_catalog()
        catalog_by_filename = {row.get("filename"): row for row in catalog if row.get("filename")}

        report_data = []
        for assignment in assignments:
            group_name = assignment["group_name"]
            policy_id = assignment["policy_id"]
            rules = db.get_policy_rules(policy_id)
            members = self._get_hostnames_for_group(group_name)

            for hostname in members:
                inventory = db.get_latest_inventory(hostname)
                installed_names = set()
                if inventory and isinstance(inventory.get("installed_software"), list):
                    for app in inventory["installed_software"]:
                        if isinstance(app, dict) and app.get("name"):
                            installed_names.add(app["name"])

                for rule in rules:
                    software_filename = rule.get("software_name")
                    catalog_entry = catalog_by_filename.get(software_filename)
                    friendly_name = catalog_entry.get("name") if catalog_entry else software_filename
                    is_installed = friendly_name in installed_names
                    rule_type = rule.get("rule_type")

                    if rule_type == "must_have":
                        required = f"Must Have: {friendly_name}"
                        status = "OK" if is_installed else "Missing"
                    else:
                        required = f"Must Not Have: {friendly_name}"
                        status = "Violation" if is_installed else "OK"

                    report_data.append({
                        "hostname": hostname,
                        "software": friendly_name,
                        "required": required,
                        "installed": "Yes" if is_installed else "No",
                        "status": status,
                    })

        self.gui.show_compliance_report(report_data)

    def save_report_to_csv(self, report_data, filepath):
        try:
            fieldnames = ["hostname", "software", "required", "installed", "status"]
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(report_data)
            self.gui.append_log(f"✅ Compliance report saved to {filepath}.")
            return True
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not save report: {e}")
            messagebox.showerror("File Error", f"Could not save report:\n{e}", parent=self.root)
            return False

    def _handle_slave_connected(self, hostname, ip):
        """Handles a new slave connection, writes to DB, then tells GUI to update."""
        self.slave_connection_times[hostname] = time.time()
        try:
            db.update_slave_status(hostname, ip, datetime.now(timezone.utc).isoformat())
        except Exception as e:
            print(f"CRITICAL: Failed to update slave status in database: {e}")
            self.gui.append_log(f"❌ DATABASE ERROR: Could not save status for {hostname}.")
        
        self.gui._update_node_list()
        
        self.gui.append_log(f"[{hostname}] connected from {ip}")
        # --- MODIFIED: Show a toast notification ---
        self.gui.show_toast("Slave Connected", f"{hostname} ({ip})", "success")
        self._dispatch_queued_commands(hostname)

    def _handle_slave_disconnected(self, hostname):
        """Handles a slave disconnection and tells the GUI to refresh."""
        self.gui._update_node_list()

        self.gui.append_log(f"[{hostname}] disconnected")
        self.gui.show_toast("Slave Disconnected", hostname, "error")

        # --- NEW LOGIC FOR QUICK DISCONNECT ---
        QUICK_DISCONNECT_THRESHOLD = 5 # 5 seconds

        if hostname in self.slave_connection_times:
            connect_time = self.slave_connection_times.pop(hostname) # Get time and remove entry
            duration = time.time() - connect_time
            
            if duration < QUICK_DISCONNECT_THRESHOLD:
                title = "Slave Handshake Failure"
                message = (
                    f"The slave '{hostname}' disconnected immediately after connecting.\n\n"
                    "This is usually caused by a configuration mismatch on the slave machine. Please check:\n\n"
                    "1. Pairing: the slave may not be paired with this master, or its pairing was revoked. Open a pairing window and re-run the slave installer with the code.\n\n"
                    "2. Service Account: Ensure the slave's Windows Service 'Log On As' user has the correct password and permissions."
                )
                # Schedule the messagebox to run safely on the main GUI thread
                self.root.after(100, lambda: messagebox.showerror(title, message, parent=self.root))
        # --- END OF NEW LOGIC ---
        

    # def _handle_inventory_received(self, hostname, info):
    #     """Called when inventory is received. Normalize and pass a dict to the GUI."""
    #     # Normalize incoming payload (handles dict OR list payloads)
    #     info = self._normalize_inventory(info)

    #     # Save in-memory
    #     self.last_inventories[hostname] = info

    #     # Debug log (optional, helpful)
    #     try:
    #         self.gui.append_log(f"[{hostname}] RECEIVED inventory (type={type(info).__name__})")
    #     except Exception:
    #         pass

    #     # Update GUI
    #     try:
    #         self.gui.update_inventory(hostname, info)
    #     except Exception as e:
    #         # keep app alive and log error to GUI
    #         print("Error updating inventory GUI:", e)
    #         try:
    #             self.gui.append_log(f"Error updating inventory GUI for {hostname}: {e}")
    #         except Exception:
    #             pass

    #     # Summary log
    #     count = len(info.get('installed_software', [])) if isinstance(info.get('installed_software', []), list) else 0
    #     try:
    #         self.gui.append_log(f"[{hostname}] inventory: {count} items")
    #     except Exception:
    #         pass

    #     # Auto-update check (if you still use it)
    #     try:
    #         self._maybe_auto_update(hostname, info)
    #     except Exception:
    #         pass
    def _handle_inventory_received(self, hostname, info):
        """Called when inventory is received. Normalize and update the latest state."""
        info = self._normalize_inventory(info)
        self.last_inventories[hostname] = info

        self.gui.append_log(f"[{hostname}] RECEIVED inventory")
        
        # --- MODIFIED: Call the new, optimized database function ---
        try:
            db.update_latest_inventory(hostname, datetime.now(timezone.utc).isoformat(), json.dumps(info))
        except Exception as e:
            self.gui.append_log(f"❌ DATABASE ERROR: Could not update inventory for {hostname}: {e}")
        # --- END OF MODIFICATION ---

        self.gui.update_inventory(hostname, info)
        
        count = len(info.get('installed_software', [])) if isinstance(info.get('installed_software', []), list) else 0
        self.gui.append_log(f"[{hostname}] inventory: {count} items")

        try:
            self._maybe_auto_update(hostname, info)
        except Exception:
            pass


    def _handle_screenshot_data(self, hostname, msg):
        """Routes an incoming base64-JPEG screenshot to either the single-host
        popup or the multi-host group results window, depending on whether this
        hostname is part of an in-flight group screenshot batch."""
        data = msg.get("data")
        group_name = self._current_screenshot_request.pop(hostname, None)

        if not data:
            self.gui.append_log(f"[{hostname}] screenshot request failed: no image data received.")
            return

        if group_name:
            self.gui.update_group_screenshot(group_name, hostname, data)
        else:
            self.gui.show_screenshot(hostname, data)

    def _handle_command_output(self, hostname, msg):
        """Routes a 'command_output' status (from either run_command or
        run_script_file) to whichever CommandResultsPopup is currently open
        for that hostname; the GUI falls back to a log line if none is open."""
        data = msg.get("data", {}) or {}
        command = msg.get("command", "")
        self.gui.append_command_output(hostname, command, data)

    def _handle_status_received(self, hostname, msg):
        """Handles status updates from the slave and logs final outcomes to the database."""
        self.gui.handle_status_event(hostname, msg)
        
        status = msg.get("status", "")
        status_lower = status.lower()

        if "success" in status_lower or "failed" in status_lower or "skipped" in status_lower:
            db.log_deployment({
                "hostname": hostname,
                "software": msg.get("software", ""),
                "status": status,
                "detail": msg.get("message", ""),
                "progress": 100,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            # --- NEW: Show a toast notification on success or failure ---
            software_name = msg.get("software", "A task")
            if "success" in status_lower:
                self.gui.show_toast("Deployment Success", f"'{software_name}' on {hostname}.", "success")
            elif "fail" in status_lower:
                self.gui.show_toast("Deployment Failed", f"'{software_name}' on {hostname}.", "error")

            self._update_install_batches(hostname, software_name, status_lower)

        if status in ("install_fail", "hash_mismatch", "download_fail"):
            attempts = self._count_attempts(hostname, msg.get("software", ""))
            if attempts < RETRY.get("install_attempts", 1):
                self.gui.append_log(f"[{hostname}] retrying {msg.get('software','')} (attempt {attempts+1})")
                fp = os.path.join(config.INSTALLERS_DIR, msg.get("software", ""))
                if os.path.exists(fp):
                    self.deploy_file_to_host([hostname], fp)
                else:
                    self.gui.append_log(f"[{hostname}] retry failed: installer '{msg.get('software','')}' not found.")
            else:
                messagebox.showwarning("Install failed", f"{hostname}: {msg.get('software','')} failed; retries exhausted")

    def _update_install_batches(self, hostname, software_name, status_lower):
        """Marks the matching (hostname, app) row as done in any active
        install batch (see deploy_to_selected_nodes), and drops the batch
        once every row in it has reached a final status -- the popup itself
        stays open for the admin to review/close.

        software_name must be msg.get("software") as sent back by the slave,
        which is the FRIENDLY NAME the master originally sent it (catalog
        "name" if set, else the raw filename) -- not necessarily the raw
        filename -- so batch items are matched on "friendly_name", the same
        value deploy_to_selected_nodes computed when building the batch.
        """
        if not software_name or not self._active_install_batches:
            return

        if "success" in status_lower:
            display_status = "Success"
        elif "skipped" in status_lower:
            display_status = "Skipped"
        else:
            display_status = "Failed"

        for batch_id, items in list(self._active_install_batches.items()):
            matched = False
            for item in items:
                if item["hostname"] == hostname and item["friendly_name"] == software_name and item["status"] == "Queued":
                    item["status"] = display_status
                    matched = True
                    break
            if matched:
                self.gui.update_install_batch_item(batch_id, hostname, software_name, display_status)
                if all(item["status"] != "Queued" for item in items):
                    del self._active_install_batches[batch_id]

    def _ensure_file_in_installers_dir(self, filepath):
        """Copies filepath into config.INSTALLERS_DIR if it isn't already
        there, so the master's own file server (networking.py's
        _handle_file_conn, which only ever serves files that physically
        exist inside INSTALLERS_DIR) can actually find it when a slave
        requests a direct download.

        Without this, picking a file from anywhere else via a file browser
        (Install from Folder, Send & Extract ZIP) silently fails -- the
        slave gets nothing but a "master did not send file header" /
        "Failed to download" error, since the server can't locate a file
        that was never copied there. Returns the path to use from here on.
        """
        target_path = os.path.join(config.INSTALLERS_DIR, os.path.basename(filepath))
        if os.path.abspath(filepath) == os.path.abspath(target_path):
            return filepath
        try:
            os.makedirs(config.INSTALLERS_DIR, exist_ok=True)
            shutil.copy2(filepath, target_path)
            self.gui.append_log(f"Copied '{os.path.basename(filepath)}' into the installers folder for distribution.")
        except Exception as e:
            self.gui.append_log(f"⚠️ Could not copy '{os.path.basename(filepath)}' into the installers folder: {e}")
        return target_path

    def deploy_file_to_host(self, hostnames, filepath, post_install_cmd="", silent_flags=""):
        """
        Deploys a file to a list of hosts using the hybrid model.
        Uses direct send for small batches and FTP for large batches.
        """
        filename = os.path.basename(filepath)

        # --- HYBRID LOGIC ---
        use_ftp = False
        if FTP.get("enabled") and len(hostnames) > FTP.get("threshold", 0):
            self.gui.append_log(f"FTP: Target count ({len(hostnames)}) exceeds threshold ({FTP.get('threshold', 0)}). Using FTP.")
            # Attempt to upload the file to the FTP server
            success, message = self._upload_to_ftp(filepath)
            if not success:
                # If the upload fails, we stop the deployment.
                return
            use_ftp = True
        else:
            # Direct transfer relies on the master's own file server, which
            # only serves files physically inside INSTALLERS_DIR.
            filepath = self._ensure_file_in_installers_dir(filepath)
        # --- END OF HYBRID LOGIC ---

        # The rest of the logic prepares the command for the slave
        catalog = self._read_catalog()
        catalog_entry = next((item for item in catalog if item.get('filename') == filename), {})
        # self.gui.append_log(f"DEBUG: Catalog entry found for {filename}: {catalog_entry}")
        
        # ... (This part is the same as before)
        if not post_install_cmd:
            post_install_cmd = catalog_entry.get("post_install_cmd", "")
        if not silent_flags:
            silent_flags = catalog_entry.get("silent_flags", "")

        friendly_name = catalog_entry.get('name', filename)
        version = catalog_entry.get('version', '0')
        digest = sha256_file(filepath)

        # Create the base message
        msg = {
            "action": "install", 
            "filename": filename, 
            "sha256": digest, 
            "post_install_cmd": post_install_cmd, 
            "silent_flags": silent_flags, 
            "friendly_name": friendly_name, 
            "version": version,
            "required_os": catalog_entry.get("required_os", "").strip(),
            "required_arch": catalog_entry.get("required_arch", "").strip(),
            "pre_install_kill": catalog_entry.get("pre_install_kill", ""),
            "post_install_kill": catalog_entry.get("post_install_kill", ""),

            # --- ADD THIS LINE ---
            # Default to "system" if the field is blank, ensuring full backward compatibility.
            "install_context": catalog_entry.get("install_context", "").lower() or "system"
        }

        # Add the download method to the message
        if use_ftp:
            msg["download_method"] = "ftp"
        else:
            msg["download_method"] = "direct"

        # Send the command to host
        for hostname in hostnames:
            if hostname in self.network.clients:
                self.network.send_to_client(hostname, msg)
                log_status = "queued"
            else:
                db.queue_command(hostname, msg)
                log_status = "queued_offline"
            
            self.gui.append_log(f"[{hostname}] {log_status} install of {filename} (Method: {msg['download_method']})")
        
        # The post-install command runs through the slave's shell, so record it.
        detail = f"{filename} | post-install command: {post_install_cmd}" if post_install_cmd else filename
        self._log_action("DEPLOY_SOFTWARE", ", ".join(hostnames), detail)

    def deploy_from_catalog_to_selected(self, hostname):
        """
        Scans the 'installers' folder and presents a list of files to deploy.
        This REPLACES the old catalog CSV functionality.
        """
        try:
            # 1. Define the path to the installers directory
            installers_dir = config.INSTALLERS_DIR

            if not os.path.exists(installers_dir):
                messagebox.showerror("Error", f"The installers directory does not exist at:\n{installers_dir}")
                return

            # 2. Scan the directory and filter for common installer types
            all_files = os.listdir(installers_dir)
            installer_files = [f for f in all_files if f.lower().endswith(('.exe', '.msi', '.pkg', '.deb', '.rpm'))]

            # 3. Handle case where no installers are found
            if not installer_files:
                messagebox.showinfo("No Installers Found", 
                                    "The 'installers' folder is empty or contains no supported files (.exe, .msi, etc).", 
                                    parent=self.root)
                return

            # 4. Display the list and get the user's choice
            selected_index = self._choose_from_list("Select Installer from Folder", installer_files)

            # 5. If a selection was made, get the full path and deploy the file
            if selected_index is not None:
                filename_to_deploy = installer_files[selected_index]
                full_filepath = os.path.join(installers_dir, filename_to_deploy)

                # Use the existing function to send the file to the slave
                self.deploy_file_to_host([hostname], full_filepath)

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
            print(f"Error in deploy_from_catalog_to_selected: {e}")


    def delete_group_from_storage(self, group_name):
        """Removes a group from the persistent database."""
        db.delete_group(group_name) # Use the new DB function        

    def uninstall_on_host(self, hostname, software_name):
        # --- NEW: Read catalog to find matching uninstall logic ---
        catalog = self._read_catalog()
        catalog_entry = next((item for item in catalog if item.get('name') == software_name), {})
        pre_kill_list_json = catalog_entry.get("pre_uninstall_kill", "") # Get the new data
        # --- END NEW ---

        # Build the complete command message
        msg = {
            "action": "uninstall",
            "name": software_name,
            "pre_uninstall_kill": pre_kill_list_json, # Add the data to the command
        }
        
        self.network.send_to_client(hostname, msg)
        self.gui.append_log(f"[{hostname}] uninstall requested for {software_name}")
        self._log_action("UNINSTALL_SOFTWARE", hostname, software_name)

    def request_inventory(self, hostname):
        self.network.send_to_client(hostname, {"action":"get_inventory"})
        self.gui.append_log(f"[{hostname}] inventory requested")

    def disconnect_slave(self, hostname):
        self.network.send_to_client(hostname, {"action":"shutdown"})
        self.gui.append_log(f"[{hostname}] shutdown requested")

    # --- Power Control ---
    def _send_system_command(self, targets, action):
        """Shared fan-out helper for system power commands (shutdown/restart/sleep).

        Only sent to currently-online targets. Unlike installer deployment,
        power commands are NOT queued for offline hosts via db.queue_command:
        a queued shutdown/restart/sleep could fire unexpectedly whenever that
        slave happens to reconnect later, which would be surprising and
        potentially disruptive. Offline targets are simply skipped and logged.
        """
        if not targets:
            return
        msg = {"action": action}
        online_count = 0
        offline_count = 0
        for hostname in targets:
            if hostname in self.network.clients:
                self.network.send_to_client(hostname, msg)
                online_count += 1
            else:
                offline_count += 1

        if online_count:
            self.gui.append_log(f"Sent '{action}' command to {online_count} online node(s).")
        if offline_count:
            self.gui.append_log(f"Skipped {offline_count} offline node(s) for '{action}' (not queued).")

        self._log_action(action.upper(), f"{len(targets)} hosts", f"{online_count} sent, {offline_count} skipped")

    def system_shutdown(self, targets):
        """Shuts down every target host, after a single confirmation naming the count."""
        if not targets:
            return
        if not messagebox.askyesno(
            "Confirm Shutdown",
            f"Are you sure you want to SHUT DOWN {len(targets)} target(s)?\n\n"
            "This is destructive and cannot be undone remotely.",
            parent=self.root,
        ):
            return
        self._send_system_command(targets, "system_shutdown")

    def system_restart(self, targets):
        """Restarts every target host, after a single confirmation naming the count."""
        if not targets:
            return
        if not messagebox.askyesno(
            "Confirm Restart",
            f"Are you sure you want to RESTART {len(targets)} target(s)?",
            parent=self.root,
        ):
            return
        self._send_system_command(targets, "system_restart")

    def system_sleep(self, targets):
        """Puts every target host to sleep, after a single confirmation naming the count."""
        if not targets:
            return
        if not messagebox.askyesno(
            "Confirm Sleep",
            f"Are you sure you want to put {len(targets)} target(s) to SLEEP?",
            parent=self.root,
        ):
            return
        self._send_system_command(targets, "system_sleep")

    # --- Broadcast Message ---
    def broadcast_message_to_slaves(self, message_text):
        """Sends a 'display_message' command to every currently-connected slave."""
        if not message_text or not message_text.strip():
            return
        online_hosts = list(self.network.clients.keys())
        if not online_hosts:
            self.gui.append_log("Broadcast message not sent: no slaves are currently connected.")
            messagebox.showinfo("No Connected Slaves", "No slaves are currently connected.", parent=self.root)
            return

        msg = {"action": "display_message", "text": message_text}
        for hostname in online_hosts:
            self.network.send_to_client(hostname, msg)

        self.gui.append_log(f"Broadcast message sent to {len(online_hosts)} connected slave(s).")
        self._log_action("BROADCAST_MESSAGE", f"{len(online_hosts)} hosts", message_text)

    # --- Screenshot Capture ---
    def request_screenshot(self, hostname):
        """Requests a single screenshot from one host."""
        if hostname not in self.network.clients:
            messagebox.showwarning("Offline", f"'{hostname}' is not currently connected.", parent=self.root)
            return
        self.network.send_to_client(hostname, {"action": "get_screenshot"})
        self.gui.append_log(f"[{hostname}] screenshot requested")

    def request_group_screenshots(self, group_name):
        """Requests a screenshot from every online member of a group (or 'All Nodes'),
        tracking the batch via self._current_screenshot_request so incoming replies
        get routed to the group's tabbed results window."""
        hostnames = self._get_hostnames_for_group(group_name)
        online_members = [h for h in hostnames if h in self.network.clients]

        if not online_members:
            self.gui.append_log(f"No online members found in '{group_name}' for screenshot request.")
            messagebox.showinfo("No Online Nodes", f"No online nodes found in '{group_name}'.", parent=self.root)
            return

        self.gui.open_group_screenshot_popup(group_name, online_members)

        for hostname in online_members:
            self._current_screenshot_request[hostname] = group_name
            self.network.send_to_client(hostname, {"action": "get_screenshot"})

        self.gui.append_log(f"Requested screenshots from {len(online_members)} node(s) in '{group_name}'.")

    # --- Scripts tab (CRUD) ---
    def get_all_scripts(self):
        return db.get_all_scripts()

    def save_script(self, script_data: dict):
        """Creates or updates a saved script. If script_data has an 'id', it's an update."""
        name = (script_data.get("name") or "").strip()
        description = script_data.get("description", "") or ""
        content = script_data.get("content", "") or ""
        script_id = script_data.get("id")

        if not name or not content:
            messagebox.showwarning("Input Required", "Script name and content are required.", parent=self.root)
            return False

        try:
            if script_id:
                db.update_script(script_id, name, description, content)
                self.gui.append_log(f"✅ Updated saved script '{name}'.")
            else:
                db.create_script(name, description, content)
                self.gui.append_log(f"✅ Created saved script '{name}'.")
            return True
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not save script: {e}")
            messagebox.showerror("Database Error", f"Could not save script.\n\n{e}", parent=self.root)
            return False

    def delete_script(self, script_id, script_name):
        """Deletes a saved script. The GUI is expected to confirm before calling
        this, mirroring how on_delete_group works."""
        try:
            db.delete_script(script_id)
            self.gui.append_log(f"Deleted saved script '{script_name}'.")
        except Exception as e:
            self.gui.append_log(f"❌ ERROR: Could not delete script: {e}")
            messagebox.showerror("Database Error", f"Could not delete script.\n\n{e}", parent=self.root)

    # --- Remote Command / Script Execution ---
    def run_command_on_nodes(self, nodes, command):
        """Sends a shell command to every online node in `nodes` and opens a
        tabbed results popup (used even for a single node, for consistency)."""
        if not nodes or not command or not command.strip():
            return

        online_nodes = [h for h in nodes if h in self.network.clients]
        offline_count = len(nodes) - len(online_nodes)

        if not online_nodes:
            messagebox.showwarning("Offline", "None of the selected nodes are currently online.", parent=self.root)
            return

        self.gui.open_command_results_popup(online_nodes, command)

        msg = {"action": "run_command", "command": command}
        for hostname in online_nodes:
            self.network.send_to_client(hostname, msg)

        self.gui.append_log(f"Sent command '{command}' to {len(online_nodes)} online node(s).")
        if offline_count:
            self.gui.append_log(f"Skipped {offline_count} offline node(s) for command execution.")
        self._log_action("RUN_COMMAND", ", ".join(online_nodes), command)

    def _choose_script_source(self):
        """Prompts the admin to pick either a saved script (from the DB) or an
        existing .bat/.ps1 file already sitting in the installers folder.

        A saved script has no file on disk, but the slave's 'run_script_file'
        action can only download a named file from the master's installers
        folder (see NetworkServer._handle_file_conn / FTP upload) - so a saved
        script's content is written out to a temp file inside INSTALLERS_DIR
        first, exactly like any other installer file, and the hybrid
        FTP/direct transfer logic mirrors send_and_extract_zip/update_slave_agents.

        Returns (filepath, cleanup_temp) or None if cancelled.
        """
        saved_scripts = db.get_all_scripts()
        installers_dir = config.INSTALLERS_DIR
        existing_scripts = [f for f in self._get_installers_from_folder() if f.lower().endswith((".bat", ".ps1"))]

        options = [f"[Saved] {s['name']}" for s in saved_scripts] + [f"[File] {f}" for f in existing_scripts]
        if not options:
            messagebox.showinfo(
                "No Scripts",
                "No saved scripts or .bat/.ps1 files found in the installers folder.",
                parent=self.root,
            )
            return None

        indices = self._choose_from_list("Select a script to run", options)
        if not indices:
            return None
        index = indices[0]

        if index < len(saved_scripts):
            script = saved_scripts[index]
            safe_name = "".join(c for c in script["name"] if c.isalnum() or c in (" ", "_", "-")).strip() or "script"
            temp_filename = f"_tmp_script_{safe_name}_{int(time.time())}.ps1"
            temp_path = os.path.join(installers_dir, temp_filename)
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(script["content"])
            except Exception as e:
                messagebox.showerror("Error", f"Could not write temporary script file: {e}", parent=self.root)
                return None
            return (temp_path, True)
        else:
            filename = existing_scripts[index - len(saved_scripts)]
            return (os.path.join(installers_dir, filename), False)

    def _cleanup_temp_script(self, path):
        """Removes a temp script file written out for a saved-script run, once
        slaves have had a reasonable window to download it."""
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def run_script_file_on_nodes(self, hostnames):
        """Lets the admin pick a saved script or a .bat/.ps1 file from the
        installers folder, then sends it to the target hosts via the same
        hybrid FTP/direct transfer pattern used by send_and_extract_zip /
        update_slave_agents. The slave's existing 'run_script_file' handler
        downloads, hash-verifies, executes, and reports back via
        'command_output' - the same status used by run_command_on_nodes, so
        results land in the same tabbed CommandResultsPopup."""
        if not hostnames:
            return

        online_nodes = [h for h in hostnames if h in self.network.clients]
        offline_count = len(hostnames) - len(online_nodes)
        if not online_nodes:
            messagebox.showwarning("Offline", "None of the selected nodes are currently online.", parent=self.root)
            return

        choice = self._choose_script_source()
        if not choice:
            return
        filepath, cleanup_temp = choice

        filename = os.path.basename(filepath)
        digest = sha256_file(filepath)

        use_ftp = False
        if FTP.get("enabled") and len(online_nodes) > FTP.get("threshold", 0):
            self.gui.append_log(f"FTP: Target count exceeds threshold for script '{filename}'. Using FTP.")
            success, _ = self._upload_to_ftp(filepath)
            if not success:
                self.gui.append_log(f"❌ CRITICAL: FTP upload failed for script '{filename}'. Aborting.")
                if cleanup_temp:
                    self._cleanup_temp_script(filepath)
                return
            use_ftp = True

        msg = {
            "action": "run_script_file",
            "filename": filename,
            "sha256": digest,
            "download_method": "ftp" if use_ftp else "direct",
        }

        self.gui.open_command_results_popup(online_nodes, f"script:{filename}")

        for hostname in online_nodes:
            self.network.send_to_client(hostname, msg)

        self.gui.append_log(f"Sent script '{filename}' to {len(online_nodes)} online node(s).")
        if offline_count:
            self.gui.append_log(f"Skipped {offline_count} offline node(s) for script execution.")
        self._log_action("RUN_SCRIPT", f"{len(online_nodes)} hosts", filename)

        if cleanup_temp:
            # Give slaves a window to finish downloading (direct transfers
            # happen asynchronously right after this) before removing the
            # temp file - deleting it immediately would race the download.
            self.root.after(300000, lambda p=filepath: self._cleanup_temp_script(p))

    def add_to_group(self, hostname, group_name):
        """Adds a host to a group and triggers a full UI refresh."""
        db.add_group_member(group_name, hostname)
        self.gui.append_log(f"[{hostname}] added to group {group_name}")
        
        # Refresh both the group list (left panel) and the node list (main panel)
        self.gui.update_group_list()
        self.gui._update_node_list()

    def bulk_install_group(self, group_name):
        """Deploys software from the catalog to a group or to all nodes."""
        rows = self._read_catalog()
        valid_choices = [r for r in rows if r.get("name") and r.get("filename")]
        if not valid_choices:
            messagebox.showerror("Catalog Error", "No valid installers found in catalog.csv.", parent=self.root)
            return

        display_names = [f"{r['name']} ({r.get('version', 'N/A')})" for r in valid_choices]
        selected_indices = self._choose_from_list(f"Select installer(s) for '{group_name}'", display_names)
        if not selected_indices:
            return

        group_members = self._get_hostnames_for_group(group_name)
        if not group_members:
            self.gui.append_log(f"Warning: No nodes found for selection '{group_name}'.")
            return

        for idx in selected_indices:
            selected_software = valid_choices[idx]
            filename = selected_software.get("filename")
            fp = os.path.join(config.INSTALLERS_DIR, filename)
            if not os.path.exists(fp):
                messagebox.showerror("Missing file", f"Installer not found: {filename} in installers/", parent=self.root)
                continue
            
            self.gui.append_log(f"Queueing bulk install of '{selected_software['name']}' for {len(group_members)} target(s)...")
            self.deploy_file_to_host(group_members, fp)
            

    # ... (rest of the file is unchanged) ...
    def _scheduler_loop(self):
        """
        Continuously checks for scheduled installs and policy compliance with robust error handling.
        """
        while self.running:
            try:
                now = time.time()
                
                # --- Block 1: Scheduled Installs ---
                try:
                    due = [task for task in self.scheduled if task[0] <= now]
                    self.scheduled = [task for task in self.scheduled if task[0] > now]

                    # Use underscores for the unused when_ts and digest variables
                    for _, host, fp, _ in due:
                        if os.path.exists(fp):
                            logging.info(f"SCHEDULER: Executing scheduled install of '{os.path.basename(fp)}' for {host}...")
                            self.deploy_file_to_host([host], fp)
                        else:
                            error_msg = f"❌ SCHEDULER: Skipped task for {host}. Installer not found: {os.path.basename(fp)}"
                            logging.warning(error_msg)
                            self.gui.append_log(error_msg)

                except Exception as e:
                    error_msg = f"❌ SCHEDULER: Error processing scheduled installs: {e}"
                    logging.error(error_msg, exc_info=True)
                    self.gui.append_log(error_msg)

                # --- Block 2: Scheduled Policy Checks ---
                try:
                    interval_hours = POLICIES.get("check_interval_hours")
                    if interval_hours:
                        interval_seconds = float(interval_hours) * 3600
                        if now - self.last_policy_check_time >= interval_seconds:
                            self.last_policy_check_time = now
                            logging.info("SCHEDULER: Triggering scheduled policy compliance check...")
                            threading.Thread(
                                target=self._run_compliance_check,
                                kwargs={"trigger_source": "Scheduled"},
                                daemon=True,
                            ).start()
                except Exception as e:
                    error_msg = f"❌ SCHEDULER: Error processing scheduled policy checks: {e}"
                    logging.error(error_msg, exc_info=True)
                    self.gui.append_log(error_msg)

                # --- Block 3: Sleep until the next tick ---
                time.sleep(SCHEDULER.get("tick_seconds", 5))

            except Exception as e:
                # This is a final safety net for any unexpected errors
                error_msg = f"❌ SCHEDULER: A critical, unhandled error occurred in the main loop: {e}"
                logging.critical(error_msg, exc_info=True)
                self.gui.append_log(error_msg)
                time.sleep(30) # Wait longer after a critical failure

    def _read_catalog(self):
        path = CATALOG.get("path")
        real = path
        with open(real, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return rows

    def _choose_from_list(self, title, items):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg="#2E2E2E")
        
        ttk.Label(win, text="Select one or more items (use Ctrl or Shift to multi-select):").pack(pady=(10, 5), padx=10)
        
        var = tk.StringVar(value=items)
        # Allow multiple items to be selected
        lb = tk.Listbox(
            win,
            listvariable=var,
            width=60,
            height=15,
            selectmode=tk.EXTENDED, 
            bg="#3C3C3C", fg="#FFFFFF", selectbackground="#007ACC", highlightthickness=0
        )
        lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        sel = {"indices": None}
        
        def ok():
            try:
                # Get all selected indices
                sel["indices"] = lb.curselection() 
            except Exception:
                sel["indices"] = None
            win.destroy()
            
        ttk.Button(win, text="Select", command=ok).pack(pady=10)
        win.grab_set()
        self.root.wait_window(win)
        return sel["indices"]

    def _count_attempts(self, hostname, software):
        n = 0
        for r in db.read_all("deployments"):
            if r.get("hostname")==hostname and r.get("software")==software:
                n += 1
        return n

    def _maybe_auto_update(self, hostname, info):
        min_map = {k:v for k,v in AUTO_UPDATE.items()}
        if not min_map: return
        present = { i.get("name"): i.get("version","0") for i in info.get("installed_software",[]) }
        for name, rule in min_map.items():
            cur = present.get(name)
            if not cur: continue
            if self._version_lt(cur, rule.get("min_version","0")):
                rows = self._read_catalog()
                match = next((r for r in rows if r["name"]==rule.get("catalog_name")), None)
                if match:
                    fp = os.path.join(config.INSTALLERS_DIR, match["filename"])
                    if os.path.exists(fp):
                        self.gui.append_log(f"[{hostname}] auto-update {name} → {match['version']}")
                        self.deploy_file_to_host([hostname], fp, post_install_cmd=match.get("post_install_cmd",""))

    def _version_lt(self, a, b):
        def norm(v): return [int(x) for x in str(v).split(".") if x.isdigit()]
        A, B = norm(a), norm(b)
        for i in range(max(len(A), len(B))):
            x = A[i] if i < len(A) else 0; y = B[i] if i < len(B) else 0
            if x < y: return True
            if x > y: return False
        return False

    def _refresh_slave_row(self, hostname):
            groups = ",".join([r.get("group_name") for r in db.read_all("group_members") if r.get("hostname")==hostname])
            self.gui.add_or_update_slave(hostname, "", "online", groups)