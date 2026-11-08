# esp_webserver.py
# Embedded HTTP server for ESP32 password management and Wi-Fi configuration
# Supports both Wi-Fi socket requests and USB serial bridge RPC

import socket
import json
import time
import gc
import sys

try:
    import urandom
except ImportError:
    import random as urandom

HTML_TEMPLATE = """<!DOCTYPE html>
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

RELAY_CONFIG_FILE = "relay_config.json"
DEFAULT_RELAY_HOST = "10.103.150.76"
DEFAULT_RELAY_PORT = 8080

class ESPWebServer:
    def __init__(self, vault, wifi_mgr, port=80):
        self.vault = vault
        self.wifi_mgr = wifi_mgr
        self.port = port
        self.pin = self.generate_pin()
        self.sock = None
        self.is_running = False
        self.relay_host, self.relay_port = self._load_relay_config()
        self.last_rpc_poll = 0

    def _load_relay_config(self):
        try:
            with open(RELAY_CONFIG_FILE, "r") as f:
                c = json.load(f)
                return c.get("relay_host", DEFAULT_RELAY_HOST), int(c.get("relay_port", DEFAULT_RELAY_PORT))
        except Exception:
            return DEFAULT_RELAY_HOST, DEFAULT_RELAY_PORT

    def save_relay_config(self, host, port=8080):
        self.relay_host = host
        self.relay_port = int(port)
        try:
            with open(RELAY_CONFIG_FILE, "w") as f:
                json.dump({"relay_host": host, "relay_port": self.relay_port}, f)
            print(f"[Webserver] Saved relay config: {host}:{port}")
            return True
        except Exception as e:
            print("[Webserver] Save relay config error:", e)
            return False

    def generate_pin(self) -> str:
        # Generates a random 5-digit PIN between 10000 and 99999
        return str(urandom.randint(10000, 99999))

    def start(self, relay_url=None):
        if self.is_running:
            return self.pin

        self.pin = self.generate_pin()
        ip = self.wifi_mgr.get_ip()
        print(f"\n==========================================")
        print(f"[Webserver] STARTING ON {ip}:{self.port}")
        print(f"[Webserver] 5-DIGIT PIN: {self.pin}")
        print(f"[RELAY_PIN:{self.pin}:{ip}:{self.port}]")
        print(f"==========================================\n")

        # Phone home to host relay over Wi-Fi
        self._phone_home_to_relay()

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("0.0.0.0", self.port))
            self.sock.listen(3)
            self.sock.setblocking(False)
            self.is_running = True
            print(f"[Webserver] Listening on port {self.port}...")
            return self.pin
        except Exception as e:
            print("[Webserver] Bind note:", e)
            self.is_running = True
            return self.pin

    def _phone_home_to_relay(self):
        """Attempts to register active PIN and IP with the relay server over Wi-Fi."""
        if not self.wifi_mgr.is_connected():
            return False

        payload = json.dumps({
            "pin": self.pin,
            "ip": self.wifi_mgr.get_ip(),
            "port": self.port
        })
        print(f"[Webserver] Phoning home to relay at http://{self.relay_host}:{self.relay_port}/relay/register...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.5)
            addr = socket.getaddrinfo(self.relay_host, self.relay_port)[0][-1]
            s.connect(addr)
            req = (
                f"POST /relay/register HTTP/1.1\r\n"
                f"Host: {self.relay_host}:{self.relay_port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{payload}"
            )
            s.sendall(req.encode("utf-8"))
            s.recv(256)
            s.close()
            print("[Webserver] Successfully phoned home and registered PIN with relay server!")
            return True
        except Exception as e:
            print(f"[Webserver] Phone-home note ({self.relay_host}:{self.relay_port}):", e)
            return False

    def stop(self):
        self.is_running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        print("[Webserver] Stopped.")

    def dispatch_api(self, method: str, path: str, body: dict):
        """Processes an API request and returns (status_code, content_type, body_str)."""
        if method == "GET" and (path == "/" or path == "/index.html"):
            return 200, "text/html", HTML_TEMPLATE

        elif method == "GET" and path == "/api/status":
            data = {
                "unlocked": self.vault.is_unlocked,
                "pin": self.pin,
                "ip": self.wifi_mgr.get_ip(),
                "accounts_count": len(self.vault.list_accounts())
            }
            return 200, "application/json", json.dumps(data)

        elif method == "GET" and path == "/api/list":
            if not self.vault.is_unlocked:
                return 403, "application/json", json.dumps({"error": "Vault locked"})
            return 200, "application/json", json.dumps(self.vault.entries)

        elif method == "POST" and path == "/api/save":
            if not self.vault.is_unlocked:
                return 403, "application/json", json.dumps({"error": "Vault locked"})
            acc = body.get("account", "").strip()
            pwd = body.get("password", "")
            if acc and pwd:
                self.vault.set_credential(acc, pwd)
                return 200, "application/json", json.dumps({"status": "saved"})
            return 400, "application/json", json.dumps({"error": "Missing fields"})

        elif method == "POST" and path == "/api/delete":
            if not self.vault.is_unlocked:
                return 403, "application/json", json.dumps({"error": "Vault locked"})
            acc = body.get("account", "").strip()
            if acc:
                self.vault.delete_credential(acc)
                return 200, "application/json", json.dumps({"status": "deleted"})
            return 400, "application/json", json.dumps({"error": "Missing account"})

        elif method == "GET" and path == "/api/wifi/scan":
            networks = self.wifi_mgr.scan_networks()
            return 200, "application/json", json.dumps(networks)

        elif method == "POST" and path == "/api/wifi":
            ssid = body.get("ssid", "").strip()
            password = body.get("password", "")
            if ssid:
                self.wifi_mgr.save_config(ssid, password)
                self.wifi_mgr.connect(ssid, password)
                return 200, "application/json", json.dumps({"status": "wifi_saved"})
            return 400, "application/json", json.dumps({"error": "Missing ssid"})

        elif method == "POST" and path == "/api/lock":
            self.vault.lock()
            self.stop()
            return 200, "application/json", json.dumps({"status": "locked"})

        elif method == "POST" and path == "/api/relay_config":
            h = body.get("relay_host", "").strip()
            p = int(body.get("relay_port", 8080))
            if h:
                self.save_relay_config(h, p)
                return 200, "application/json", json.dumps({"status": "saved"})
            return 400, "application/json", json.dumps({"error": "Missing relay_host"})

        return 404, "text/plain", "Not Found"

    def handle_serial_command(self, line: str):
        """
        Processes an incoming RPC command from USB serial:
        Format: [SERIAL_REQ:id:METHOD:path:body_json]
        Replies: [SERIAL_RESP:id:status:content_type:body_json]
        """
        if not line.startswith("[SERIAL_REQ:") or not line.endswith("]"):
            return False

        content = line[12:-1]
        parts = content.split(":", 3)
        if len(parts) < 3:
            return False

        req_id = parts[0]
        method = parts[1].upper()
        path = parts[2]
        body_str = parts[3] if len(parts) > 3 else ""

        body_dict = {}
        if body_str:
            try:
                body_dict = json.loads(body_str)
            except Exception:
                pass

        status, ct, resp_body = self.dispatch_api(method, path, body_dict)
        print(f"[SERIAL_RESP:{req_id}:{status}:{ct}:{resp_body}]")
        return True

    def handle_request(self):
        """Handles incoming Wi-Fi socket connections and reverse RPC poll."""
        if not self.is_running:
            return

        # 1. Reverse RPC poll from host relay server (tunnels through AP isolation)
        self._poll_reverse_rpc()

        # 2. Local Wi-Fi socket connections
        if not self.sock:
            return

        try:
            conn, addr = self.sock.accept()
        except OSError:
            return  # No incoming connection

        conn.settimeout(2.5)
        try:
            raw_req = conn.recv(2048)
            if not raw_req:
                conn.close()
                return

            req_str = raw_req.decode("utf-8", "ignore")
            lines = req_str.split("\r\n")
            if not lines or not lines[0]:
                conn.close()
                return

            req_line_parts = lines[0].split(" ")
            if len(req_line_parts) < 2:
                conn.close()
                return

            method = req_line_parts[0]
            path = req_line_parts[1].split("?")[0]
            body_dict = self._parse_json_body(req_str)

            status, ct, resp_body = self.dispatch_api(method, path, body_dict)
            self._send_response(conn, status, ct, resp_body)

        except Exception as e:
            print("[Webserver] Request handling error:", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass
            gc.collect()

    def _parse_json_body(self, req_str):
        try:
            body_start = req_str.find("\r\n\r\n")
            if body_start != -1:
                return json.loads(req_str[body_start + 4:])
        except Exception:
            pass
        return {}

    def _send_response(self, conn, status_code, content_type, body):
        status_text = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}.get(status_code, "OK")
        header = f"HTTP/1.1 {status_code} {status_text}\r\nContent-Type: {content_type}\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n"
        conn.sendall(header.encode("utf-8") + (body.encode("utf-8") if isinstance(body, str) else body))

    def _poll_reverse_rpc(self):
        """Polls the relay server for queued commands when behind NAT/AP isolation."""
        if not self.wifi_mgr.is_connected() or not self.is_running:
            return

        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_rpc_poll) < 1000:
            return
        self.last_rpc_poll = now

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.2)
            addr = socket.getaddrinfo(self.relay_host, self.relay_port)[0][-1]
            s.connect(addr)
            req = (
                f"GET /relay/poll_rpc?pin={self.pin} HTTP/1.1\r\n"
                f"Host: {self.relay_host}:{self.relay_port}\r\n"
                f"Connection: close\r\n\r\n"
            )
            s.sendall(req.encode("utf-8"))
            raw = b""
            while True:
                chunk = s.recv(512)
                if not chunk:
                    break
                raw += chunk
            s.close()

            if b"\r\n\r\n" in raw:
                body_str = raw.split(b"\r\n\r\n", 1)[1].decode("utf-8", "ignore").strip()
                if body_str and body_str.startswith("{"):
                    cmd = json.loads(body_str)
                    req_id = cmd.get("id")
                    method = cmd.get("method", "GET")
                    path = cmd.get("path", "/")
                    body_dict = cmd.get("body", {})

                    if req_id:
                        status, ct, resp_body = self.dispatch_api(method, path, body_dict)
                        self._send_reverse_reply(req_id, status, ct, resp_body)
        except Exception:
            pass

    def _send_reverse_reply(self, req_id, status, content_type, body_str):
        """Sends an RPC response back through the reverse tunnel."""
        try:
            payload = json.dumps({
                "id": req_id,
                "status": status,
                "content_type": content_type,
                "body": body_str
            })
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            addr = socket.getaddrinfo(self.relay_host, self.relay_port)[0][-1]
            s.connect(addr)
            req = (
                f"POST /relay/reply_rpc HTTP/1.1\r\n"
                f"Host: {self.relay_host}:{self.relay_port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{payload}"
            )
            s.sendall(req.encode("utf-8"))
            s.recv(256)
            s.close()
        except Exception as e:
            print("[Webserver] Reverse reply error:", e)
