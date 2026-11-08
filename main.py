# main.py
# Foss49Key - Hardware Password Manager & USB HID Auto-Typer
# Runs on ESP32-S3 MicroPython

# ==============================================================================
# MODE CONFIGURATION
# Set to True  -> Testing Mode: simulates screen (console ASCII boxes) & simulates
#                 rotary encoder + buttons via serial console inputs.
# Set to False -> Live Hardware Mode: uses physical I2C 128x64 OLED display and
#                 reads physical GPIO pins for rotary encoder and buttons.
# ==============================================================================
TEST_MODE = False

import time
import sys
import gc

from display import Display
from keyboard_hid import KeyboardHID
from crypto_vault import VaultManager
from voice_unlock import VoiceUnlockManager
from wifi_manager import WiFiManager
from esp_webserver import ESPWebServer

# --- Real Hardware GPIO Pin Definitions (Used when TEST_MODE = False) ---
I2C_SDA_PIN = 8   # OLED I2C SDA
I2C_SCL_PIN = 9   # OLED I2C SCL
ENC_A_PIN = 13    # Rotary Encoder Phase A (TRA)
ENC_B_PIN = 14    # Rotary Encoder Phase B (TRB)
ENC_SW_PIN = 12   # Rotary Encoder Push Switch (PSH)
BTN_CON_PIN = 11  # KEY1 / CON / OK / Confirm Button
BTN_BAK_PIN = 10  # KEY0 / BAK / Back / Return Button

# --- States ---
STATE_LOCKED = 0
STATE_LISTENING = 1
STATE_TRANSCRIBING = 2
STATE_MENU = 3
STATE_WEBSERVER = 4

class Foss49KeyApp:
    def __init__(self, test_mode: bool = False):
        self.test_mode = test_mode
        mode_str = "TESTING (Simulated Screen & Buttons)" if self.test_mode else "LIVE HARDWARE (Physical Screen & GPIO Pins)"
        print(f"\n==================================================")
        print(f" [Foss49Key] Initializing in {mode_str} Mode")
        print(f"==================================================")

        # Core Peripherals
        self.display = Display(test_mode=self.test_mode, width=128, height=64, sda=I2C_SDA_PIN, scl=I2C_SCL_PIN)
        self.keyboard = KeyboardHID()
        self.vault = VaultManager()
        self.voice = VoiceUnlockManager(key_file="deepgram.key")
        self.wifi = WiFiManager()
        self.webserver = ESPWebServer(self.vault, self.wifi, port=80)

        # State Variables
        self.state = STATE_LOCKED
        self.menu_items = []
        self.selected_idx = 0
        self.current_pin = None

        # Setup serial input polling for RPC bridge and testing
        try:
            import uselect
            self.poll = uselect.poll()
            self.poll.register(sys.stdin, uselect.POLLIN)
        except Exception:
            self.poll = None

        # Configure Inputs depending on mode
        if not self.test_mode:
            self._init_live_gpio()
        else:
            self._init_test_input()

        # Connect Wi-Fi on boot
        self._init_wifi()

    def _init_live_gpio(self):
        """Initializes real physical GPIO pins with pull-ups for Live Mode."""
        from machine import Pin
        print("[Hardware] Initializing physical rotary encoder & buttons on GPIO...")
        self.pin_a = Pin(ENC_A_PIN, Pin.IN, Pin.PULL_UP)
        self.pin_b = Pin(ENC_B_PIN, Pin.IN, Pin.PULL_UP)
        self.pin_sw = Pin(ENC_SW_PIN, Pin.IN, Pin.PULL_UP)
        self.pin_con = Pin(BTN_CON_PIN, Pin.IN, Pin.PULL_UP)
        self.pin_bak = Pin(BTN_BAK_PIN, Pin.IN, Pin.PULL_UP)

        self.last_a = self.pin_a.value()
        self.last_sw = self.pin_sw.value()
        self.last_con = self.pin_con.value()
        self.last_bak = self.pin_bak.value()

    def _init_test_input(self):
        """Sets up non-blocking serial input reader for Testing Mode."""
        print("[Simulation] Serial console simulation active.")
        print(" Controls (type in serial monitor):")
        print("   [W] or [U] : Rotary Encoder Up (Previous)")
        print("   [S] or [D] : Rotary Encoder Down (Next)")
        print("   [C] or Enter : CON / KEY1 (OK / Select / Trigger Voice Capture)")
        print("   [B] : BAK / KEY0 (Back / Cancel / Lock)")
        print("   [P] : Encoder Switch (PSH)")
        try:
            import uselect
            self.poll = uselect.poll()
            self.poll.register(sys.stdin, uselect.POLLIN)
        except Exception:
            self.poll = None

    def _init_wifi(self):
        self.display.show_message("Wi-Fi Connecting", "Connecting to NinerWiFi-Guest...")
        connected = self.wifi.connect(timeout_sec=8)
        ip = self.wifi.get_ip()
        wifi_str = f"{self.wifi.ssid} ({ip})" if connected else "Connecting..."
        self.display.show_locked(status="Ready to listen", wifi_status=wifi_str)

    def update_menu_list(self):
        accounts = self.vault.list_accounts()
        self.menu_items = [f"Key: {acc}" for acc in accounts]
        self.menu_items.append("[ Start Web Server ]")
        self.menu_items.append("[ Lock Device ]")
        if self.selected_idx >= len(self.menu_items):
            self.selected_idx = max(0, len(self.menu_items) - 1)

    def render_current_state(self):
        if self.state == STATE_LOCKED:
            ip = self.wifi.get_ip()
            wifi_str = f"{self.wifi.ssid} ({ip})" if self.wifi.is_connected() else "Disconnected"
            prompt = "Press CON to speak" if not self.test_mode else "Press [C] to speak"
            self.display.show_locked(status=prompt, wifi_status=wifi_str)

        elif self.state == STATE_MENU:
            self.update_menu_list()
            self.display.show_menu(self.menu_items, self.selected_idx, title="PASSWORD VAULT")

        elif self.state == STATE_WEBSERVER:
            self.display.show_webserver(self.current_pin, self.wifi.get_ip(), port=80)

    def handle_voice_unlock(self):
        self.state = STATE_LISTENING
        if not self.wifi.is_connected():
            self.wifi.connect(timeout_sec=5)

        def progress_cb(meter, remaining):
            self.display.show_listening(meter, remaining)

        # Record 3.0 seconds from I2S mic into 8MB PSRAM
        pcm_audio = self.voice.record_audio(duration_sec=3.0, on_progress=progress_cb)

        self.state = STATE_TRANSCRIBING
        self.display.show_transcribing()

        transcript = self.voice.transcribe_audio(pcm_audio)
        del pcm_audio
        gc.collect()

        if not transcript and self.test_mode:
            print("\n[TEST MODE] No speech detected from mic.")
            print("Type your 5-word passphrase below to test unlock (or press Enter to cancel):")
            try:
                manual = sys.stdin.readline().strip()
                if manual:
                    transcript = self.voice.clean_transcript(manual)
            except Exception:
                pass

        if not transcript:
            self.display.show_message("Voice Unlock", "No speech detected. Try again.")
            time.sleep_ms(1500)
            self.state = STATE_LOCKED
            self.render_current_state()
            return

        print(f"[Unlock Attempt] Spoken phrase: '{transcript}'")
        unlocked = self.vault.unlock(transcript)

        if unlocked:
            self.display.show_message("UNLOCKED", f"Passphrase verified!\n'{transcript}'")
            time.sleep_ms(1200)
            self.state = STATE_MENU
            self.selected_idx = 0
            self.render_current_state()
        else:
            self.display.show_message("ACCESS DENIED", f"Invalid phrase:\n'{transcript}'")
            time.sleep_ms(2000)
            self.state = STATE_LOCKED
            self.render_current_state()

    def handle_menu_selection(self):
        if self.selected_idx < len(self.vault.list_accounts()):
            account = self.vault.list_accounts()[self.selected_idx]
            pwd = self.vault.get_password(account)
            if pwd:
                self.display.show_typing(account)
                self.keyboard.type_string(pwd)
                time.sleep_ms(1000)
                self.render_current_state()
        else:
            action_label = self.menu_items[self.selected_idx]
            if "Start Web Server" in action_label:
                self.start_webserver_mode()
            elif "Lock Device" in action_label:
                self.lock_device()

    def start_webserver_mode(self):
        self.current_pin = self.webserver.start()
        self.state = STATE_WEBSERVER
        self.render_current_state()

    def stop_webserver_mode(self):
        self.webserver.stop()
        self.state = STATE_MENU
        self.render_current_state()

    def lock_device(self):
        if self.webserver.is_running:
            self.webserver.stop()
        self.vault.lock()
        self.state = STATE_LOCKED
        self.display.show_message("LOCKED", "Device secured.")
        time.sleep_ms(1000)
        self.render_current_state()

    def _poll_live_hardware(self):
        """Polls physical rotary encoder and push buttons."""
        # 1. Rotary Encoder (falling edge on Phase A)
        val_a = self.pin_a.value()
        if self.last_a == 1 and val_a == 0:
            if self.state == STATE_MENU and len(self.menu_items) > 0:
                val_b = self.pin_b.value()
                if val_b == 1:
                    self.selected_idx = (self.selected_idx + 1) % len(self.menu_items)
                else:
                    self.selected_idx = (self.selected_idx - 1) % len(self.menu_items)
                self.render_current_state()
        self.last_a = val_a

        # 2. OK / Confirm Button (CON / KEY1)
        val_con = self.pin_con.value()
        if self.last_con == 1 and val_con == 0:
            time.sleep_ms(25)  # Debounce
            if self.pin_con.value() == 0:
                if self.state == STATE_LOCKED:
                    self.handle_voice_unlock()
                elif self.state == STATE_MENU:
                    self.handle_menu_selection()
                while self.pin_con.value() == 0:
                    time.sleep_ms(10)
        self.last_con = val_con

        # 3. Encoder Switch (PSH)
        val_sw = self.pin_sw.value()
        if self.last_sw == 1 and val_sw == 0:
            time.sleep_ms(25)
            if self.pin_sw.value() == 0:
                if self.state == STATE_LOCKED:
                    self.handle_voice_unlock()
                elif self.state == STATE_MENU:
                    self.handle_menu_selection()
                while self.pin_sw.value() == 0:
                    time.sleep_ms(10)
        self.last_sw = val_sw

        # 4. Back Button (BAK / KEY0)
        val_bak = self.pin_bak.value()
        if self.last_bak == 1 and val_bak == 0:
            time.sleep_ms(25)
            if self.pin_bak.value() == 0:
                if self.state == STATE_WEBSERVER:
                    self.stop_webserver_mode()
                elif self.state == STATE_MENU:
                    self.lock_device()
                while self.pin_bak.value() == 0:
                    time.sleep_ms(10)
        self.last_bak = val_bak

    def _poll_simulated_inputs(self):
        """Simulates rotary encoder and buttons via serial console keystrokes."""
        if not self.poll:
            return

        events = self.poll.poll(0)
        if not events:
            return

        char = sys.stdin.read(1)
        if not char:
            return

        char_lower = char.lower()

        # Encoder UP
        if char_lower in ["w", "u", "k", "+"]:
            print("[Sim Input] Rotary Encoder UP (Previous)")
            if self.state == STATE_MENU and len(self.menu_items) > 0:
                self.selected_idx = (self.selected_idx - 1) % len(self.menu_items)
                self.render_current_state()

        # Encoder DOWN
        elif char_lower in ["s", "d", "j", "-"]:
            print("[Sim Input] Rotary Encoder DOWN (Next)")
            if self.state == STATE_MENU and len(self.menu_items) > 0:
                self.selected_idx = (self.selected_idx + 1) % len(self.menu_items)
                self.render_current_state()

        # CON / KEY1 (OK / Select / Voice Trigger)
        elif char_lower in ["c", "\r", "\n", "1"]:
            print("[Sim Input] Pressed CON / KEY1 (Confirm)")
            if self.state == STATE_LOCKED:
                self.handle_voice_unlock()
            elif self.state == STATE_MENU:
                self.handle_menu_selection()

        # BAK / KEY0 (Back / Lock)
        elif char_lower in ["b", "0", "x"]:
            print("[Sim Input] Pressed BAK / KEY0 (Back)")
            if self.state == STATE_WEBSERVER:
                self.stop_webserver_mode()
            elif self.state == STATE_MENU:
                self.lock_device()

        # PSH (Encoder Switch)
        elif char_lower in ["p", "e"]:
            print("[Sim Input] Pressed Encoder Switch (PSH)")
            if self.state == STATE_LOCKED:
                self.handle_voice_unlock()
            elif self.state == STATE_MENU:
                self.handle_menu_selection()

    def run(self):
        print(f"\n[Foss49Key] Main loop active (TEST_MODE={self.test_mode}). Ready.")
        self.render_current_state()

        while True:
            try:
                # 1. Process incoming serial commands (Serial RPC bridge or simulation input)
                if self.poll:
                    events = self.poll.poll(0)
                    if events:
                        try:
                            if hasattr(sys.stdin, "buffer"):
                                raw = sys.stdin.buffer.readline()
                                line = raw.decode("utf-8", "ignore").strip()
                            else:
                                line = sys.stdin.readline().strip()
                        except Exception:
                            line = ""

                        if line:
                            if line.startswith("[SERIAL_REQ:"):
                                self.webserver.handle_serial_command(line)
                            elif self.test_mode:
                                self._poll_simulated_char(line)

                # 2. Process hardware inputs if in live mode
                if not self.test_mode:
                    self._poll_live_hardware()

                # 3. Service Web Server if active
                if self.state == STATE_WEBSERVER:
                    self.webserver.handle_request()
                    if not self.vault.is_unlocked:
                        self.state = STATE_LOCKED
                        self.render_current_state()

            except Exception as e:
                print("[App Loop Error]", e)

            time.sleep_ms(10)

    def _poll_simulated_char(self, line: str):
        char = line[0].lower() if line else ""
        if char in ["w", "u", "k", "+"]:
            print("[Sim Input] Rotary Encoder UP (Previous)")
            if self.state == STATE_MENU and len(self.menu_items) > 0:
                self.selected_idx = (self.selected_idx - 1) % len(self.menu_items)
                self.render_current_state()
        elif char in ["s", "d", "j", "-"]:
            print("[Sim Input] Rotary Encoder DOWN (Next)")
            if self.state == STATE_MENU and len(self.menu_items) > 0:
                self.selected_idx = (self.selected_idx + 1) % len(self.menu_items)
                self.render_current_state()
        elif char in ["c", "1"]:
            print("[Sim Input] Pressed CON / KEY1 (Confirm)")
            if self.state == STATE_LOCKED:
                self.handle_voice_unlock()
            elif self.state == STATE_MENU:
                self.handle_menu_selection()
        elif char in ["b", "0", "x"]:
            print("[Sim Input] Pressed BAK / KEY0 (Back)")
            if self.state == STATE_WEBSERVER:
                self.stop_webserver_mode()
            elif self.state == STATE_MENU:
                self.lock_device()
        elif char in ["p", "e"]:
            print("[Sim Input] Pressed Encoder Switch (PSH)")
            if self.state == STATE_LOCKED:
                self.handle_voice_unlock()
            elif self.state == STATE_MENU:
                self.handle_menu_selection()

if __name__ == "__main__":
    while True:
        try:
            app = Foss49KeyApp(test_mode=TEST_MODE)
            app.run()
        except Exception as e:
            print("[Fatal App Error - Restarting in 2s]:", e)
            time.sleep(2)
