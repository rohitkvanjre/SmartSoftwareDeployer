"""Slave side of pairing (see common/pairing_protocol.py for the design).

The installer drops the code the admin typed into pairing_code.txt next to
the agent. On its next connection attempt, the agent moves the code into a
protected store, pairs with the master, and saves the token it receives plus
the master's certificate fingerprint. Every later connection is pinned to
that fingerprint, so a machine that merely answers the discovery broadcast
can't pose as the master.
"""

import hmac
import json
import logging
import os
import socket
import ssl
import subprocess
import sys
from datetime import datetime, timezone

from common import pairing_protocol as proto
from . import config

_FROZEN = getattr(sys, "frozen", False)
if _FROZEN:
    CREDENTIALS_DIR = os.path.join(os.environ.get("ProgramData"), "SoftwareDeployerAgent", "credentials")
else:
    CREDENTIALS_DIR = os.path.join(config.APP_ROOT, "credentials")
CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, "slave_credentials.json")
PENDING_CODE_FILE = os.path.join(CREDENTIALS_DIR, "pending_pairing_code.txt")
# Written by the installer (or `python -m slave --pair CODE`).
DROP_CODE_FILE = os.path.join(config.APP_ROOT, "pairing_code.txt")

_CONNECT_TIMEOUT_SECONDS = 30


class MasterIdentityError(Exception):
    """The server's certificate doesn't match the one pinned at pairing."""


def _ensure_credentials_dir():
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    if _FROZEN:
        # Only SYSTEM (S-1-5-18) and Administrators (S-1-5-32-544) may read
        # the token -- not the student logged on to this lab PC.
        subprocess.run(
            ["icacls", CREDENTIALS_DIR, "/inheritance:r",
             "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
            capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )


def load_credentials():
    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            creds = json.load(f)
    except (OSError, ValueError):
        return None
    if all(isinstance(creds.get(k), str) for k in ("token", "master_fingerprint")):
        return creds
    return None


def _save_credentials(token, fingerprint):
    _ensure_credentials_dir()
    creds = {
        "token": token,
        "master_fingerprint": fingerprint.hex(),
        "paired_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(creds, f)


def store_pairing_code(code):
    """Accepts a code from the installer drop file or the command line."""
    with open(DROP_CODE_FILE, "w", encoding="utf-8") as f:
        f.write(code)


def _take_pending_code():
    """Moves a freshly dropped code into the protected store (the drop file
    sits in a folder ordinary users can read) and returns whichever code is
    pending, or None."""
    if os.path.exists(DROP_CODE_FILE):
        try:
            with open(DROP_CODE_FILE, "r", encoding="utf-8") as f:
                dropped = f.read().strip()
            _ensure_credentials_dir()
            with open(PENDING_CODE_FILE, "w", encoding="utf-8") as f:
                f.write(dropped)
        finally:
            os.remove(DROP_CODE_FILE)
    try:
        with open(PENDING_CODE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _clear_pending_code():
    try:
        os.remove(PENDING_CODE_FILE)
    except FileNotFoundError:
        pass


def connect_to_master(master_ip, port, pinned_fingerprint_hex=None):
    """Opens a TLS connection and returns (socket, fingerprint). The master's
    certificate is self-signed, so trust comes from the pin (or, while
    pairing, from the master's proof), not from a CA."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((master_ip, port), timeout=_CONNECT_TIMEOUT_SECONDS)
    try:
        sock = context.wrap_socket(raw, server_hostname=master_ip)
    except Exception:
        raw.close()
        raise
    fingerprint = proto.cert_fingerprint(sock.getpeercert(binary_form=True))
    if pinned_fingerprint_hex is not None and not hmac.compare_digest(fingerprint.hex(), pinned_fingerprint_hex):
        sock.close()
        raise MasterIdentityError(
            f"The server at {master_ip} is not the master this PC was paired with "
            "(certificate mismatch). If the master was reinstalled, re-pair this PC."
        )
    return sock, fingerprint


def ensure_paired(master_ip, port):
    """Returns True once this PC holds valid credentials. A newly dropped
    code always triggers (re-)pairing, even if already paired."""
    if not os.path.exists(DROP_CODE_FILE) and not os.path.exists(PENDING_CODE_FILE):
        if load_credentials():
            return True
        logging.warning("This PC is not paired with a master. Re-run the slave installer with a pairing code "
                        "from the master's 'Pair New Slaves' screen.")
        return False

    raw_code = _take_pending_code()
    code = proto.normalize_code(raw_code) if raw_code else None
    if not code:
        logging.error("The pairing code given to the installer is not a valid code. Re-run the installer with "
                      "the code shown on the master.")
        _clear_pending_code()
        return load_credentials() is not None

    try:
        outcome = _pair(master_ip, port, code)
    except (OSError, ValueError) as e:
        logging.warning(f"Pairing with {master_ip} failed ({e}). Will retry.")
        return False

    if outcome == "paired":
        _clear_pending_code()
        logging.info(f"Paired with the master at {master_ip}.")
        return True
    if outcome in ("bad_code", "master_proof_failed"):
        # Definitive: retrying the same code can't succeed, and would burn
        # the master's limited guesses.
        _clear_pending_code()
        logging.error(
            "Pairing failed: the code is wrong or has expired"
            + (", or the server isn't the real master" if outcome == "master_proof_failed" else "")
            + ". Open a new pairing window on the master and re-run the installer with its code."
        )
    else:
        logging.warning(f"Pairing not completed ({outcome}). Will retry.")
    return load_credentials() is not None


def _pair(master_ip, port, code):
    hostname = socket.gethostname()
    slave_nonce = proto.new_nonce()
    sock, fingerprint = connect_to_master(master_ip, port)
    with sock:
        reader = sock.makefile("rb")
        _send(sock, {"type": "pair_request", "hostname": hostname, "nonce": slave_nonce})

        challenge = _read(reader)
        if challenge.get("type") == "pair_result":
            return challenge.get("reason", "refused")
        master_nonce = challenge.get("nonce")
        if challenge.get("type") != "pair_challenge" or not proto.is_valid_nonce(master_nonce):
            raise ValueError("unexpected reply from master")

        key = proto.derive_key(code, fingerprint)
        expected = proto.make_proof(key, "master", hostname, slave_nonce, master_nonce)
        if not proto.proofs_match(challenge.get("proof"), expected):
            # Either our code is wrong, or this isn't the master (its proof is
            # bound to a different certificate). Stop before revealing our
            # own proof, which an impostor could try to crack offline.
            return "master_proof_failed"

        _send(sock, {"type": "pair_response",
                     "proof": proto.make_proof(key, "slave", hostname, slave_nonce, master_nonce)})
        result = _read(reader)
        if result.get("type") != "pair_result":
            raise ValueError("unexpected reply from master")
        if not result.get("ok"):
            return result.get("reason", "refused")
        token = result.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("master sent no token")
        _save_credentials(token, fingerprint)
        return "paired"


def _send(sock, message):
    sock.sendall((json.dumps(message) + "\n").encode("utf-8"))


def _read(reader):
    line = reader.readline(4096)
    if not line:
        raise ConnectionError("master closed the connection")
    message = json.loads(line.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("malformed reply from master")
    return message
