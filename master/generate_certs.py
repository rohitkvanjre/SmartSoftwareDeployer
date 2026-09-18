"""
generate_certs.py
==================

Reusable helper that (re)generates the TLS certificate used by the
Smart Software Deployer master. Pure Python (the `cryptography` library,
already a bundled dependency) -- no external `openssl` executable required,
so it works unmodified inside a PyInstaller-frozen build on a bare machine
that has never had OpenSSL installed.

What it does:
  1. Detects this machine's current local IPv4 addresses using only the
     Python standard library (socket module), with a fallback to parsing
     `ipconfig` output if the socket-based approach yields nothing useful.
  2. Generates a fresh self-signed RSA-2048 certificate + private key
     (master/data/cert.pem, master/data/key.pem) whose Subject Alternative
     Names cover the detected IPs/hostname, so the certificate validates
     for this machine's real network address.
  3. Writes master/data/cert.conf purely as a human-readable record of what
     was generated (kept for backward compatibility / operator reference;
     it is no longer fed to any external tool).

ensure_certs_exist() is the entry point meant to be called automatically
and silently at application startup (see master/app.py) -- it only
generates a new cert/key pair if they don't already exist, so it never
overwrites a real deployment's existing certificate on every launch.
"""

from __future__ import annotations

import datetime
import ipaddress
import re
import socket
import subprocess
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# ---------------------------------------------------------------------------
# Paths (frozen-exe aware, matching the pattern used in master/config.py)
# ---------------------------------------------------------------------------

import os

# NOTE: mirrors master/config.py's MASTER_DIR calculation exactly (kept as a
# separate copy, not an import, so this script still works when run
# standalone via "python master/generate_certs.py" with no package context).
# If you change one, change the other.
if getattr(sys, "frozen", False):
    _BASE_PATH = Path(os.environ.get("ProgramData", str(Path(sys.executable).resolve().parent))) / "SmartSoftwareDeployer" / "Master"
else:
    _BASE_PATH = Path(__file__).resolve().parent

MASTER_DATA_DIR = _BASE_PATH / "data"
CERT_CONF_PATH = MASTER_DATA_DIR / "cert.conf"
KEY_PATH = MASTER_DATA_DIR / "key.pem"
CERT_PATH = MASTER_DATA_DIR / "cert.pem"

# ---------------------------------------------------------------------------
# Step 1: detect local IPv4 addresses (stdlib only)
# ---------------------------------------------------------------------------


def _detect_ips_via_socket() -> list[str]:
    """Try socket.gethostname() + socket.getaddrinfo() to enumerate IPv4s."""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except socket.gaierror:
        pass
    return ips


def _detect_ips_via_ipconfig() -> list[str]:
    """Fallback: shell out to `ipconfig` and regex-parse IPv4 Address lines."""
    ips: list[str] = []
    try:
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout
    except (OSError, subprocess.SubprocessError):
        return ips

    # The label itself is localized by Windows (e.g. German "IPv4-Adresse",
    # French "Adresse IPv4"), so match on the "IPv4" substring -- which
    # ipconfig keeps in every locale -- rather than the full English label.
    for line in output.splitlines():
        if "ipv4" not in line.lower():
            continue
        match = re.search(r":\s*(\d{1,3}(?:\.\d{1,3}){3})", line)
        if match:
            ip = match.group(1).strip()
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    return ips


def detect_local_ipv4_addresses() -> list[str]:
    """Detect this machine's local IPv4 addresses (excluding loopback)."""
    ips = _detect_ips_via_socket()
    if not ips:
        ips = _detect_ips_via_ipconfig()
    return ips


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


# ---------------------------------------------------------------------------
# Step 2: build the self-signed cert + key with cryptography (no openssl)
# ---------------------------------------------------------------------------


def _build_san(ip_list: list[str], dns_list: list[str]) -> x509.SubjectAlternativeName:
    entries = []
    for ip in ip_list:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue
    for dns in dns_list:
        entries.append(x509.DNSName(dns))
    return x509.SubjectAlternativeName(entries)


def generate_self_signed_cert(ip_list: list[str], dns_list: list[str], cn: str) -> tuple[bytes, bytes]:
    """Returns (cert_pem_bytes, key_pem_bytes) for a fresh self-signed cert."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "KA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Attibele"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MyOrg"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(_build_san(ip_list, dns_list), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def _write_cert_conf_record(ip_list: list[str], dns_list: list[str], cn: str) -> None:
    """Writes a human-readable record of the SAN entries used. Not consumed
    by any tool anymore -- kept only for operator reference/debugging."""
    alt_lines = [f"IP.{i} = {ip}" for i, ip in enumerate(ip_list, start=1)]
    alt_lines += [f"DNS.{i} = {dns}" for i, dns in enumerate(dns_list, start=1)]
    conf_text = (
        "# Informational record of the last certificate generated by generate_certs.py.\n"
        "# This file is no longer read by any tool (cert generation is pure Python).\n"
        f"CN = {cn}\n" + "\n".join(alt_lines) + "\n"
    )
    MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    CERT_CONF_PATH.write_text(conf_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def generate_certs(force: bool = False) -> dict:
    """Generates master/data/cert.pem + key.pem for this machine.

    If force is False and both files already exist, does nothing and
    returns immediately (safe to call unconditionally at app startup).
    Returns a summary dict of what was detected/generated.
    """
    if not force and CERT_PATH.exists() and KEY_PATH.exists():
        return {"generated": False, "reason": "cert/key already exist"}

    detected_ips = detect_local_ipv4_addresses()

    ip_list: list[str] = []
    for ip in detected_ips:
        if ip not in ip_list:
            ip_list.append(ip)
    if "127.0.0.1" not in ip_list:
        ip_list.append("127.0.0.1")

    hostname = get_hostname()
    dns_list: list[str] = ["localhost"]
    if hostname and hostname.lower() != "localhost" and hostname not in dns_list:
        dns_list.append(hostname)

    cn = detected_ips[0] if detected_ips else "localhost"

    cert_pem, key_pem = generate_self_signed_cert(ip_list, dns_list, cn)

    MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    CERT_PATH.write_bytes(cert_pem)
    KEY_PATH.write_bytes(key_pem)
    _write_cert_conf_record(ip_list, dns_list, cn)

    return {
        "generated": True,
        "ip_list": ip_list,
        "dns_list": dns_list,
        "cn": cn,
        "detected_ips_empty": not detected_ips,
        "cert_path": str(CERT_PATH),
        "key_path": str(KEY_PATH),
    }


def ensure_certs_exist() -> dict:
    """Idempotent, silent, safe-to-call-on-every-startup entry point."""
    return generate_certs(force=False)


# ---------------------------------------------------------------------------
# CLI entry point (manual/forced regeneration, e.g. after a network change)
# ---------------------------------------------------------------------------


def main() -> int:
    result = generate_certs(force=True)
    print("Detected local IPv4 addresses:", result.get("ip_list"))
    print("Detected hostname:", get_hostname())
    if result.get("detected_ips_empty"):
        print(
            "WARNING: could not detect any real local IPv4 address. The "
            "generated certificate's SAN list will only cover 127.0.0.1/"
            "localhost and may fail TLS verification for this machine's "
            "real network address."
        )
    print()
    print(f"Generated {KEY_PATH}")
    print(f"Generated {CERT_PATH}")
    print()
    print("=== Summary: SAN entries used ===")
    for i, ip in enumerate(result.get("ip_list", []), start=1):
        print(f"  IP.{i} = {ip}")
    for i, dns in enumerate(result.get("dns_list", []), start=1):
        print(f"  DNS.{i} = {dns}")
    print(f"  CN = {result.get('cn')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
