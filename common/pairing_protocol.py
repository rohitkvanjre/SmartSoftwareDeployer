"""Pairing protocol primitives shared by the master and the slave.

A slave pairs by proving it knows a short, time-limited code shown on the
master's screen. In return it receives its own long random token, which is
what authenticates it from then on. The code is never sent over the wire:
both sides derive a key from it and exchange HMAC proofs.

The master proves knowledge of the code FIRST, and its key is bound to its
TLS certificate fingerprint. The slave checks that proof against the
certificate it actually sees on the connection, so an impostor in the middle
(which presents a different certificate and doesn't know the code) is
detected before the slave reveals anything. The slave then pins that
fingerprint for all future connections.

scrypt makes each guess at the code expensive, so a captured proof can't be
brute-forced within the pairing window; the master separately limits online
guesses.
"""

import hashlib
import hmac
import secrets

# Crockford base32: no I, L, O, U, so codes can't be misread when typed.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8

_KDF_SALT_PREFIX = b"SmartSoftwareDeployer-pairing-v1|"
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1

NONCE_HEX_LENGTH = 64


def generate_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code):
    """Uppercases, drops separators, and maps commonly confused characters,
    returning None if the result isn't a well-formed code."""
    if not isinstance(code, str):
        return None
    cleaned = code.upper().replace("-", "").replace(" ", "")
    cleaned = cleaned.replace("O", "0").replace("I", "1").replace("L", "1")
    if len(cleaned) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in cleaned):
        return None
    return cleaned


def format_code(code):
    return f"{code[:4]}-{code[4:]}"


def cert_fingerprint(der_bytes):
    return hashlib.sha256(der_bytes).digest()


def derive_key(code, fingerprint):
    return hashlib.scrypt(
        code.encode("ascii"),
        salt=_KDF_SALT_PREFIX + fingerprint,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
    )


def make_proof(key, role, hostname, slave_nonce, master_nonce):
    message = "|".join((role, hostname, slave_nonce, master_nonce)).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def proofs_match(received, expected):
    return isinstance(received, str) and hmac.compare_digest(received, expected)


def new_nonce():
    return secrets.token_hex(NONCE_HEX_LENGTH // 2)


def is_valid_nonce(nonce):
    if not isinstance(nonce, str) or len(nonce) != NONCE_HEX_LENGTH:
        return False
    try:
        int(nonce, 16)
    except ValueError:
        return False
    return True


def new_slave_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
