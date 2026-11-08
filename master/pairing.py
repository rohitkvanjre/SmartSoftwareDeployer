"""Master side of slave pairing (see common/pairing_protocol.py for the
cryptographic design). An admin opens a time-limited pairing window, which
shows a short code; every slave installed with that code during the window
receives its own long random token."""

import json
import logging
import os
import socket
import ssl
import threading
import time

from common import pairing_protocol as proto
from . import config, db

DEFAULT_WINDOW_SECONDS = 30 * 60

# Online guessing limits. A wrong code costs an attacker one of these per
# attempt, so with a 2^40 code space the odds of a lucky guess are negligible.
MAX_FAILURES_PER_IP = 5
MAX_FAILURES_TOTAL = 20
# Each request makes the master run scrypt and hand out a proof, so requests
# are capped too -- this bounds both CPU cost and offline-guessing material.
MAX_REQUESTS_PER_IP = 10

_EXCHANGE_TIMEOUT_SECONDS = 30
_MAX_LINE_BYTES = 4096


def master_ip_addresses():
    """Returns (primary_ip, other_ips) for display in the pairing dialog.

    A PC can have several addresses, e.g. a WSL/Hyper-V virtual adapter that
    lab PCs can't reach. The primary is the address Windows would send
    network traffic from (connecting a UDP socket picks the outgoing
    interface without sending anything); the rest are listed in case it's
    the wrong one."""
    primary = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            primary = probe.getsockname()[0]
    except OSError:
        pass
    from .generate_certs import detect_local_ipv4_addresses
    found = [ip for ip in detect_local_ipv4_addresses()
             if not ip.startswith(("127.", "169.254.", "0."))]
    if primary in (None, "0.0.0.0") or primary.startswith(("127.", "169.254.")):
        primary = found[0] if found else None
    return primary, [ip for ip in found if ip != primary]


def master_cert_fingerprint():
    cert_path = os.path.join(config.MASTER_DIR, config.TLS.get("server_cert", "data/cert.pem"))
    with open(cert_path, "r", encoding="ascii") as f:
        der = ssl.PEM_cert_to_DER_cert(f.read())
    return proto.cert_fingerprint(der)


class PairingManager:
    def __init__(self, on_event=None):
        self._lock = threading.Lock()
        self._on_event = on_event or (lambda message: None)
        self._reset_window(code=None, expires_at=0.0)

    def _reset_window(self, code, expires_at):
        self._code = code
        self._expires_at = expires_at
        self._failures_by_ip = {}
        self._requests_by_ip = {}
        self._failures_total = 0
        self._paired_hosts = []

    def start(self, duration_seconds=DEFAULT_WINDOW_SECONDS):
        with self._lock:
            self._reset_window(proto.generate_code(), time.time() + duration_seconds)
        self._on_event("Pairing window opened.")

    def stop(self):
        with self._lock:
            was_open = self._is_open_locked()
            self._reset_window(code=None, expires_at=0.0)
        if was_open:
            self._on_event("Pairing window closed.")

    def _is_open_locked(self):
        return self._code is not None and time.time() < self._expires_at

    def status(self):
        with self._lock:
            is_open = self._is_open_locked()
            return {
                "open": is_open,
                "code": proto.format_code(self._code) if is_open else None,
                "seconds_left": max(0, int(self._expires_at - time.time())) if is_open else 0,
                "paired_hosts": list(self._paired_hosts),
            }

    def handle(self, conn, ip, request, leftover):
        """Runs one pairing exchange on an already-TLS-wrapped connection.
        `request` is the first (already parsed) message; `leftover` is any
        bytes received after it."""
        hostname = request.get("hostname")
        slave_nonce = request.get("nonce")
        if not isinstance(hostname, str) or not hostname.strip() or len(hostname) > 255 \
                or not proto.is_valid_nonce(slave_nonce):
            self._send(conn, {"type": "pair_result", "ok": False, "reason": "bad_request"})
            return
        hostname = hostname.strip()

        with self._lock:
            if not self._is_open_locked():
                refusal = "not_open"
            elif self._requests_by_ip.get(ip, 0) >= MAX_REQUESTS_PER_IP \
                    or self._failures_by_ip.get(ip, 0) >= MAX_FAILURES_PER_IP:
                refusal = "rate_limited"
            else:
                refusal = None
                self._requests_by_ip[ip] = self._requests_by_ip.get(ip, 0) + 1
                code = self._code
        if refusal:
            self._send(conn, {"type": "pair_result", "ok": False, "reason": refusal})
            if refusal == "not_open":
                self._on_event(f"Pairing request from {hostname} ({ip}) refused: no pairing window is open.")
            return

        key = proto.derive_key(code, master_cert_fingerprint())
        master_nonce = proto.new_nonce()
        self._send(conn, {
            "type": "pair_challenge",
            "nonce": master_nonce,
            "proof": proto.make_proof(key, "master", hostname, slave_nonce, master_nonce),
        })

        reply = self._read_message(conn, leftover)
        if reply is None:
            return  # slave rejected our proof (wrong code on its side) or hung up

        expected = proto.make_proof(key, "slave", hostname, slave_nonce, master_nonce)
        locked_out = False
        with self._lock:
            # The window may have been closed or reopened with a new code
            # while scrypt ran; only the code it was opened with counts.
            still_valid = self._is_open_locked() and self._code == code
            accepted = still_valid and proto.proofs_match(reply.get("proof"), expected)
            if not accepted and still_valid:
                self._failures_by_ip[ip] = self._failures_by_ip.get(ip, 0) + 1
                self._failures_total += 1
                if self._failures_total >= MAX_FAILURES_TOTAL:
                    self._reset_window(code=None, expires_at=0.0)
                    locked_out = True

        if not accepted:
            self._send(conn, {"type": "pair_result", "ok": False, "reason": "bad_code" if still_valid else "not_open"})
            self._on_event(f"Pairing attempt from {hostname} ({ip}) rejected: wrong code.")
            if locked_out:
                self._on_event("Pairing window closed: too many wrong codes. Open a new window to continue.")
            return

        token = proto.new_slave_token()
        db.set_slave_credential(hostname, proto.hash_token(token))
        self._send(conn, {"type": "pair_result", "ok": True, "token": token})
        with self._lock:
            if hostname not in self._paired_hosts:
                self._paired_hosts.append(hostname)
        self._on_event(f"Paired {hostname} ({ip}).")

    @staticmethod
    def _send(conn, message):
        try:
            conn.sendall((json.dumps(message) + "\n").encode("utf-8"))
        except OSError as e:
            logging.warning(f"Pairing: failed to send to slave: {e}")

    @staticmethod
    def _read_message(conn, buffer):
        conn.settimeout(_EXCHANGE_TIMEOUT_SECONDS)
        try:
            while b"\n" not in buffer:
                chunk = conn.recv(4096)
                if not chunk:
                    return None
                buffer += chunk
                if len(buffer) > _MAX_LINE_BYTES:
                    return None
            line = buffer.split(b"\n", 1)[0]
            message = json.loads(line.decode("utf-8"))
            return message if isinstance(message, dict) and message.get("type") == "pair_response" else None
        except (OSError, ValueError):
            return None
