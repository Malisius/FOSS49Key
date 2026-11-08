# wifi_manager.py
# Wi-Fi Station connection management for ESP32

import time
import json

try:
    import network
except ImportError:
    network = None

CONFIG_FILE = "wifi_config.json"
DEFAULT_SSID = "NinerWiFi-Guest"
DEFAULT_PASS = ""

class WiFiManager:
    def __init__(self):
        if network:
            self.wlan = network.WLAN(network.STA_IF)
            self.wlan.active(True)
        else:
            self.wlan = None
        self.ssid, self.password = self._load_config()

    def _load_config(self):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                return cfg.get("ssid", DEFAULT_SSID), cfg.get("password", DEFAULT_PASS)
        except Exception:
            return DEFAULT_SSID, DEFAULT_PASS

    def _find_matching_ssid(self, target_ssid):
        """Scans for networks and finds exact broadcast SSID case if mismatch exists."""
        if not self.wlan or not target_ssid:
            return target_ssid
        try:
            self.wlan.active(True)
            scan_raw = self.wlan.scan()
            for item in scan_raw:
                try:
                    name = item[0].decode("utf-8", "ignore").strip()
                    if name.lower() == target_ssid.lower():
                        return name
                except Exception:
                    pass
        except Exception:
            pass
        return target_ssid

    def save_config(self, ssid, password):
        exact_ssid = self._find_matching_ssid(ssid)
        self.ssid = exact_ssid
        self.password = password
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"ssid": exact_ssid, "password": password}, f)
            print(f"[WiFi] Saved credentials for '{exact_ssid}'")
            return True
        except Exception as e:
            print("[WiFi] Save config error:", e)
            return False

    def is_connected(self):
        if self.wlan:
            return self.wlan.isconnected()
        return True  # Assume connected in test environment

    def get_ip(self):
        if self.wlan and self.wlan.isconnected():
            return self.wlan.ifconfig()[0]
        return "10.143.34.7"

    def connect(self, ssid=None, password=None, timeout_sec=12):
        if ssid is not None:
            self.ssid = ssid
            self.password = password if password is not None else ""

        if not self.wlan:
            print(f"[WiFi] (Simulated) Connected to '{self.ssid}' (IP: 10.143.34.7)")
            return True

        self.wlan.active(True)
        # Check if SSID needs case normalization against broadcast APs
        exact_ssid = self._find_matching_ssid(self.ssid)
        if exact_ssid != self.ssid:
            print(f"[WiFi] Corrected SSID casing: '{self.ssid}' -> '{exact_ssid}'")
            self.ssid = exact_ssid

        print(f"[WiFi] Connecting to '{self.ssid}'...")
        try:
            if self.password:
                self.wlan.connect(self.ssid, self.password)
            else:
                self.wlan.connect(self.ssid)
        except Exception as e:
            print("[WiFi] Connect initiation error:", e)

        t_start = time.ticks_ms()
        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t_start) > timeout_sec * 1000:
                print(f"[WiFi] Connection timed out after {timeout_sec}s.")
                return False
            time.sleep_ms(250)

        ip = self.get_ip()
        print(f"[WiFi] Connected! IP: {ip}")
        return True

    def scan_networks(self):
        self.wlan.active(True)
        results = []
        try:
            scan_raw = self.wlan.scan()
            seen = set()
            for item in scan_raw:
                ssid_bytes = item[0]
                rssi = item[3]
                authmode = item[4]
                try:
                    name = ssid_bytes.decode("utf-8").strip()
                except Exception:
                    name = str(ssid_bytes)
                if name and name not in seen:
                    seen.add(name)
                    auth_str = "Open" if authmode == 0 else "WPA/WPA2"
                    results.append({"ssid": name, "rssi": rssi, "auth": auth_str})
        except Exception as e:
            print("[WiFi] Scan error:", e)
        return results

