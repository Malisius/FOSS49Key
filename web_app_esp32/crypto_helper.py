# crypto_helper.py
import ucryptolib
import hashlib
import os

BLOCK_SIZE = 16

def derive_key(passphrase: str) -> bytes:
    """Hash the passphrase using SHA-256 to produce a consistent 32-byte (AES-256) key."""
    return hashlib.sha256(passphrase.encode('utf-8')).digest()

def pad(data: bytes) -> bytes:
    """PKCS7 padding to 16-byte boundary."""
    pad_len = BLOCK_SIZE - (len(data) % BLOCK_SIZE)
    return data + bytes([pad_len] * pad_len)

def unpad(data: bytes) -> bytes:
    """Remove PKCS7 padding."""
    pad_len = data[-1]
    if pad_len > BLOCK_SIZE:
        raise ValueError("Invalid padding")
    return data[:-pad_len]

def encrypt_data(plaintext_str: str, key: bytes) -> bytes:
    """Encrypts plaintext string and prepends the random 16-byte IV."""
    iv = os.urandom(16)
    cipher = ucryptolib.aes(key, 2, iv) # Mode 2 = CBC
    padded = pad(plaintext_str.encode('utf-8'))
    encrypted = cipher.encrypt(padded)
    return iv + encrypted  # Prepend IV for storage

def decrypt_data(ciphertext: bytes, key: bytes) -> str:
    """Splits IV and decrypts the remaining payload."""
    if len(ciphertext) < 32:
        raise ValueError("Corrupted ciphertext")
    iv = ciphertext[:16]
    payload = ciphertext[16:]
    cipher = ucryptolib.aes(key, 2, iv)
    decrypted_padded = cipher.decrypt(payload)
    return unpad(decrypted_padded).decode('utf-8')