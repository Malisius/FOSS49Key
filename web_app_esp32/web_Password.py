import network
import socket
import json
import os
import time
import hashlib
from machine import I2S, Pin
import crypto_helper

AP_SSID = "ESP32-KeyVault"
AP_PASS = "vault1234"
AUTH_FILE = "auth.json"
VAULT_ENC_FILE = "vault.enc"

# Hardware State
is_unlocked = False
active_aes_key = None

# --- I2S Voice Setup (ICS-43434) ---
# SCK -> GPIO 1, WS -> GPIO 2, SD -> GPIO 42
i2s = I2S(
    0,
    sck=Pin(1),
    ws=Pin(2),
    sd=Pin(42),
    mode=I2S.RX,
    bits=32,
    format=I2S.MONO,
    rate=16000,
    ibuf=1024
)

def get_auth_config():
    try:
        with open(AUTH_FILE, "r") as f:
            return json.load(f)
    except:
        return None

def set_auth_config(passphrase):
    key = crypto_helper.derive_key(passphrase)
    phash = hashlib.sha256(passphrase.encode()).hexdigest()
    with open(AUTH_FILE, "w") as f:
        json.dump({"hash": phash}, f)
    return key

def read_encrypted_vault():
    global active_aes_key
    if not active_aes_key:
        return []
    try:
        with open(VAULT_ENC_FILE, "rb") as f:
            raw = f.read()
        plaintext = crypto_helper.decrypt_data(raw, active_aes_key)
        return json.loads(plaintext)
    except Exception as e:
        print("Vault read error:", e)
        return []

def write_encrypted_vault(data):
    global active_aes_key
    if not active_aes_key:
        return False
    plaintext = json.dumps(data)
    ciphertext = crypto_helper.encrypt_data(plaintext, active_aes_key)
    with open(VAULT_ENC_FILE, "wb") as f:
        f.write(ciphertext)
    return True

# --- Web UI with Passphrase Gate ---
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KeyVault Pro</title>
  <style>
    body { font-family: sans-serif; background: #0f172a; color: #f8fafc; padding: 16px; margin: 0; }
    .card { background: #1e293b; border-radius: 10px; padding: 18px; max-width: 420px; margin: 0 auto 16px; }
    input { width: 100%; box-sizing: border-box; padding: 10px; border-radius: 6px; border: 1px solid #334155; background: #0f172a; color: #fff; margin: 6px 0; }
    button { width: 100%; padding: 10px; border: none; border-radius: 6px; background: #0284c7; color: white; font-weight: bold; cursor: pointer; margin-top: 10px; }
    .status { text-align: center; font-size: 0.85rem; color: #38bdf8; margin-bottom: 10px; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <div class="card" id="auth-card">
    <h2 id="auth-title">Unlock Vault</h2>
    <p class="status" id="auth-status">Enter passphrase or speak into microphone</p>
    <input id="master-pass" type="password" placeholder="Master Passphrase">
    <button onclick="handleAuth()">Submit</button>
  </div>

  <div class="card hidden" id="vault-card">
    <h2>Add Credential</h2>
    <input id="acc" placeholder="Account (e.g. GitHub)">
    <input id="pwd" type="password" placeholder="Password">
    <button onclick="saveItem()">Encrypt & Save</button>
    <h2 style="margin-top:20px;">Stored Accounts</h2>
    <div id="list">Loading...</div>
  </div>

<script>
  let isUnlocked = false;

  async function checkStatus() {
    const res = await fetch('/api/status');
    const data = await res.json();
    if (data.setup_required) {
      document.getElementById('auth-title').innerText = "Set Master Passphrase";
      document.getElementById('auth-status').innerText = "Create initial master key";
    } else if (data.unlocked) {
      showVault();
    }
  }

  async function handleAuth() {
    const pass = document.getElementById('master-pass').value;
    const res = await fetch('/api/login', { method: 'POST', body: JSON.stringify({ pass }) });
    const data = await res.json();
    if (data.status === 'ok') {
      showVault();
    } else {
      alert('Invalid Passphrase');
    }
  }

  function showVault() {
    document.getElementById('auth-card').classList.add('hidden');
    document.getElementById('vault-card').classList.remove('hidden');
    loadVault();
  }

  async function loadVault() {
    const res = await fetch('/api/list');
    const list = await res.json();
    const el = document.getElementById('list');
    el.innerHTML = list.length ? list.map(i => `<div style="padding:6px 0;"><strong>${i.account}</strong></div>`).join('') : 'Empty';
  }

  async function saveItem() {
    const account = document.getElementById('acc').value.trim();
    const password = document.getElementById('pwd').value;
    await fetch('/api/save', { method: 'POST', body: JSON.stringify({ account, password }) });
    document.getElementById('acc').value = '';
    document.getElementById('pwd').value = '';
    loadVault();
  }

  checkStatus();
  // Poll every 3 seconds in case voice unlocks the device
  setInterval(async () => {
    if (!isUnlocked) {
      const res = await fetch('/api/status');
      const d = await res.json();
      if (d.unlocked) showVault();
    }
  }, 3000);
</script>
</body>
</html>"""

# --- Network & Server Init ---
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid=AP_SSID, password=AP_PASS, authmode=network.AUTH_WPA2_PSK)
ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1'))

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 80))
s.listen(2)
s.setblocking(False)

print("Server online at http://192.168.4.1")

# Preallocated audio buffer for microphone polling
audio_buf = bytearray(512)

while True:
    # 1. Non-blocking Voice Passphrase Detection
    try:
        bytes_in = i2s.readinto(audio_buf)
        if bytes_in and not is_unlocked:
            # Measure peak audio volume
            peak = max(audio_buf)
            # Threshold detection: Replace with audio pattern or keyword verification
            if peak > 240:
                auth = get_auth_config()
                if auth:
                    print("Voice phrase detected! Unlocking...")
                    # Unlock session
                    is_unlocked = True
    except:
        pass

    # 2. Web Server Request Handling
    try:
        conn, addr = s.accept()
        conn.settimeout(2.0)
        req = conn.recv(1024).decode('utf-8')
        lines = req.split("\r\n")
        if not lines or not lines[0]:
            conn.close()
            continue

        method, path, _ = lines[0].split(" ")
        auth_conf = get_auth_config()

        if method == "GET" and (path == "/" or path == "/index.html"):
            conn.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
            conn.sendall(HTML_PAGE)

        elif method == "GET" and path == "/api/status":
            resp = json.dumps({"setup_required": auth_conf is None, "unlocked": is_unlocked})
            conn.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + resp)

        elif method == "POST" and path == "/api/login":
            body = json.loads(req[req.find("\r\n\r\n")+4:])
            entered_pass = body.get("pass", "")

            if auth_conf is None:
                # First time setup
                active_aes_key = set_auth_config(entered_pass)
                is_unlocked = True
                conn.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\"}")
            else:
                input_hash = hashlib.sha256(entered_pass.encode()).hexdigest()
                if input_hash == auth_conf["hash"]:
                    active_aes_key = crypto_helper.derive_key(entered_pass)
                    is_unlocked = True
                    conn.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\"}")
                else:
                    conn.send("HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\n\r\n{\"status\":\"fail\"}")

        elif method == "GET" and path == "/api/list":
            if not is_unlocked:
                conn.send("HTTP/1.1 403 Forbidden\r\n\r\n")
            else:
                vault = read_encrypted_vault()
                summary = [{"account": x["account"]} for x in vault]
                conn.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + json.dumps(summary))

        elif method == "POST" and path == "/api/save":
            if not is_unlocked:
                conn.send("HTTP/1.1 403 Forbidden\r\n\r\n")
            else:
                body = json.loads(req[req.find("\r\n\r\n")+4:])
                vault = read_encrypted_vault()
                vault = [i for i in vault if i["account"] != body["account"]]
                vault.append({"account": body["account"], "password": body["password"]})
                write_encrypted_vault(vault)
                conn.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"saved\"}")

        conn.close()
    except OSError:
        pass  # Socket timeout / non-blocking check
    except Exception as e:
        print("Server error:", e)
        try:
            conn.close()
        except:
            pass