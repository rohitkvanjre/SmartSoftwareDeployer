"""Module: networking
Auto-refactored into software_deploy package.
"""

import socket, threading, json, os, traceback, ssl, time, hmac
from datetime import datetime, timezone
from . import db
from .config import PORTS, TLS, HEALTH
import logging
from . import config
from common.pairing_protocol import hash_token


BUF = 4096
MAX_CONTROL_FRAME = 1024 * 1024
MAX_FILE_HEADER = 4096

class NetworkServer:
    def __init__(self, on_slave_connected=None, on_slave_disconnected=None, on_inventory=None, on_status=None, on_slave_log=None, on_slave_log_file=None, on_slave_config_file=None, pairing=None) :
        self.port = PORTS["control"]
        self.clients = {}
        self.running = True
        self.on_slave_connected = on_slave_connected
        self.on_slave_disconnected = on_slave_disconnected
        self.on_inventory = on_inventory
        self.on_status = on_status
        self.on_slave_log = on_slave_log
        self.on_slave_log_file = on_slave_log_file
        self.on_slave_config_file = on_slave_config_file
        self.pairing = pairing

    def start(self):
        threading.Thread(target=self._run_tcp_server, daemon=True).start()
        threading.Thread(target=self._run_discovery_server, daemon=True).start()
        threading.Thread(target=self._run_file_server, daemon=True).start()
        threading.Thread(target=self._health_loop, daemon=True).start()

    # ---- TCP control server ----
    def close_client_connection(self, hostname):
        """Forcefully closes the connection to a specific client from the server side."""
        client_tuple = self.clients.get(hostname)
        if client_tuple:
            conn, _, _ = client_tuple
            try:
                conn.close()
                logging.info(f"Force-closed connection to {hostname} from server side.")
            except Exception as e:
                logging.warning(f"Error during force-close for {hostname}: {e}")

    def _wrap_server_conn(self, conn):
        # TLS is mandatory: slaves pin this certificate's fingerprint, and
        # pairing binds its proofs to it.
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cert_path = os.path.join(config.MASTER_DIR, TLS.get("server_cert", "data/cert.pem"))
        key_path = os.path.join(config.MASTER_DIR, TLS.get("server_key", "data/key.pem"))
        ctx.load_cert_chain(cert_path, key_path)
        return ctx.wrap_socket(conn, server_side=True)

    def _run_tcp_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", self.port))
        s.listen(100)
        while self.running:
            try:
                conn, addr = s.accept()
                conn = self._wrap_server_conn(conn)
                t = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
                t.start()
            except ssl.SSLEOFError:
                # This specific error is expected during the shutdown dummy connection.
                # We catch it and do nothing ("pass") to suppress the message.
                logging.info("exiting")
                pass    
            except Exception:
                traceback.print_exc()

    def _handle_client(self, conn, addr):
        ip = addr[0]
        # Set once the connection's first message authenticates; every later
        # message on this connection is attributed to this hostname,
        # whatever hostname it claims.
        hostname = None
        buf = b""
        try:
            while self.running:
                data = conn.recv(BUF)
                if not data:
                    break
                if len(buf) + len(data) > MAX_CONTROL_FRAME:
                    raise ValueError("Control message exceeds the maximum allowed size")
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line:
                        continue

                    msg = json.loads(line.decode("utf-8", errors="replace"))

                    if hostname is None:
                        if msg.get("type") == "pair_request" and self.pairing:
                            self.pairing.handle(conn, ip, msg, buf)
                            return
                        if not self._auth_ok(msg):
                            logging.warning(f"[AUTH FAIL] Rejected connection from {ip} claiming to be '{msg.get('hostname')}'.")
                            return
                        hostname = msg.get("hostname")

                    # This is the single, correct block for handling all message types
                    event_type = msg.get("status")

                    if event_type == "Connected":
                        if self.on_slave_connected and hostname:
                            from . import db # Make sure db is imported
                            self.clients[hostname] = (conn, ip, time.time())
                            # Use the new database function
                            self.on_slave_connected(hostname, ip)

                    elif event_type == "inventory_report":
                        if self.on_inventory and hostname:
                            info = msg.get("data", {})
                            # Use the new database function
                            from . import db
                            db.update_latest_inventory(hostname, datetime.now(timezone.utc).isoformat(), json.dumps(info))
                            self.on_inventory(hostname, info)
                    
                    elif event_type == "log_file_content":
                        if self.on_slave_log_file and hostname:
                            self.on_slave_log_file(hostname, msg.get("data", ""))

                    elif event_type == "config_content":
                        if self.on_slave_config_file and hostname:
                            self.on_slave_config_file(hostname, msg.get("data", ""))
                    
                    elif event_type == "slave_log":
                        if self.on_slave_log and hostname:
                            self.on_slave_log(hostname, msg.get("data", {}))

                    elif event_type: # This correctly catches all other statuses like "Installing", "Success", etc.
                        if self.on_status and hostname:
                            self.on_status(hostname, msg)

                    else:
                        # This handles non-status messages like "pong"
                        if (msg.get("event") == "pong" or msg.get("action") == "pong") and hostname in self.clients:
                            c, ip0, _ = self.clients[hostname]
                            self.clients[hostname] = (c, ip0, time.time())
                        else:
                            print(f"[UNKNOWN MESSAGE FORMAT] {msg}")

        except Exception:
            traceback.print_exc()
        finally:
            try: conn.close()
            except: pass
            if hostname and hostname in self.clients:
                self.clients.pop(hostname, None)
                if self.on_slave_disconnected:
                    self.on_slave_disconnected(hostname)
                    
    # ---- UDP discovery ----
    def _run_discovery_server(self):
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        u.bind(("", PORTS["discovery"]))
        while self.running:
            try:
                data, addr = u.recvfrom(1024)
                try:
                    parsed = json.loads(data.decode("utf-8"))
                    # Answered without authentication: unpaired slaves need
                    # to find the master to pair at all, and the master's
                    # address isn't secret. Slaves verify the master's
                    # identity by certificate pin / pairing proof instead.
                    if parsed.get("type") == "DISCOVER_MASTER_REQUEST":
                        u.sendto(f"MASTER_HERE:{self.port}".encode("utf-8"), addr)
                    else:
                        logging.debug(f"Ignored invalid discovery probe from {addr}")
                except Exception:
                    logging.debug(f"Ignored invalid discovery probe from {addr}")
            except Exception:
                traceback.print_exc()

    # ---- File server ----
    def _run_file_server(self):
        installers_dir = config.INSTALLERS_DIR
        os.makedirs(installers_dir, exist_ok=True)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", PORTS["files"]))
        s.listen(50)
        while self.running:
            try:
                conn, addr = s.accept()
                conn = self._wrap_server_conn(conn)
                threading.Thread(target=self._handle_file_conn, args=(conn, installers_dir), daemon=True).start()
            except Exception:
                traceback.print_exc()

    def _handle_file_conn(self, conn, installers_dir):
        try:
            header = b""
            while True:
                chunk = conn.recv(BUF)
                if not chunk:
                    break
                header += chunk
                try:
                    meta = json.loads(header.decode("utf-8").strip())
                    break
                except Exception:
                    if len(header) > MAX_FILE_HEADER:
                        raise RuntimeError("Invalid header")
            if not self._auth_ok(meta):
                raise PermissionError("File request authentication failed")
            filename = meta.get("filename")
            if not filename:
                raise RuntimeError("No filename")
            installers_root = os.path.realpath(installers_dir)
            path = os.path.realpath(os.path.join(installers_root, os.path.basename(filename)))
            if os.path.commonpath((installers_root, path)) != installers_root:
                raise PermissionError("Requested file is outside the installer directory")
            if not os.path.isfile(path):
                raise FileNotFoundError(path)
            size = os.path.getsize(path)
            conn.sendall((json.dumps({"size": size}) + "\n").encode("utf-8"))
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(BUF)
                    if not chunk:
                        break
                    conn.sendall(chunk)
        except Exception:
            traceback.print_exc()
        finally:
            try: conn.close()
            except: pass

    # ---- Outbound ----
    def send_to_client(self, hostname, msg: dict):
        t = self.clients.get(hostname)
        if not t:
            return
        conn, _, _ = t
        conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))

    def send_to_group(self, group_name, msg):
        # This is now much more efficient, asking the DB for exactly what we need.
        members = db.get_all_groups(group_name)
        for member in members:
            hostname = member.get("hostname")
            if hostname:
                self.send_to_client(hostname, msg)


    def _auth_ok(self, msg):
        """Checks a slave's own pairing-issued token against the stored hash
        for the hostname it claims."""
        hostname = msg.get("hostname")
        token = msg.get("auth")
        if not isinstance(hostname, str) or not isinstance(token, str):
            return False
        stored_hash = db.get_slave_token_hash(hostname)
        return stored_hash is not None and hmac.compare_digest(hash_token(token), stored_hash)

        # ---- Health ----  
        # This is the missing health-check/heartbeat function
    def _health_loop(self):
        while self.running:
            now = time.time()
            for host, (conn, ip, last_pong) in list(self.clients.items()):
                try:
                    # Periodically send a 'ping' to the client
                    ping_msg = {"action": "ping"}
                    conn.sendall((json.dumps(ping_msg) + "\n").encode("utf-8"))
                except Exception:
                    # If sending fails, we'll catch it on the timeout below
                    pass
                
                # If we haven't received a 'pong' back recently, disconnect the slave
                if now - last_pong > HEALTH.get("offline_after_seconds", 30):
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self.clients.pop(host, None)
                    if self.on_slave_disconnected:
                        self.on_slave_disconnected(host)
            
            time.sleep(HEALTH.get("ping_seconds", 10))