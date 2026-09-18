# In master/auth.py
import os
import hashlib
import binascii
import hmac

# --- Configuration for Hashing ---
SALT_BYTES = 32
HASH_ROUNDS = 600000

def generate_salt():
    """Generates a cryptographically secure random salt and returns it as a hex string."""
    return binascii.hexlify(os.urandom(SALT_BYTES)).decode()

def hash_password(password: str, salt: str) -> str:
    """Hashes a password with the provided salt using PBKDF2-HMAC-SHA256."""
    pwd_bytes = password.encode('utf-8')
    salt_bytes = salt.encode('utf-8')
    hashed = hashlib.pbkdf2_hmac('sha256', pwd_bytes, salt_bytes, HASH_ROUNDS)
    return binascii.hexlify(hashed).decode()

def verify_password(provided_password: str, salt: str, stored_hash: str) -> bool:
    """Verifies a password against a stored salt and hash using a constant-time comparison."""
    return hmac.compare_digest(hash_password(provided_password, salt), stored_hash)