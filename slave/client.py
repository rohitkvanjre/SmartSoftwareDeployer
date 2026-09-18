# slave/client.py (Final Corrected Version)

import socket, json, time, os, sys, ssl, logging, threading, ipaddress, subprocess
from . import tasks, config
from packaging.version import parse as parse_version
from .config import shared_token
from .tasks import RestartServiceException
import psutil

MAX_AGENT_FRAME = 1024 * 1024

def _log_cert_details(cert_path):
    """Inspects a cert file and logs its Common Name for debugging."""
    try:
        cert_dict = ssl._ssl._test_decode_cert(cert_path)
        subject = dict(x[0] for x in cert_dict['subject'])
        common_name = subject.get('commonName', 'NOT FOUND')
        logging.info(f"DEBUG: Certificate at '{cert_path}' has Common Name: {common_name}")
        return common_name
    except Exception as e:
        logging.error(f"DEBUG: Could not inspect certificate file at '{cert_path}': {e}")
        return None

class SlaveClient:
    @staticmethod
    def discover_master(timeout=5, retries=3):
        """
        Broadcasts on all network interfaces to reliably find the master server.
        """
        discovery_port = config.PORTS.get("discovery", 5051)
        discover_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        discover_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        discover_sock.settimeout(1) # Short timeout for each receive attempt
        message = json.dumps({"type": "DISCOVER_MASTER_REQUEST", "token": shared_token}).encode("utf-8")

        # Get all broadcast addresses for all valid network interfaces
        broadcast_addresses = []
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family != socket.AF_INET or not addr.address:
                        continue
                    bcast = addr.broadcast
                    if not bcast and addr.netmask:
                        # psutil's Windows backend very often leaves `broadcast`
                        # empty even though `address`/`netmask` ARE populated
                        # (a known psutil/Windows limitation, not an error) --
                        # this was silently causing "Found broadcast
                        # addresses: []" on every Windows adapter tested so
                        # far, regardless of network. Derive it ourselves from
                        # the IP/netmask instead of trusting that field.
                        try:
                            network = ipaddress.IPv4Network(f"{addr.address}/{addr.netmask}", strict=False)
                            bcast = str(network.broadcast_address)
                        except ValueError:
                            bcast = None
                    if bcast and not addr.address.startswith("169.254."):
                        broadcast_addresses.append(bcast)
            # Remove duplicates
            broadcast_addresses = list(set(broadcast_addresses))
            logging.info(f"Found broadcast addresses: {broadcast_addresses}")
        except Exception as e:
            logging.error(f"Could not get network interfaces: {e}")
            broadcast_addresses = [] # Ensure it's an empty list on error
        
        # --- THIS IS THE FIX ---
        # If psutil fails or finds no valid interfaces, add the default broadcast address.
        if not broadcast_addresses:
            logging.warning("No specific broadcast addresses found. Adding default '<broadcast>'.")
            broadcast_addresses.append('<broadcast>')
        # --- END OF FIX ---

        for i in range(retries):
            try:
                logging.info(f"Broadcasting for master... (Attempt {i + 1}/{retries})")
                # Send a broadcast on every found interface
                for bcast_addr in broadcast_addresses:
                    discover_sock.sendto(message, (bcast_addr, discovery_port))
                
                # Listen for a reply
                data, addr = discover_sock.recvfrom(1024)
                response = data.decode('utf-8')
                if response.startswith("MASTER_HERE"):
                    master_ip, master_port = addr[0], int(response.split(':')[1])
                    logging.info(f"Master found at {master_ip}:{master_port}")
                    discover_sock.close()
                    return master_ip, master_port
            except socket.timeout:
                continue # This is expected, just try again on the next retry
            except Exception as e:
                logging.error(f"Discovery error: {e}")
        
        discover_sock.close()
        logging.warning("Discovery failed after all retries.")
        return None, None
        
    # def _handle_run_script_file(self, command):
    #     """Downloads a script file, verifies it, executes it, and returns the output."""
    #     filename = command.get("filename")
    #     expected_hash = command.get("sha256")
    #     download_method = command.get("download_method", "direct")
        
    #     if not filename or not expected_hash:
    #         self._log_and_send_error("Invalid 'run_script_file' command received.")
    #         return

    #     self.send_status({"status": "script_transfer", "message": f"Receiving script {filename}..."})
        
    #     # --- Download Logic ---
    #     script_path = None
    #     if download_method == "ftp":
    #         script_path = tasks.download_from_ftp(filename)
    #     else: # direct
    #         script_path = tasks.download_from_master(self.master_ip, filename)

    #     if not script_path:
    #         msg = f"Failed to download script file: {filename}"
    #         self.send_status({"status": "command_output", "data": {"stderr": msg, "returncode": -1}, "command": f"script:{filename}"})
    #         self._log_and_send_error(msg)
    #         return
            
    #     # --- Hash Verification ---
    #     actual_hash = tasks.sha256_file(script_path)
    #     if actual_hash != expected_hash:
    #         msg = f"Hash mismatch for script {filename}! Deleting corrupt file."
    #         self.send_status({"status": "command_output", "data": {"stderr": msg, "returncode": -1}, "command": f"script:{filename}"})
    #         self._log_and_send_error(msg)
    #         try: os.remove(script_path)
    #         except Exception as e: logging.error(f"Failed to delete corrupt script: {e}")
    #         return
            
    #     # --- Execution and Reporting ---
    #     self.send_status({"status": "script_running", "message": f"Executing script {filename}..."})
    #     output = tasks.execute_script_file(script_path)
        
    #     # Send the output back using the existing 'command_output' status
    #     self.send_status({"status": "command_output", "data": output, "command": f"script:{filename}"})
        
    #     try: os.remove(script_path)
    #     except Exception as e: logging.error(f"Failed to clean up script file {script_path}: {e}")

    def _handle_run_script_file(self, command):
        """
        Downloads a script file, verifies it, and executes it in a background thread
        to prevent blocking the main network loop.
        """
        # --- This nested function contains the actual work and will run in the background ---
        def script_thread_target(client_instance, script_command):
            filename = script_command.get("filename")
            # --- THIS IS THE FIX ---
            expected_hash = script_command.get("sha256") # Corrected from "sha26"
            # --- END OF FIX ---
            download_method = script_command.get("download_method", "direct")

            # This check should now pass correctly
            if not filename or not expected_hash:
                client_instance._log_and_send_error("Invalid 'run_script_file' command received (Missing filename or hash).")
                return

            client_instance.send_status({"status": "script_transfer", "message": f"Receiving script {filename}..."})

            # --- Download Logic ---
            script_path = None
            if download_method == "ftp":
                script_path = tasks.download_from_ftp(filename)
            else: # direct
                script_path = tasks.download_from_master(client_instance.master_ip, filename)

            if not script_path:
                msg = f"Failed to download script file: {filename}"
                client_instance.send_status({"status": "command_output", "data": {"stderr": msg, "returncode": -1}, "command": f"script:{filename}"})
                client_instance._log_and_send_error(msg)
                return

            # --- Hash Verification ---
            # Use the correct sha256 function from tasks
            actual_hash = tasks.sha256_file(script_path)
            if actual_hash != expected_hash:
                msg = f"Hash mismatch for script {filename}! Deleting corrupt file."
                client_instance.send_status({"status": "command_output", "data": {"stderr": msg, "returncode": -1}, "command": f"script:{filename}"})
                client_instance._log_and_send_error(msg)
                try: os.remove(script_path)
                except Exception as e: logging.error(f"Failed to delete corrupt script: {e}")
                return

            # --- Execution and Reporting ---
            client_instance.send_status({"status": "script_running", "message": f"Executing script {filename}..."})
            output = tasks.execute_script_file(script_path)

            # Send the output back using the existing 'command_output' status
            client_instance.send_status({"status": "command_output", "data": output, "command": f"script:{filename}"})

            # --- Cleanup ---
            try: os.remove(script_path)
            except Exception as e: logging.error(f"Failed to clean up script file {script_path}: {e}")
        # --- End of the background thread's target function ---

        # --- This part runs on the main network thread ---
        logging.info(f"Spawning background thread to execute script: {command.get('filename')}")
        # Create the thread
        script_runner_thread = threading.Thread(
            target=script_thread_target,
            args=(self, command)
        )
        script_runner_thread.daemon = True
        script_runner_thread.start() # Start the background execution

    def _process_receive_and_extract_zip(self, filename, expected_hash, download_method):
        """Downloads, verifies, extracts zip, and creates shortcut in background."""
        try:
            self.send_status({"status": "ZIP Transfer Started", "message": f"Receiving {filename} via {download_method.upper()}..."})

            # --- Download Logic ---
            # Hash-check a same-named cached file BEFORE trusting it, same as
            # the regular install path's "Local First" logic -- otherwise a
            # newer ZIP pushed under the same filename as a stale cached one
            # would get hash-checked only AFTER being used, and a mismatch
            # there just deleted it and gave up instead of fetching the
            # actual current version.
            cache_path = os.path.join(tasks.DOWNLOADS_PATH, os.path.basename(filename))
            downloaded_path = None
            if os.path.exists(cache_path):
                if tasks.sha256_file(cache_path) == expected_hash:
                    self.send_status({"status": "ZIP Transfer Skipped", "message": "File already in cache."})
                    downloaded_path = cache_path
                else:
                    logging.warning(f"Cached ZIP '{filename}' does not match the requested version; re-downloading.")
                    self.send_status({"status": "Verifying", "message": "Cached file is a different version. Downloading..."})

            if not downloaded_path:
                if download_method == "ftp":
                    downloaded_path = tasks.download_from_ftp(filename)
                else: # direct
                    downloaded_path = tasks.download_from_master(self.master_ip, filename)

            if not downloaded_path:
                msg = f"Failed to download ZIP file: {filename}"
                self.send_status({"status": "ZIP Transfer Failed", "message": msg})
                self._log_and_send_error(msg)
                return

            # --- Hash Verification ---
            actual_hash = tasks.sha256_file(downloaded_path) #
            if actual_hash != expected_hash:
                msg = f"Hash mismatch for ZIP {filename}! Deleting corrupt file."
                self.send_status({"status": "ZIP Verify Failed", "message": msg})
                self._log_and_send_error(msg)
                try: os.remove(downloaded_path)
                except Exception as e: logging.error(f"Failed to delete corrupt ZIP: {e}")
                return
            logging.info(f"Hash verified for {filename}.")
            self.send_status({"status": "ZIP Verified", "message": f"Verified integrity of {filename}."})

            # --- Call the existing Extraction/Shortcut Task ---
            # Pass the send_status method as the callback
            tasks.extract_zip_and_create_shortcut(downloaded_path, filename, self.send_status) #

        except Exception as e:
            # Catch-all for unexpected errors during the process
            error_msg = f"Unexpected error during receive_and_extract_zip for '{filename}': {e}"
            logging.error(error_msg, exc_info=True)
            try:
                # Try to inform the master, connection might be dead
                self._log_and_send_error(error_msg)
            except:
                pass # Ignore errors if we can't send status back

    def __init__(self, master_ip, control_port=5050):
        self.master_ip = master_ip
        self.control_port = control_port
        self.sock = None
        self.auth_token = shared_token
        self.status_obj = AgentStatus()     # Create the shared status object
        self.is_running = True 
        self._send_lock = threading.Lock()

    def _handle_get_log_file(self, command):
        """Handles a request from the master to send back the log file tail."""
        num_lines = command.get("lines", 200)
        log_content = tasks.get_log_tail(num_lines)
        self.send_status({"status": "log_file_content", "hostname": socket.gethostname(), "data": log_content})    

    def _send_payload(self, payload):
        message = json.dumps(payload).encode('utf-8') + b'\n'
        with self._send_lock:
            self.sock.sendall(message)

    def send_status(self, status_data):
        try: 
            payload = dict(status_data)
            payload['hostname'] = socket.gethostname()
            payload['auth'] = self.auth_token
            self._send_payload(payload)
        except Exception as e:
            logging.error(f"ERROR sending status: {e}")

    def start(self):
        """Starts the IPC server thread and the main connection loop to the master."""
        try:
            # --- NEW: Start the IPC server in a background thread ---
            self.status_obj.set_status("Starting IPC Server")
            ipc_thread = threading.Thread(target=self._start_ipc_server, daemon=True)
            ipc_thread.start()
            # --- END NEW ---

            logging.info(f"Connecting to master at {self.master_ip}:{self.control_port}...")
            self.status_obj.set_status(f"Connecting: {self.master_ip}...")
            
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            if not config.TLS.get("enabled"):
                logging.warning("SECURITY WARNING: TLS is disabled - all traffic to the master, including the shared auth token, will be sent in plaintext over the network.")

            if config.TLS.get("enabled"):
                # ... (your existing SSL wrap logic is unchanged) ...
                logging.info("TLS is enabled. Wrapping socket...")
                context = ssl.create_default_context()
                if config.TLS.get("verify"):
                    context.verify_mode = ssl.CERT_REQUIRED
                    context.check_hostname = True
                    cert_path = os.path.join(config.APP_ROOT, config.TLS.get("ca_cert"))
                    _log_cert_details(cert_path)
                    context.load_verify_locations(cert_path)
                else:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                self.sock = context.wrap_socket(self.sock, server_hostname=self.master_ip)

            self.sock.connect((self.master_ip, self.control_port))
            self.sock.settimeout(1.0) # NEW: Set a 1-second timeout
            
            logging.info("Secure connection to master established.")
            self.status_obj.set_status("Connected to Master") # Update status
            self.send_status({"status": "Connected", "message": "Slave is online"})
            
            self._command_loop() # Run the main blocking loop

        except RestartServiceException:
            logging.info("Restart request received, propagating to service manager.")
            raise # Re-raise for the service wrapper
        except ssl.SSLCertVerificationError as e:
            self.status_obj.set_status("SSL CERT ERROR")
            logging.error(f"FATAL ERROR: SSL Certificate Verification Failed: {e}.")
            return False
        except ConnectionRefusedError as e:
            self.status_obj.set_status("Connection Refused")
            logging.warning(f"Connection refused by master: {e}. Will retry.")
            return True
        except Exception as e:
            self.status_obj.set_status(f"Error: {e}")
            logging.error(f"A critical error occurred: {e}. Will retry.")
            return True
        finally:
            self.status_obj.set_status("Offline")
            if self.sock:
                self.sock.close()
            self.is_running = False # Ensure IPC thread also stops
        return True

    def _command_loop(self):
        buffer = b""
        while self.is_running: 
            try:
                # --- NEW: Check for IPC commands (like trigger inventory) ---
                if self.status_obj.check_and_clear_inventory_trigger():
                    logging.info("[MainLoop] Running inventory check triggered by user.")
                    self.status_obj.set_status("Inventory (User Request)")
                    self._handle_get_inventory() # Run the task
                    self.status_obj.set_status("Connected to Master") # Set back to idle

                # --- NEW: Non-blocking socket read with timeout ---
                chunk = None
                try:
                    chunk = self.sock.recv(4096)
                except socket.timeout:
                    continue  # Timeout is expected, just loop again to check flags
                # --- END NEW ---

                if not chunk:
                    logging.info("Connection lost.")
                    break
                if len(buffer) + len(chunk) > MAX_AGENT_FRAME:
                    raise ValueError("Command message exceeds the maximum allowed size")
                buffer += chunk
                while b'\n' in buffer:
                    message_str, buffer = buffer.split(b'\n', 1)
                    if not message_str: continue
                    try:
                        command = json.loads(message_str.decode('utf-8'))
                    except json.JSONDecodeError as e:
                        logging.warning(f"Invalid JSON received: {e}")
                        continue
                    
                    if not isinstance(command, dict): continue

                    # --- THIS IS THE MODIFIED PART ---
                    action = command.get("action")
                    
                    # Only log the command if it's not a 'ping'
                    if action != "ping":
                        log_command = dict(command)
                        log_command.pop("auth", None)
                        logging.info(f"Received command: {log_command}")
                    # --- END OF MODIFICATION ---

                    if action == "receive_file":
                        self._handle_receive_file(command)
                    elif action == "get_log":
                        self._handle_get_log_file(command)  
                    elif action == "get_config":
                        self.send_status({
                            "status": "config_content",
                            "data": tasks.get_config_content()
                        })    
                    elif action == "write_config":
                        content = command.get("data", "")
                        success, message = tasks.write_config_file(content)
                        if success:
                            self.send_status({"status": "config_saved"})
                        else:
                            self.send_status({"status": "slave_log", "data": {"level": "ERROR", "message": f"Write config failed: {message}"}})
                    elif action == "restart_agent":
                        self.send_status({"status": "Restarting Agent", "message": "Restarting to apply settings."})
                        time.sleep(1)
                        self.sock.close()
                        tasks.restart_agent()      
                    elif action == "install":
                        self.status_obj.set_status(f"Starting Install: {command.get('friendly_name')}")
                        self._handle_install(command)
                        self.status_obj.set_status("Connected to Master")
                    elif action == "uninstall":
                        self.status_obj.set_status(f"Uninstalling: {command.get('name')}")
                        self._handle_uninstall(command)
                        self.status_obj.set_status("Connected to Master")
                    elif action == "get_inventory":
                        self._handle_get_inventory(command)
                    elif action == "run_command":
                        cmd_to_run = command.get("command")
                        if cmd_to_run:
                            # Runs on a background thread, same as install/uninstall --
                            # tasks.run_shell_command has its own 60s timeout, and
                            # running it inline here would block this main command
                            # loop (and therefore the socket's heartbeat/stop-signal
                            # responsiveness) for up to that entire 60s on every
                            # remote command the master sends.
                            def run_command_thread_target(client_instance, cmd_to_run):
                                client_instance.status_obj.set_status(f"Running: {cmd_to_run[:30]}...")
                                output = tasks.run_shell_command(cmd_to_run)
                                client_instance.send_status({
                                    "status": "command_output",
                                    "command": cmd_to_run,
                                    "data": output
                                })
                                client_instance.status_obj.set_status("Connected to Master")

                            threading.Thread(
                                target=run_command_thread_target,
                                args=(self, cmd_to_run),
                                daemon=True
                            ).start()
                    elif action == "run_script_file":
                        self._handle_run_script_file(command)
                    elif action == "update_agent":
                        self.status_obj.set_status("Agent Update Started...")
                        tasks.handle_self_update(command, config.SERVICE_NAME, self.master_ip)
                        break # Update task will kill this process   
                    elif action == "ping":
                        resp = {"action": "pong", "auth": shared_token}
                        self._send_payload(resp)
                    elif action == "shutdown":
                        logging.info("Received shutdown command from master. Exiting.")
                        self.send_status({"status": "Shutting Down", "message": "Disconnecting as commanded."})
                        time.sleep(0.5)
                        self.sock.close()
                        break
                    elif action == "reconnect":
                        logging.info("Received reconnect command. Restarting connection loop.")
                        self.send_status({"status": "Restarting Connection", "message": "Re-discovering master."})
                        time.sleep(0.5)
                        self.sock.close()
                        break
                    elif action == "system_shutdown":
                        self.send_status({"status": "System Action", "message": "Shutting down system..."})
                        tasks.SystemPower.shutdown()
                    elif action == "system_restart":
                        self.send_status({"status": "System Action", "message": "Restarting system..."})
                        tasks.SystemPower.restart()
                    elif action == "system_sleep":
                        self.send_status({"status": "System Action", "message": "Putting system to sleep..."})
                        tasks.SystemPower.sleep()
                    elif action == "get_screenshot":
                        # Run the screenshot task in a background thread to avoid blocking.
                        # This runs as a Windows Service (Session 0, no desktop), so it
                        # can't capture the screen itself -- it relays the request to the
                        # tray app running in the actual logged-on user's session, which
                        # can. See tasks.take_screenshot_via_tray_relay.
                        def screenshot_thread():
                            img_data = tasks.take_screenshot_via_tray_relay()
                            if img_data:
                                self.send_status({"status": "screenshot_data", "data": img_data})
                            else:
                                self._log_and_send_error(
                                    "Failed to capture screenshot on slave "
                                    "(no user may be logged on, or the tray app isn't running)."
                                )

                        # Start the thread
                        threading.Thread(target=screenshot_thread, daemon=True).start()
                    elif action == "display_message":
                        message_text = command.get("text")
                        if message_text:
                            logging.info(f"Received broadcast message: '{message_text}'")
                            # Use a thread to avoid blocking the network loop while msg.exe runs
                            display_thread = threading.Thread(
                                target=tasks.display_broadcast_message, # Call the function in tasks.py
                                args=(message_text,),
                                daemon=True
                            )
                            display_thread.start()
                    
                    elif action == "receive_and_extract_zip":
                        filename = command.get("filename")
                        expected_hash = command.get("sha256")
                        download_method = command.get("download_method", "direct")

                        if not filename or not expected_hash:
                            self._log_and_send_error("Invalid 'receive_and_extract_zip' command (missing filename or hash).")
                            continue # Skip to next command

                        # Start the download, verification, extraction, and shortcut creation
                        # in a background thread to keep the main loop responsive.
                        logging.info(f"Received request to receive and extract ZIP: {filename}")
                        process_zip_thread = threading.Thread(
                            target=self._process_receive_and_extract_zip, # New helper function
                            args=(filename, expected_hash, download_method),
                            daemon=True
                        )
                        process_zip_thread.start()
            except SystemExit:
                self.is_running = False
                raise
            except RestartServiceException:
                self.is_running = False
                raise
            except Exception as e:
                self._log_and_send_error(f"An error in command loop: {e}")
                self.is_running = False
                break

    def _log_and_send_error(self, message="An unspecified error occurred on the slave."):
        logging.error(message)
        self.send_status({"status": "slave_log", "data": {"level": "ERROR", "message": message}})

    def _handle_receive_file(self, command):
        filename = command.get("filename")
        if not filename: return
        
        friendly_name = command.get("friendly_name", filename)
        # Check the download method sent by the master
        download_method = command.get("download_method", "direct")

        is_healthy, health_message = tasks.run_health_check()
        if not is_healthy:
            error_msg = f"Health Check Failed: {health_message}"
            self.send_status({"status": "File Transfer Failed", "software": friendly_name, "message": error_msg})
            self._log_and_send_error(error_msg)
            return
        else:
            self.send_status({"status": "Pre-Transfer Check", "software": friendly_name, "message": "Health Check Passed"})
        
        self.send_status({"status": "File Transfer Started", "software": friendly_name, "message": f"Receiving {filename} via {download_method.upper()}..."})
        
        cache_path = os.path.join(tasks.DOWNLOADS_PATH, os.path.basename(filename))
        if os.path.exists(cache_path):
            self.send_status({"status": "File Transfer Skipped", "software": friendly_name, "message": "File already exists in cache."})
            return

        # Use the correct downloader based on the method
        downloaded_path = None
        if download_method == "ftp":
            downloaded_path = tasks.download_from_ftp(filename)
        else: # "direct"
            downloaded_path = tasks.download_from_master(self.master_ip, filename)

        if downloaded_path:
            self.send_status({"status": "File Transfer Success", "software": friendly_name, "message": "File stored in cache."})
        else:
            self.send_status({"status": "File Transfer Failed", "software": friendly_name, "message": f"Download via {download_method.upper()} failed."})
            self._log_and_send_error(f"File transfer failed for '{filename}'.")

    def _start_ipc_server(self):
        """
        Runs a file-based IPC loop to communicate with the Tray App.
        This replaces the old socket-based server.
        """
        logging.info(f"[IPC_File_Server] Starting polling loop for command file: {self.status_obj.command_file}")

        while self.is_running:
            try:
                # Check if the command file exists
                if os.path.exists(self.status_obj.command_file):
                    with open(self.status_obj.command_file, "r") as f:
                        command = f.read().strip()
                    
                    logging.info(f"[IPC_File_Server] Received command: {command}")
                    
                    if command == "TRIGGER_INVENTORY":
                        self.status_obj.trigger_inventory()
                    
                    # IMPORTANT: Delete the file to acknowledge the command
                    os.remove(self.status_obj.command_file)

            except Exception as e:
                if self.is_running:
                    logging.warning(f"[IPC_File_Server] Error in polling loop: {e}")
            
            # Wait for 2 seconds before checking again
            time.sleep(2)

    # def _handle_install(self, command):
    #     # --- Block 1: Get Initial Info (No change) ---
    #     filename = command.get("filename")
    #     friendly_name = command.get("friendly_name", filename)
    #     expected_hash = command.get("sha256")
    #     version_str = command.get("version") or "0"
    #     new_version = parse_version(version_str)

    #     # --- Block 2: Pre-flight & Version Checks (No change) ---
    #     inventory = tasks.get_system_info()
    #     # (This section contains all the OS/arch checks, health checks, and old version uninstall logic)
    #     req_os = command.get("required_os")
    #     if req_os:
    #         sys_os = inventory.get("os_info", {}).get("system", "Unknown")
    #         if req_os.lower() not in sys_os.lower():
    #             msg = f"Skipped: OS requirement not met (Required: {req_os}, System: {sys_os})"
    #             self.send_status({"status": "Skipped", "software": friendly_name, "message": msg}); logging.warning(msg)
    #             return
    #     req_arch = command.get("required_arch")
    #     if req_arch:
    #         sys_arch = inventory.get("os_info", {}).get("architecture", "Unknown")
    #         if req_arch.lower() not in sys_arch.lower():
    #             msg = f"Skipped: Architecture requirement not met (Required: {req_arch}, System: {sys_arch})"
    #             self.send_status({"status": "Skipped", "software": friendly_name, "message": msg}); logging.warning(msg)
    #             return
    #     is_healthy, health_message = tasks.run_health_check()
    #     if not is_healthy:
    #         error_msg = f"Health Check Failed: {health_message}"
    #         self.send_status({"status": "Install: Failed", "software": friendly_name, "message": error_msg}); self._log_and_send_error(error_msg)
    #         return
    #     else:
    #         self.send_status({"status": "Pre-Install Check", "software": friendly_name, "message": "Health Check Passed"})
    #     installed_software = inventory.get("installed_software", [])
    #     software_to_uninstall = None
    #     for soft in installed_software:
    #         if soft.get('name', '').lower() in friendly_name.lower():
    #             try:
    #                 installed_version = parse_version(soft.get('version', "0"))
    #                 if installed_version >= new_version:
    #                     message = f"Version {installed_version} or newer is already installed."
    #                     self.send_status({"status": "Skipped", "software": friendly_name, "message": message})
    #                     logging.info(message)
    #                     return
    #                 if new_version > installed_version:
    #                     self.send_status({"status": "Updating", "software": friendly_name, "message": f"Found old version {installed_version}."})
    #                     software_to_uninstall = soft['name']
    #                     break
    #             except Exception:
    #                 continue
    #     if software_to_uninstall:
    #         self.send_status({"status": "Uninstalling", "software": friendly_name, "message": f"Removing old version: {software_to_uninstall}"})
    #         uninstalled_ok, un_message = tasks.Uninstaller.uninstall(software_to_uninstall, inventory)
    #         if not uninstalled_ok:
    #             self.send_status({"status": "Update: Failed", "software": friendly_name, "message": f"Failed to uninstall old version: {un_message}"})
    #             self._log_and_send_error(f"Failed to uninstall old version for '{friendly_name}'. Details: {un_message}")
    #             return

    #     # --- Block 3: NEW "Local First" File Acquisition Logic ---
    #     installer_path_to_use = None
    #     self.send_status({"status": "Locating", "software": friendly_name, "message": "Searching for installer locally..."})
    #     local_path = tasks.find_installer_locally(filename)

    #     if local_path and expected_hash:
    #         logging.info(f"Found local installer at: {local_path}. Verifying hash...")
    #         self.send_status({"status": "Verifying", "software": friendly_name, "message": "Found local file, checking integrity..."})
            
    #         actual_hash = tasks.sha256_file(local_path)
    #         if actual_hash == expected_hash:
    #             logging.info("Local file hash matches. Skipping download.")
    #             self.send_status({"status": "Download Skipped", "software": friendly_name, "message": "Using verified local file."})
    #             installer_path_to_use = local_path
    #         else:
    #             logging.warning(f"Local file hash mismatch! Will re-download.")
    #             self.send_status({"status": "Verifying", "software": friendly_name, "message": "Local file is wrong version. Downloading..."})
        
    #     # --- Block 4: Fallback Download Logic ---
    #     if not installer_path_to_use:
    #         download_method = command.get("download_method", "direct")
    #         self.send_status({"status": "Downloading", "software": friendly_name, "message": f"Requesting via {download_method.upper()}..."})
            
    #         downloader = None
    #         if download_method == "ftp":
    #             downloader = lambda fname: tasks.download_from_ftp(fname)
    #         else: # "direct"
    #             downloader = lambda fname: tasks.download_from_master(self.master_ip, fname)
            
    #         installer_path_to_use = downloader(filename)
    #         if not installer_path_to_use:
    #             msg = "File could not be located locally or downloaded."
    #             self.send_status({"status": "Install: Failed", "software": friendly_name, "message": msg}); self._log_and_send_error(msg)
    #             return
            
    #         if expected_hash:
    #             actual_hash = tasks.sha256_file(installer_path_to_use)
    #             if actual_hash != expected_hash:
    #                 msg = f"Hash mismatch after download! Deleting corrupt file."
    #                 self.send_status({"status": "Install: Failed", "software": friendly_name, "message": msg}); self._log_and_send_error(msg)
    #                 try: os.remove(installer_path_to_use)
    #                 except Exception as e: logging.error(f"Failed to delete corrupt file: {e}")
    #                 return
    #             logging.info("Downloaded file hash verification successful.")

    #     # --- Block 5: Installation and Reporting (No change) ---
    #     self.send_status({"status": "Installing", "software": friendly_name, "message": "All checks passed..."})
    #     success, message = tasks.Installer.install(installer_path_to_use, command.get("silent_flags", ""))
        
    #     if success:
    #         source_message = "Update" if software_to_uninstall else "New Install"
    #         self.send_status({"status": f"{source_message}: Success", "software": friendly_name, "message": message})
    #         logging.info("Installation successful. Sending updated inventory to master...")
    #         self.send_status({"status": "inventory_report", "data": tasks.get_system_info()})
    #     else:
    #         source_message = "Update" if software_to_uninstall else "New Install"
    #         self.send_status({"status": f"{source_message}: Failed", "software": friendly_name, "message": message})
    #         self._log_and_send_error(f"Installation failed for '{filename}'. Details: {message}")

    def _handle_install(self, command):
        """
        Handles an install request by starting the installation process in a new,
        non-blocking background thread. This allows the main network loop to remain
        responsive to heartbeat pings.
        """
        # This is the function that will run in the background.
        def install_thread_target(client_instance, install_command):
            # --- This logic runs in the background, leaving the main thread free ---
            filename = install_command.get("filename")
            friendly_name = install_command.get("friendly_name", filename)
            expected_hash = install_command.get("sha256")
            version_str = install_command.get("version") or "0"
            new_version = parse_version(version_str)

            # --- Block 1: Pre-flight & Version Checks ---
            inventory = tasks.get_system_info()
            
            req_os = install_command.get("required_os")
            if req_os and req_os.lower() not in inventory.get("os_info", {}).get("system", "").lower():
                msg = f"Skipped: OS requirement not met (Required: {req_os})"
                client_instance.send_status({"status": "Skipped", "software": friendly_name, "message": msg})
                logging.warning(msg)
                return

            req_arch = install_command.get("required_arch")
            if req_arch and req_arch.lower() not in inventory.get("os_info", {}).get("architecture", "Unknown").lower():
                msg = f"Skipped: Architecture requirement not met (Required: {req_arch})"
                client_instance.send_status({"status": "Skipped", "software": friendly_name, "message": msg})
                logging.warning(msg)
                return

            is_healthy, health_message = tasks.run_health_check()
            if not is_healthy:
                error_msg = f"Health Check Failed: {health_message}"
                client_instance.send_status({"status": "Install: Failed", "software": friendly_name, "message": error_msg})
                client_instance._log_and_send_error(error_msg)
                return
            else:
                client_instance.send_status({"status": "Pre-Install Check", "software": friendly_name, "message": "Health Check Passed"})

            installed_software = inventory.get("installed_software", [])
            software_to_uninstall = None

            for soft in installed_software:
                installed_name = soft.get('name', '').lower()
                catalog_name = friendly_name.lower()

                # Use your original (and correct) check logic
                if catalog_name in installed_name:
                    logging.info(f"VERSION_CHECK: Found match. Catalog='{catalog_name}', Installed='{installed_name}'")
                    try:
                        installed_version_str = soft.get('version', "0")
                        new_version_str = version_str # from the command

                        installed_version = parse_version(installed_version_str)
                        new_version = parse_version(new_version_str)

                        logging.info(f"VERSION_CHECK: Comparing. Installed='{installed_version}' >= New='{new_version}' ?")

                        if installed_version >= new_version:
                            message = f"Version {installed_version} or newer is already installed. Skipping."
                            client_instance.send_status({"status": "Skipped", "software": friendly_name, "message": message})
                            logging.warning(f"VERSION_CHECK: {message}")
                            return  # This is the "success" exit (skip)
                        else:
                            # This is the "update" path
                            logging.info(f"VERSION_CHECK: New version detected. Proceeding with update.")
                            client_instance.send_status({"status": "Updating", "software": friendly_name, "message": f"Found old version {installed_version}."})
                            software_to_uninstall = soft['name']
                            break
                    except Exception as e:
                        # This happens if a version is "N/A" or a weird string. Install anyway.
                        logging.warning(f"VERSION_CHECK: Failed to parse version ({e}). Continuing install.")
                        continue
            # --- END OF NEW LOGIC ---
            
            if software_to_uninstall:
                client_instance.send_status({"status": "Uninstalling", "software": friendly_name, "message": f"Removing old version: {software_to_uninstall}"})
                uninstalled_ok, un_message = tasks.Uninstaller.uninstall(software_to_uninstall, inventory)
                if not uninstalled_ok:
                    client_instance.send_status({"status": "Update: Failed", "software": friendly_name, "message": f"Failed to uninstall old version: {un_message}"})
                    client_instance._log_and_send_error(f"Failed to uninstall old version for '{friendly_name}'. Details: {un_message}")
                    return

            # --- Block 2: "Local First" File Acquisition Logic ---
            client_instance.send_status({"status": "Locating", "software": friendly_name, "message": "Searching for installer locally..."})
            installer_path_to_use = tasks.find_installer_locally(filename)

            if installer_path_to_use and expected_hash:
                actual_hash = tasks.sha256_file(installer_path_to_use)
                if actual_hash != expected_hash:
                    logging.warning(f"Local file hash mismatch! Will re-download.")
                    client_instance.send_status({"status": "Verifying", "software": friendly_name, "message": "Local file is wrong version. Downloading..."})
                    installer_path_to_use = None # Invalidate path to trigger download
                else:
                    logging.info("Local file hash matches. Skipping download.")
                    client_instance.send_status({"status": "Download Skipped", "software": friendly_name, "message": "Using verified local file."})

            # --- Block 3: Fallback Download Logic ---
            if not installer_path_to_use:
                download_method = install_command.get("download_method", "direct")
                client_instance.send_status({"status": "Downloading", "software": friendly_name, "message": f"Requesting via {download_method.upper()}..."})
                
                downloader = tasks.download_from_ftp if download_method == "ftp" else lambda f: tasks.download_from_master(client_instance.master_ip, f)
                installer_path_to_use = downloader(filename)

                if not installer_path_to_use:
                    msg = "File could not be located locally or downloaded."
                    client_instance.send_status({"status": "Install: Failed", "software": friendly_name, "message": msg})
                    client_instance._log_and_send_error(msg)
                    return
                
                if expected_hash:
                    actual_hash = tasks.sha256_file(installer_path_to_use)
                    if actual_hash != expected_hash:
                        msg = "Hash mismatch after download! Deleting corrupt file."
                        client_instance.send_status({"status": "Install: Failed", "software": friendly_name, "message": msg})
                        client_instance._log_and_send_error(msg)
                        try: os.remove(installer_path_to_use)
                        except Exception as e: logging.error(f"Failed to delete corrupt file: {e}")
                        return
                    logging.info("Downloaded file hash verification successful.")

            # --- Block 4: Installation and Final Reporting ---
            client_instance.send_status({"status": "Installing", "software": friendly_name, "message": "All checks passed..."})
            success, message = tasks.Installer.install(
                local_path=installer_path_to_use,
                silent_flags=install_command.get("silent_flags", ""),
                friendly_name=friendly_name,
                pre_install_kill_list=install_command.get("pre_install_kill", ""),
                post_install_kill_list=install_command.get("post_install_kill", ""),
                install_context=install_command.get("install_context", "system") # <-- ADD THIS LINE
            )
            
            if success:
                source_message = "Update" if software_to_uninstall else "New Install"
                client_instance.send_status({"status": f"{source_message}: Success", "software": friendly_name, "message": message})
                logging.info("Installation successful. Sending updated inventory to master...")
                client_instance.send_status({"status": "inventory_report", "data": tasks.get_system_info()})

                post_install_cmd = install_command.get("post_install_cmd")
                if isinstance(post_install_cmd, str) and post_install_cmd.strip():
                    client_instance.send_status({"status": "Post-Install", "software": friendly_name, "message": "Running post-install command..."})
                    result = tasks.run_shell_command(post_install_cmd)
                    if result.get("returncode") == 0:
                        client_instance.send_status({"status": "Post-Install: Success", "software": friendly_name, "message": result.get("stdout", "")[:500]})
                    else:
                        client_instance.send_status({"status": "Post-Install: Failed", "software": friendly_name, "message": result.get("stderr", "")[:500]})
            else:
                source_message = "Update" if software_to_uninstall else "New Install"
                client_instance.send_status({"status": f"{source_message}: Failed", "software": friendly_name, "message": message})
                client_instance._log_and_send_error(f"Installation failed for '{filename}'. Details: {message}")

        # --- This part runs on the main thread ---
        # Create and start the background thread, passing it the client instance and the command.
        installer_thread = threading.Thread(
            target=install_thread_target,
            args=(self, command)
        )
        installer_thread.daemon = True  # Allows the main program to exit even if threads are running
        installer_thread.start()
        # The function returns immediately, unblocking the main _command_loop.


    def _handle_uninstall(self, command):
        """Runs the actual uninstall on a background thread, matching
        _handle_install's pattern, and returns immediately so a slow or
        hung uninstaller (e.g. one silently waiting on a "close this
        running application" dialog it can never show, since a Windows
        Service has no desktop to show it on) can't block the main
        _command_loop -- which would otherwise starve the socket's
        read/heartbeat traffic and make the master think the whole
        connection died, not just this one uninstall."""
        def uninstall_thread_target(client_instance, command):
            software_name = command.get("name")
            client_instance.send_status({"status": "Uninstalling", "software": software_name, "message": f"Uninstalling {software_name}..."})
            inventory = tasks.get_system_info()
            success, message = tasks.Uninstaller.uninstall(
                name=software_name,
                inventory=inventory,
                pre_uninstall_kill_list=command.get("pre_uninstall_kill", "")
            )
            if success:
                status_key = "Success"
                client_instance.send_status({"status": f"Uninstall {status_key}", "software": software_name, "message": message})
                logging.info("Uninstallation successful. Sending updated inventory to master...")
                updated_inventory = tasks.get_system_info()
                client_instance.send_status({"status": "inventory_report", "data": updated_inventory})
            else:
                status_key = "Failed"
                client_instance.send_status({"status": f"Uninstall {status_key}", "software": software_name, "message": message})
                client_instance._log_and_send_error(f"Uninstallation failed for '{software_name}'. Details: {message}")

        uninstall_thread = threading.Thread(target=uninstall_thread_target, args=(self, command))
        uninstall_thread.daemon = True
        uninstall_thread.start()
        # Returns immediately, unblocking the main _command_loop.

    def _handle_get_inventory(self, command):
        inventory_data = tasks.get_system_info()
        self.send_status({"status": "inventory_report", "data": inventory_data})

def _grant_users_modify_access(path):
    """Grants the built-in "Users" group Modify rights on path, inherited by
    every file/subfolder created there afterward.

    This service creates the shared IPC folder while running as LocalSystem,
    so it inherits %ProgramData%'s ACL -- which only grants standard users
    Read & Execute, not Modify. That was never a problem while each shared
    file only ever flowed one way (SYSTEM writes status.json, standard user
    only reads it; standard user writes command.txt, SYSTEM reads it) -- but
    the screenshot relay needs the tray app (running as the logged-on
    standard user, NOT SYSTEM) to delete/overwrite files SYSTEM created,
    which fails with WinError 5 (Access is denied) without this. Uses the
    well-known SID for BUILTIN\\Users (S-1-5-32-545) rather than the literal
    name "Users" so this works regardless of the OS's display language.
    Best-effort: failure is logged but never fatal.
    """
    try:
        # /T recurses into files/subfolders that already exist -- without
        # it, inheritance only covers files created AFTER this grant, so a
        # request file already stuck there from before this fix shipped
        # would stay undeletable until this ran with /T at least once.
        subprocess.run(
            ["icacls", path, "/grant", "*S-1-5-32-545:(OI)(CI)M", "/T"],
            capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as e:
        logging.warning(f"Could not grant Users modify access on '{path}': {e}")


class AgentStatus:
    """A thread-safe class that manages agent status via a file for IPC."""
    def __init__(self):
        self._lock = threading.Lock()
        self._status = "Initializing..."
        self._inventory_trigger = False

        # Define a path in a publicly writable location
        self.ipc_dir = os.path.join(os.environ.get("ProgramData"), "SoftwareDeployerAgent", "ipc")
        os.makedirs(self.ipc_dir, exist_ok=True)
        _grant_users_modify_access(self.ipc_dir)
        self.status_file = os.path.join(self.ipc_dir, "status.json")
        self.command_file = os.path.join(self.ipc_dir, "command.txt")

    def set_status(self, new_status):
        with self._lock:
            self._status = new_status
            try:
                # Write the status to the file for the tray app to read
                status_data = {"status": new_status, "timestamp": time.time()}
                with open(self.status_file, "w") as f:
                    json.dump(status_data, f)
            except Exception as e:
                logging.error(f"[StatusFile] Failed to write status: {e}")

        logging.info(f"[Status] {new_status}")

    def get_status(self):
        with self._lock:
            return self._status

    def trigger_inventory(self):
        with self._lock:
            self._inventory_trigger = True

    def check_and_clear_inventory_trigger(self):
        with self._lock:
            if self._inventory_trigger:
                self._inventory_trigger = False
                return True
            return False
