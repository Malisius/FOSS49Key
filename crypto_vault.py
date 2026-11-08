# crypto_vault.py
import hashlib
import binascii
import os
import json

try:
    import ucryptolib
except ImportError:
    # Fallback cipher for off-device desktop testing when ucryptolib is not present
    class _MockAES:
        def __init__(self, key, mode, iv):
            self.key = key
            self.iv = iv
        def encrypt(self, data):
            out = bytearray(data)
            for i in range(len(out)):
                out[i] ^= self.key[i % len(self.key)] ^ self.iv[i % len(self.iv)]
            return bytes(out)
        def decrypt(self, data):
            out = bytearray(data)
            for i in range(len(out)):
                out[i] ^= self.key[i % len(self.key)] ^ self.iv[i % len(self.iv)]
            return bytes(out)

    class _MockUcrypto:
        @staticmethod
        def aes(key, mode, iv):
            return _MockAES(key, mode, iv)

    ucryptolib = _MockUcrypto()

BLOCK_SIZE = 16
AUTH_FILE = "auth.json"
VAULT_FILE = "vault.enc"

def hash_hex(text: str) -> str:
    raw = hashlib.sha256(text.strip().lower().encode("utf-8")).digest()
    return binascii.hexlify(raw).decode()

def derive_key(passphrase: str) -> bytes:
    """Hash the passphrase using SHA-256 to produce a 32-byte (AES-256) key."""
    return hashlib.sha256(passphrase.strip().lower().encode("utf-8")).digest()

def pad(data: bytes) -> bytes:
    """PKCS7 padding to 16-byte boundary."""
    pad_len = BLOCK_SIZE - (len(data) % BLOCK_SIZE)
    return data + bytes([pad_len] * pad_len)

def unpad(data: bytes) -> bytes:
    """Remove PKCS7 padding."""
    if not data:
        raise ValueError("Empty data in unpad")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > BLOCK_SIZE:
        raise ValueError("Invalid padding")
    # Verify padding bytes
    if data[-pad_len:] != bytes([pad_len] * pad_len):
        raise ValueError("Invalid padding bytes")
    return data[:-pad_len]

def encrypt_data(plaintext_str: str, key: bytes) -> bytes:
    """Encrypts plaintext string and prepends the random 16-byte IV."""
    iv = os.urandom(16)
    cipher = ucryptolib.aes(key, 2, iv)  # Mode 2 = CBC
    padded = pad(plaintext_str.encode("utf-8"))
    encrypted = cipher.encrypt(padded)
    return iv + encrypted

def decrypt_data(ciphertext: bytes, key: bytes) -> str:
    """Splits IV and decrypts the remaining payload."""
    if len(ciphertext) < 32:
        raise ValueError("Corrupted ciphertext")
    iv = ciphertext[:16]
    payload = ciphertext[16:]
    cipher = ucryptolib.aes(key, 2, iv)
    decrypted_padded = cipher.decrypt(payload)
    return unpad(decrypted_padded).decode("utf-8")

class VaultManager:
    def __init__(self):
        self.is_unlocked = False
        self.active_key = None
        self.entries = []  # list of {"account": ..., "password": ...}
        self.load_if_unlocked()

    def is_configured(self) -> bool:
        try:
            os.stat(AUTH_FILE)
            return True
        except OSError:
            return False

    def get_auth_hash(self):
        try:
            with open(AUTH_FILE, "r") as f:
                data = json.load(f)
                return data.get("hash")
        except Exception:
            return None

    def setup_master_passphrase(self, passphrase: str):
        cleaned = passphrase.strip().lower()
        phash = hash_hex(cleaned)
        with open(AUTH_FILE, "w") as f:
            json.dump({"hash": phash}, f)
        self.active_key = derive_key(cleaned)
        self.is_unlocked = True
        self.entries = [
            {"account": "Example-Email", "password": "Password123!"},
            {"account": "Example-Work", "password": "CorrectHorseBatteryStaple49"}
        ]
        self.save_encrypted()
        return True

    def unlock(self, passphrase: str) -> bool:
        cleaned = passphrase.strip().lower()
        target_hash = self.get_auth_hash()

        if target_hash is None:
            # First time setup
            print("[Vault] Initializing vault with passphrase:", cleaned)
            return self.setup_master_passphrase(cleaned)

        test_hash = hash_hex(cleaned)
        if test_hash != target_hash:
            print("[Vault] Passphrase mismatch.")
            return False

        key = derive_key(cleaned)
        try:
            with open(VAULT_FILE, "rb") as f:
                raw = f.read()
            plaintext = decrypt_data(raw, key)
            self.entries = json.loads(plaintext)
            self.active_key = key
            self.is_unlocked = True
            print(f"[Vault] Unlocked successfully! Loaded {len(self.entries)} entries.")
            return True
        except Exception as e:
            print("[Vault] Decryption error:", e)
            return False

    def lock(self):
        self.is_unlocked = False
        self.active_key = None
        self.entries = []
        print("[Vault] Device locked. Memory purged.")

    def save_encrypted(self) -> bool:
        if not self.is_unlocked or not self.active_key:
            return False
        try:
            plaintext = json.dumps(self.entries)
            ciphertext = encrypt_data(plaintext, self.active_key)
            with open(VAULT_FILE, "wb") as f:
                f.write(ciphertext)
            return True
        except Exception as e:
            print("[Vault] Save error:", e)
            return False

    def list_accounts(self):
        if not self.is_unlocked:
            return []
        return [item["account"] for item in self.entries]

    def get_password(self, account: str):
        if not self.is_unlocked:
            return None
        for item in self.entries:
            if item["account"] == account:
                return item["password"]
        return None

    def set_credential(self, account: str, password: str):
        if not self.is_unlocked:
            return False
        # Update existing or append
        updated = False
        for item in self.entries:
            if item["account"] == account:
                item["password"] = password
                updated = True
                break
        if not updated:
            self.entries.append({"account": account, "password": password})
        return self.save_encrypted()

    def delete_credential(self, account: str):
        if not self.is_unlocked:
            return False
        self.entries = [i for i in self.entries if i["account"] != account]
        return self.save_encrypted()

    def load_if_unlocked(self):
        pass
