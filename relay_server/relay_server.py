#!/usr/bin/env python3
"""
Foss49Key - Host Relay & Reverse Proxy Server
Bridges incoming domain/Tailscale connections to the ESP32-S3 Password Manager.
Supports direct Wi-Fi reverse-proxying and automatic USB Serial RPC fallback.
"""

import sys
import os
import json
import time
import socket
import urllib.request
import urllib.error
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import secrets

PORT = int(os.environ.get("RELAY_PORT", 8080))
ACTIVE_DEVICE = {
    "pin": None,
    "ip": None,
    "port": 80,
    "last_seen": 0,
    "registered_at": 0
}
SESSIONS = set()
WIFI_DIRECT_FAILED_UNTIL = 0

# Reverse Tunnel RPC state for remote ESP32 behind NAT/AP isolation
REVERSE_TUNNEL = {
    "queue": [],             # list of (req_id, method, path, body, Event, result_box)
    "replies": {},           # req_id -> (Event, result_box)
    "last_seen": 0,
    "lock": threading.Lock()
}

# Serial Bridge RPC Singleton
SERIAL_BRIDGE = None

PIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Foss49Key - Secure Access</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0b0f19;
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 16px;
    }
    .card {
      background: #151d30;
      border: 1px solid #23314d;
      border-radius: 16px;
      padding: 32px 24px;
      max-width: 400px;
      width: 100%;
      text-align: center;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    }
    h1 { font-size: 1.6rem; color: #60a5fa; margin-bottom: 8px; }
    p { font-size: 0.9rem; color: #94a3b8; margin-bottom: 24px; }
    .pin-inputs {
      display: flex;
      justify-content: center;
      gap: 10px;
      margin-bottom: 24px;
    }
    .pin-box {
      width: 50px;
      height: 58px;
      font-size: 1.8rem;
      text-align: center;
      border: 2px solid #23314d;
      border-radius: 10px;
      background: #0b1220;
      color: #fff;
      outline: none;
      transition: 0.2s border-color;
    }
    .pin-box:focus { border-color: #2563eb; }
    button {
      width: 100%;
      padding: 14px;
      border: none;
      border-radius: 10px;
      background: #2563eb;
      color: #fff;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: 0.2s background;
    }
    button:hover { background: #1d4ed8; }
    .status-msg {
      margin-top: 16px;
      font-size: 0.85rem;
      color: #ef4444;
      display: none;
    }
    .device-info {
      margin-top: 24px;
      font-size: 0.8rem;
      color: #64748b;
      border-top: 1px solid #1e293b;
      padding-top: 12px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Foss49Key Gate</h1>
    <p>Enter the 5-digit PIN shown on your unlocked hardware device.</p>
    
    <div class="pin-inputs" id="pin-container">
      <input class="pin-box" type="text" maxlength="1" inputmode="numeric" autofocus>
      <input class="pin-box" type="text" maxlength="1" inputmode="numeric">
      <input class="pin-box" type="text" maxlength="1" inputmode="numeric">
      <input class="pin-box" type="text" maxlength="1" inputmode="numeric">
      <input class="pin-box" type="text" maxlength="1" inputmode="numeric">
    </div>

    <button onclick="submitPin()">Connect to Device</button>
    <div class="status-msg" id="msg"></div>

    <div class="device-info" id="dev-status">
      Hardware Status: Checking...
    </div>
  </div>

<script>
  const boxes = document.querySelectorAll('.pin-box');
  boxes.forEach((box, idx) => {
    box.addEventListener('input', (e) => {
      if (box.value.length === 1 && idx < boxes.length - 1) {
        boxes[idx + 1].focus();
      }
      if (idx === boxes.length - 1 && box.value.length === 1) {
        submitPin();
      }
    });
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !box.value && idx > 0) {
        boxes[idx - 1].focus();
      }
      if (e.key === 'Enter') {
        submitPin();
      }
    });
  });

  async function updateStatus() {
    try {
      const res = await fetch('/relay/device_status');
      const d = await res.json();
      const el = document.getElementById('dev-status');
      if (d.registered) {
        el.innerHTML = `Hardware: Online (<span style="color:#22c55e;">${d.ip || 'USB Bridge'}</span>)`;
      } else {
        el.innerHTML = 'Hardware: Waiting for device PIN...';
      }
    } catch(e) {}
  }
  updateStatus();
  setInterval(updateStatus, 3000);

  async function submitPin() {
    let pin = '';
    boxes.forEach(b => pin += b.value);
    const msg = document.getElementById('msg');
    if (pin.length !== 5) {
      msg.innerText = 'Please enter all 5 digits';
      msg.style.display = 'block';
      return;
    }
    msg.style.display = 'none';

    try {
      const res = await fetch('/relay/verify_pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        window.location.reload();
      } else {
        msg.innerText = data.error || 'Invalid PIN. Check device display.';
        msg.style.display = 'block';
        boxes.forEach(b => b.value = '');
        boxes[0].focus();
      }
    } catch(e) {
      msg.innerText = 'Connection error: ' + e;
      msg.style.display = 'block';
    }
  }
</script>
</body>
</html>"""

PORTAL_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Foss49Key - Password Manager</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151d30;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --danger: #dc2626;
      --text: #f1f5f9;
      --subtext: #94a3b8;
      --border: #23314d;
      --success: #16a34a;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 16px; }
    .container { max-width: 520px; margin: 0 auto; }
    .header { text-align: center; margin-bottom: 20px; }
    .header h1 { font-size: 1.6rem; color: #60a5fa; margin-bottom: 4px; }
    .badge { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: bold; background: #1e3a8a; color: #93c5fd; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 18px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
    .card h2 { font-size: 1.15rem; margin-bottom: 12px; color: #cbd5e1; display: flex; justify-content: space-between; align-items: center; }
    label { display: block; font-size: 0.85rem; color: var(--subtext); margin-top: 8px; margin-bottom: 4px; }
    input, select { width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border); background: #0b1220; color: #fff; font-size: 0.95rem; outline: none; }
    input:focus, select:focus { border-color: var(--accent); }
    button { padding: 10px 16px; border: none; border-radius: 8px; background: var(--accent); color: #fff; font-weight: 600; font-size: 0.95rem; cursor: pointer; transition: 0.2s; margin-top: 10px; width: 100%; }
    button:hover { background: var(--accent-hover); }
    button.btn-danger { background: var(--danger); }
    button.btn-danger:hover { background: #b91c1c; }
    button.btn-secondary { background: #334155; }
    button.btn-secondary:hover { background: #475569; }
    .row { display: flex; gap: 8px; }
    .row button { width: auto; flex: 1; }
    .item-list { margin-top: 10px; display: flex; flex-direction: column; gap: 10px; }
    .item { background: #0d1527; border: 1px solid var(--border); border-radius: 8px; padding: 12px; display: flex; justify-content: space-between; align-items: center; }
    .item-info { flex: 1; min-width: 0; }
    .item-account { font-weight: 600; font-size: 1rem; color: #f8fafc; }
    .item-pass { font-family: monospace; font-size: 0.9rem; color: #94a3b8; margin-top: 4px; letter-spacing: 1px; }
    .actions { display: flex; gap: 6px; }
    .actions button { padding: 6px 10px; font-size: 0.8rem; margin: 0; width: auto; }
    .toast { text-align: center; font-size: 0.85rem; padding: 8px; border-radius: 6px; margin-bottom: 12px; display: none; }
    .toast-success { background: rgba(22, 163, 74, 0.2); color: #4ade80; border: 1px solid #16a34a; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Foss49Key Vault</h1>
      <span class="badge" id="dev-status">Hardware Connected</span>
    </div>

    <div class="toast toast-success" id="toast"></div>

    <!-- Add Credential Card -->
    <div class="card">
      <h2>Add New Credential</h2>
      <label>Account / Service Name</label>
      <input id="acc" placeholder="e.g. GitHub, Work Laptop, Email">
      <label>Password</label>
      <input id="pwd" type="password" placeholder="Enter secure password">
      <button onclick="saveItem()">Save to Encrypted Vault</button>
    </div>

    <!-- Stored Credentials Card -->
    <div class="card">
      <h2>Stored Passwords (<span id="count">0</span>)</h2>
      <div id="list" class="item-list">Loading vault entries...</div>
    </div>

    <!-- Wi-Fi Settings Card -->
    <div class="card">
      <h2>Wi-Fi Network Settings</h2>
      <label>Available Networks</label>
      <div class="row">
        <select id="wifi-select" onchange="onSelectNetwork()">
          <option value="">Scan for Wi-Fi networks...</option>
        </select>
        <button class="btn-secondary" onclick="scanWifi()" style="flex: 0 0 80px;">Scan</button>
      </div>
      <label>SSID</label>
      <input id="wifi-ssid" placeholder="Network Name (SSID)">
      <label>Password (leave blank for open networks)</label>
      <input id="wifi-pass" type="password" placeholder="Wi-Fi Password">
      <button onclick="saveWifi()">Update & Reconnect Wi-Fi</button>
    </div>

    <!-- Session Management Card -->
    <div class="card" style="text-align: center;">
      <button class="btn-danger" onclick="lockVault()">Lock Device & Disconnect</button>
    </div>
  </div>

<script>
  function showToast(msg) {
    const t = document.getElementById('toast');
    t.innerText = msg;
    t.style.display = 'block';
    setTimeout(() => { t.style.display = 'none'; }, 3000);
  }

  async function loadVault() {
    try {
      const res = await fetch('/api/list');
      const list = await res.json();
      document.getElementById('count').innerText = list.length;
      const el = document.getElementById('list');
      if (!list.length) {
        el.innerHTML = '<div style="color:var(--subtext); text-align:center; padding:12px;">No stored credentials yet.</div>';
        return;
      }
      el.innerHTML = list.map((item, idx) => `
        <div class="item">
          <div class="item-info">
            <div class="item-account">${escapeHtml(item.account)}</div>
            <div class="item-pass" id="pwd-${idx}">••••••••••••</div>
          </div>
          <div class="actions">
            <button class="btn-secondary" onclick="togglePass(${idx}, '${escapeHtml(item.password)}')">Show</button>
            <button class="btn-danger" onclick="deleteItem('${escapeHtml(item.account)}')">Delete</button>
          </div>
        </div>
      `).join('');
    } catch(e) {
      document.getElementById('list').innerHTML = '<div style="color:var(--danger)">Error loading vault</div>';
    }
  }

  function togglePass(idx, actualPassword) {
    const el = document.getElementById('pwd-' + idx);
    if (el.innerText === '••••••••••••') {
      el.innerText = actualPassword;
      el.style.color = '#38bdf8';
    } else {
      el.innerText = '••••••••••••';
      el.style.color = '#94a3b8';
    }
  }

  async function saveItem() {
    const account = document.getElementById('acc').value.trim();
    const password = document.getElementById('pwd').value;
    if (!account || !password) {
      alert('Please enter both account and password');
      return;
    }
    await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account, password })
    });
    document.getElementById('acc').value = '';
    document.getElementById('pwd').value = '';
    showToast('Credential encrypted and saved!');
    loadVault();
  }

  async function deleteItem(account) {
    if (!confirm('Are you sure you want to delete ' + account + '?')) return;
    await fetch('/api/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account })
    });
    showToast('Deleted ' + account);
    loadVault();
  }

  async function scanWifi() {
    const sel = document.getElementById('wifi-select');
    sel.innerHTML = '<option>Scanning...</option>';
    try {
      const res = await fetch('/api/wifi/scan');
      const networks = await res.json();
      sel.innerHTML = '<option value="">Select a network...</option>' +
        networks.map(n => `<option value="${escapeHtml(n.ssid)}">${escapeHtml(n.ssid)} (${n.auth})</option>`).join('');
    } catch(e) {
      sel.innerHTML = '<option>Scan failed</option>';
    }
  }

  function onSelectNetwork() {
    const sel = document.getElementById('wifi-select');
    if (sel.value) {
      document.getElementById('wifi-ssid').value = sel.value;
    }
  }

  async function saveWifi() {
    const ssid = document.getElementById('wifi-ssid').value.trim();
    const password = document.getElementById('wifi-pass').value;
    if (!ssid) {
      alert('SSID cannot be empty');
      return;
    }
    await fetch('/api/wifi', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ssid, password })
    });
    showToast('Wi-Fi settings saved. Device reconnecting...');
  }

  async function lockVault() {
    if (!confirm('Lock device and shut down server?')) return;
    await fetch('/api/lock', { method: 'POST' });
    document.body.innerHTML = '<div style="text-align:center; padding:40px; color:#cbd5e1;"><h2>Device Locked</h2><p>Web portal disconnected.</p></div>';
  }

  function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  loadVault();
</script>
</body>
</html>"""

def find_esp32_port(preferred_port=None):
    """Finds the active ESP32 serial port dynamically across ACM0/ACM1 renumbering."""
    if preferred_port and os.path.exists(preferred_port):
        return preferred_port
    by_id = "/dev/serial/by-id"
    if os.path.isdir(by_id):
        try:
            for entry in os.listdir(by_id):
                return os.path.realpath(os.path.join(by_id, entry))
        except Exception:
            pass
    for candidate in ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyACM2", "/dev/ttyUSB0", "/dev/ttyUSB1"]:
        if os.path.exists(candidate):
            return candidate
    return preferred_port or "/dev/ttyACM0"

class SerialRPCBridge:
    def __init__(self, serial_port=None):
        self.serial_port = serial_port
        self.ser = None
        self.lock = threading.Lock()
        self.pending = {}  # req_id -> (Event, result_tuple)
        self.running = True
        self.t = threading.Thread(target=self._worker, daemon=True)
        self.t.start()

    def _worker(self):
        try:
            import serial
        except ImportError:
            print("[Serial Bridge] pyserial not available.")
            return

        while self.running:
            try:
                active_port = find_esp32_port(self.serial_port)
                if os.path.exists(active_port):
                    s = serial.Serial()
                    s.port = active_port
                    s.baudrate = 115200
                    s.timeout = 0.5
                    s.dtr = False
                    s.rts = False
                    s.open()
                    self.ser = s
                    print(f"[Serial Bridge] Connected to {active_port}")
                    while self.running:
                        line = s.readline().decode("utf-8", "ignore").strip()
                        if line:
                            # 1. PIN broadcast
                            if "[RELAY_PIN:" in line:
                                parts = line.split("[RELAY_PIN:")[1].split("]")[0].split(":")
                                if len(parts) >= 2:
                                    ACTIVE_DEVICE["pin"] = parts[0]
                                    ACTIVE_DEVICE["ip"] = parts[1]
                                    if len(parts) >= 3:
                                        ACTIVE_DEVICE["port"] = int(parts[2])
                                    ACTIVE_DEVICE["last_seen"] = time.time()
                                    print(f"\n>>> [AUTO-DETECT] Active PIN {ACTIVE_DEVICE['pin']} registered from ESP32 ({ACTIVE_DEVICE['ip']}) <<<\n")

                            # 2. Serial RPC Response: [SERIAL_RESP:id:status:content_type:body]
                            elif "[SERIAL_RESP:" in line and line.endswith("]"):
                                start_idx = line.find("[SERIAL_RESP:") + len("[SERIAL_RESP:")
                                content = line[start_idx:-1]
                                parts = content.split(":", 3)
                                if len(parts) >= 3:
                                    req_id = parts[0]
                                    status = int(parts[1])
                                    ct = parts[2]
                                    body = parts[3] if len(parts) > 3 else ""
                                    with self.lock:
                                        if req_id in self.pending:
                                            evt, _ = self.pending[req_id]
                                            self.pending[req_id] = (evt, (status, ct, body))
                                            evt.set()
                    try:
                        s.close()
                    except Exception:
                        pass
            except Exception as e:
                self.ser = None
            time.sleep(2.0)

    def send_rpc(self, method: str, path: str, body: str = ""):
        """Sends an RPC request across USB serial and waits up to 2.5s for response."""
        req_id = secrets.token_hex(4)
        evt = threading.Event()
        with self.lock:
            if not self.ser:
                return None
            self.pending[req_id] = (evt, None)
            cmd = f"[SERIAL_REQ:{req_id}:{method}:{path}:{body}]\r\n"
            try:
                self.ser.write(cmd.encode("utf-8"))
                self.ser.flush()
            except Exception as e:
                print("[Serial Bridge] Send error:", e)
                del self.pending[req_id]
                return None

        # Wait for reply
        if evt.wait(timeout=2.5):
            with self.lock:
                _, res = self.pending.pop(req_id, (None, None))
                return res

        with self.lock:
            self.pending.pop(req_id, None)
        return None

class RelayHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {args[0]}\n")

    def get_session_token(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("foss_session="):
                return part.split("=", 1)[1]
        return None

    def is_authenticated(self):
        token = self.get_session_token()
        return token in SESSIONS

    def do_GET(self):
        # 1. Reverse RPC poll from remote ESP32
        if self.path.startswith("/relay/poll_rpc"):
            self.handle_poll_rpc()
            return

        # 2. Device status query (unauthenticated)
        if self.path == "/relay/device_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "registered": ACTIVE_DEVICE["pin"] is not None,
                "ip": ACTIVE_DEVICE["ip"],
                "last_seen": ACTIVE_DEVICE["last_seen"]
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        # 3. Check if authenticated session exists
        if not self.is_authenticated():
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PIN_PAGE_HTML.encode("utf-8"))
            return

        # 4. Authenticated root page -> serve responsive web app directly
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PORTAL_PAGE_HTML.encode("utf-8"))
            return

        # 5. Proxy API GET requests
        self.proxy_request("GET")

    def handle_poll_rpc(self):
        with REVERSE_TUNNEL["lock"]:
            REVERSE_TUNNEL["last_seen"] = time.time()
            if REVERSE_TUNNEL["queue"]:
                req_id, method, path, body, evt, res_box = REVERSE_TUNNEL["queue"].pop(0)
                body_dict = {}
                if body and body.startswith("{"):
                    try:
                        body_dict = json.loads(body)
                    except Exception:
                        pass
                cmd = {
                    "id": req_id,
                    "method": method,
                    "path": path,
                    "body": body_dict
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(cmd).encode("utf-8"))
                return

        # No pending command
        self.send_response(204)
        self.end_headers()

    def handle_reply_rpc(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8", "ignore")
        try:
            data = json.loads(body)
            req_id = data.get("id")
            status = int(data.get("status", 200))
            ct = data.get("content_type", "application/json")
            resp_body = data.get("body", "")

            with REVERSE_TUNNEL["lock"]:
                if req_id in REVERSE_TUNNEL["replies"]:
                    evt, box = REVERSE_TUNNEL["replies"][req_id]
                    box[0] = (status, ct, resp_body)
                    evt.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def do_POST(self):
        # 0. Reverse RPC reply from remote ESP32
        if self.path == "/relay/reply_rpc":
            self.handle_reply_rpc()
            return

        # 1. Registration endpoint for ESP32
        if self.path == "/api/register" or self.path == "/relay/register":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8", "ignore")
            try:
                data = json.loads(body)
                ACTIVE_DEVICE["pin"] = str(data.get("pin", "")).strip()
                ACTIVE_DEVICE["ip"] = data.get("ip", self.client_address[0])
                ACTIVE_DEVICE["port"] = int(data.get("port", 80))
                ACTIVE_DEVICE["last_seen"] = time.time()
                ACTIVE_DEVICE["registered_at"] = time.time()
                print(f"[Relay] Registered device: PIN={ACTIVE_DEVICE['pin']} IP={ACTIVE_DEVICE['ip']}:{ACTIVE_DEVICE['port']}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"registered"}')
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
            return

        # 2. PIN verification endpoint
        if self.path == "/relay/verify_pin":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8", "ignore")
            try:
                data = json.loads(body)
                entered_pin = str(data.get("pin", "")).strip()
                correct_pin = ACTIVE_DEVICE.get("pin")

                if not correct_pin:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"error","error":"No device has generated a PIN yet. Start web server on device."}')
                    return

                if entered_pin == correct_pin:
                    token = secrets.token_hex(16)
                    SESSIONS.add(token)
                    print(f"[Relay] PIN verified successfully! Session granted.")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Set-Cookie", f"foss_session={token}; Path=/; HttpOnly")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"error","error":"Incorrect PIN"}')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
            return

        # 3. Authenticated: Proxy POST request to ESP32
        if not self.is_authenticated():
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"Unauthorized"}')
            return

        self.proxy_request("POST")

    def proxy_request(self, method):
        global WIFI_DIRECT_FAILED_UNTIL
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        body_str = body_bytes.decode("utf-8", "ignore")

        target_ip = ACTIVE_DEVICE.get("ip")
        target_port = ACTIVE_DEVICE.get("port", 80)
        now = time.time()

        # 1. Priority 1: USB Serial RPC Bridge if hardware connected to this machine
        if SERIAL_BRIDGE and SERIAL_BRIDGE.ser:
            res = SERIAL_BRIDGE.send_rpc(method, self.path, body_str)
            if res:
                status, ct, resp_str = res
                resp_bytes = resp_str.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
                return

        # 2. Priority 2: Reverse RPC Tunnel if remote ESP32 polled recently (bypasses AP isolation)
        if now - REVERSE_TUNNEL["last_seen"] < 15.0:
            req_id = secrets.token_hex(4)
            evt = threading.Event()
            res_box = [None]
            with REVERSE_TUNNEL["lock"]:
                REVERSE_TUNNEL["replies"][req_id] = (evt, res_box)
                REVERSE_TUNNEL["queue"].append((req_id, method, self.path, body_str, evt, res_box))

            # Wait for remote ESP32 to poll and reply (up to 4.5s)
            if evt.wait(timeout=4.5):
                with REVERSE_TUNNEL["lock"]:
                    REVERSE_TUNNEL["replies"].pop(req_id, None)
                if res_box[0]:
                    status, ct, resp_str = res_box[0]
                    resp_bytes = resp_str.encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", str(len(resp_bytes)))
                    self.end_headers()
                    self.wfile.write(resp_bytes)
                    return
            else:
                with REVERSE_TUNNEL["lock"]:
                    REVERSE_TUNNEL["replies"].pop(req_id, None)

        # 3. Priority 3: Direct Wi-Fi HTTP proxy (with short 0.6s timeout) if not marked broken
        if target_ip and target_ip != "0.0.0.0" and now >= WIFI_DIRECT_FAILED_UNTIL:
            target_url = f"http://{target_ip}:{target_port}{self.path}"
            req_headers = {}
            for h, v in self.headers.items():
                if h.lower() not in ["host", "content-length", "cookie"]:
                    req_headers[h] = v

            try:
                req = urllib.request.Request(target_url, data=body_bytes if method == "POST" else None, headers=req_headers, method=method)
                with urllib.request.urlopen(req, timeout=0.6) as resp:
                    resp_data = resp.read()
                    self.send_response(resp.status)
                    for h, v in resp.headers.items():
                        if h.lower() not in ["content-length", "transfer-encoding"]:
                            self.send_header(h, v)
                    self.send_header("Content-Length", str(len(resp_data)))
                    self.end_headers()
                    self.wfile.write(resp_data)
                    return
            except Exception as e:
                # Wi-Fi blocked by campus AP isolation; mark broken for 60s
                WIFI_DIRECT_FAILED_UNTIL = now + 60.0
                pass

        # 4. Failure fallback
        self.send_response(502)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"ESP32 unreachable: USB serial disconnected, reverse tunnel idle, and direct Wi-Fi blocked by AP isolation."}')

def get_tailscale_ip():
    try:
        import subprocess
        out = subprocess.check_output(["tailscale", "ip", "-4"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return None

def main():
    global SERIAL_BRIDGE

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        ACTIVE_DEVICE["pin"] = sys.argv[1]
        print(f"[Relay] Set initial PIN from argument: {ACTIVE_DEVICE['pin']}")
    if len(sys.argv) > 2 and not sys.argv[2].startswith("-"):
        ACTIVE_DEVICE["ip"] = sys.argv[2]
        print(f"[Relay] Set initial IP from argument: {ACTIVE_DEVICE['ip']}")

    # Start Serial Bridge RPC with dynamic port auto-discovery
    SERIAL_BRIDGE = SerialRPCBridge()

    ts_ip = get_tailscale_ip() or "100.93.205.66"
    server = HTTPServer(("0.0.0.0", PORT), RelayHTTPHandler)

    print("\n" + "=" * 65)
    print(" Foss49Key - Host Relay & Reverse Proxy Gateway")
    print("=" * 65)
    print(f" Local Port       : {PORT}")
    print(f" Tailscale Access : http://{ts_ip}:{PORT}")
    print(f" Local Machine    : http://127.0.0.1:{PORT}")
    print(" Active Modes     : Wi-Fi Proxy + USB Serial RPC Bridge")
    print("=" * 65 + "\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Relay] Server shutting down.")
        server.server_close()

if __name__ == "__main__":
    main()
