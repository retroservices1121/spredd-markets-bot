"""
Encryption utilities for secure wallet storage.
Uses AES-256-GCM with PBKDF2 key derivation for user-specific encryption.
"""

import hashlib
import os
import secrets
from typing import Tuple

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


# Constants
SALT_LENGTH = 16
NONCE_LENGTH = 12
KEY_LENGTH = 32
ITERATIONS = 100_000


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


def derive_user_key(
    master_key: bytes,
    user_id: int,
    salt: bytes,
    user_pin: str = "",
) -> bytes:
    """
    Derive a user-specific encryption key from master key and optional PIN.
    This ensures each user's data is encrypted with a unique key that
    only they can decrypt (if PIN is used).

    Args:
        master_key: The application master encryption key
        user_id: Unique user identifier
        salt: Random salt for key derivation
        user_pin: Optional user PIN for non-custodial security

    Returns:
        32-byte derived key
    """
    # Combine master key with user ID and PIN
    # If PIN is provided, even with master_key + DB access, attacker can't decrypt
    key_material = master_key + str(user_id).encode() + user_pin.encode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=ITERATIONS,
        backend=default_backend(),
    )

    return kdf.derive(key_material)


def encrypt(plaintext: bytes, master_key: str, user_id: int, user_pin: str = "") -> str:
    """
    Encrypt data with user-specific key derivation.

    Args:
        plaintext: Data to encrypt
        master_key: 64-character hex master key
        user_id: User identifier for key derivation
        user_pin: Optional user PIN for non-custodial encryption

    Returns:
        Hex-encoded encrypted data (salt + nonce + ciphertext)
    """
    try:
        master_key_bytes = bytes.fromhex(master_key)

        # Generate random salt and nonce
        salt = os.urandom(SALT_LENGTH)
        nonce = os.urandom(NONCE_LENGTH)

        # Derive user-specific key (includes PIN if provided)
        derived_key = derive_user_key(master_key_bytes, user_id, salt, user_pin)

        # Encrypt with AES-GCM
        aesgcm = AESGCM(derived_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        # Combine: salt + nonce + ciphertext
        encrypted = salt + nonce + ciphertext

        return encrypted.hex()

    except Exception as e:
        raise EncryptionError(f"Encryption failed: {e}")


def decrypt(encrypted_hex: str, master_key: str, user_id: int, user_pin: str = "") -> bytes:
    """
    Decrypt data with user-specific key derivation.

    Args:
        encrypted_hex: Hex-encoded encrypted data
        master_key: 64-character hex master key
        user_id: User identifier for key derivation
        user_pin: User PIN used during encryption (required if PIN was used)

    Returns:
        Decrypted plaintext bytes

    Raises:
        EncryptionError: If decryption fails (wrong PIN or corrupted data)
    """
    try:
        master_key_bytes = bytes.fromhex(master_key)
        encrypted = bytes.fromhex(encrypted_hex)

        # Extract components
        salt = encrypted[:SALT_LENGTH]
        nonce = encrypted[SALT_LENGTH:SALT_LENGTH + NONCE_LENGTH]
        ciphertext = encrypted[SALT_LENGTH + NONCE_LENGTH:]

        # Derive user-specific key (includes PIN if provided)
        derived_key = derive_user_key(master_key_bytes, user_id, salt, user_pin)

        # Decrypt with AES-GCM
        aesgcm = AESGCM(derived_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        return plaintext

    except Exception as e:
        raise EncryptionError(f"Decryption failed: {e}")


def generate_encryption_key() -> str:
    """Generate a new 64-character hex encryption key."""
    return secrets.token_hex(32)


def validate_encryption_key(key: str) -> bool:
    """Validate that an encryption key is properly formatted."""
    if len(key) != 64:
        return False
    try:
        bytes.fromhex(key)
        return True
    except ValueError:
        return False


def hash_data(data: bytes) -> str:
    """Create a SHA-256 hash of data."""
    return hashlib.sha256(data).hexdigest()
