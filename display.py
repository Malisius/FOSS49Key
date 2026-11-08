# display.py
# Unified display driver: supports both live SSD1306 hardware OLED and simulated console box display

class Display:
    def __init__(self, test_mode=False, width=128, height=64, sda=8, scl=9):
        self.test_mode = test_mode
        self.width = width
        self.height = height
        self.oled = None

        if not self.test_mode:
            try:
                import machine
                import ssd1306
                i2c = machine.I2C(0, sda=machine.Pin(sda), scl=machine.Pin(scl), freq=400000)
                if 0x3C in i2c.scan() or 0x3D in i2c.scan():
                    self.oled = ssd1306.SSD1306_I2C(width, height, i2c, addr=0x3C)
                    print("[Display] Live SSD1306 Hardware OLED initialized on I2C (0x3C).")
                else:
                    print("[Display] Notice: No I2C display responding at 0x3C/0x3D; falling back to console.")
            except Exception as e:
                print(f"[Display] Note: Hardware OLED init skipped ({e}); using console.")

    def render_box(self, lines, title="Foss49Key OLED"):
        """Renders simulated 128x64 display as a formatted ASCII box in console."""
        width = 34
        inner_w = width - 4
        border = "+" + "-" * (width - 2) + "+"

        # Center title
        t = title[:inner_w]
        pad_left = (inner_w - len(t)) // 2
        pad_right = inner_w - len(t) - pad_left
        title_str = "| " + " " * pad_left + t + " " * pad_right + " |"

        print("\n" + border)
        print(title_str)
        print("+" + "-" * (width - 2) + "+")
        for line in lines:
            line = str(line)[:inner_w]
            pad = inner_w - len(line)
            print(f"| {line}{' ' * pad} |")
        for _ in range(max(0, 6 - len(lines))):
            print(f"| {' ' * inner_w} |")
        print(border)

    def show_locked(self, status="Say 5-word phrase", wifi_status=""):
        if self.oled:
            try:
                self.oled.fill(0)
                self.oled.text("Foss49Key LOCKED", 0, 0)
                self.oled.hline(0, 10, 128, 1)
                self.oled.text("Press CON (Key1)", 0, 16)
                self.oled.text("to speak phrase", 0, 26)
                if wifi_status:
                    self.oled.text(f"WiFi: {wifi_status[:10]}", 0, 42)
                self.oled.text(status[:16], 0, 54)
                self.oled.show()
                return
            except Exception:
                pass

        lines = [
            "*** DEVICE LOCKED ***",
            "",
            "Press CON (Key1) to Speak",
            f"Mic: {status}",
            "",
            f"WiFi: {wifi_status}" if wifi_status else ""
        ]
        self.render_box(lines, title="Foss49Key - LOCKED")

    def show_listening(self, meter_str, seconds_left):
        if self.oled:
            try:
                self.oled.fill(0)
                self.oled.text("LISTENING...", 16, 4)
                self.oled.text(f"{seconds_left:.1f}s remaining", 16, 20)
                # Draw meter bar
                meter_len = min(120, max(0, int(len(meter_str.strip()) * 6)))
                self.oled.rect(4, 38, 120, 12, 1)
                if meter_len > 0:
                    self.oled.fill_rect(6, 40, meter_len, 8, 1)
                self.oled.show()
                return
            except Exception:
                pass

        lines = [
            "*** LISTENING ***",
            "",
            f"Speak now ({seconds_left:.1f}s)...",
            f"Mic: [{meter_str}]",
            "",
            "Release/Wait to finish"
        ]
        self.render_box(lines, title="Voice Capture")

    def show_transcribing(self):
        if self.oled:
            try:
                self.oled.fill(0)
                self.oled.text("PROCESSING...", 10, 10)
                self.oled.text("Querying", 10, 26)
                self.oled.text("Deepgram STT...", 10, 38)
                self.oled.show()
                return
            except Exception:
                pass

        lines = [
            "*** PROCESSING ***",
            "",
            "Sending to Deepgram...",
            "Decrypting vault...",
            "",
            "Please wait..."
        ]
        self.render_box(lines, title="Deepgram STT")

    def show_menu(self, items, selected_idx, title="PASSWORDS"):
        if self.oled:
            try:
                self.oled.fill(0)
                header = f"{title[:10]} ({selected_idx+1}/{len(items)})"
                self.oled.text(header, 0, 0)
                self.oled.hline(0, 10, 128, 1)

                # Show 4 visible lines on 128x64
                window_size = 4
                start_idx = max(0, min(selected_idx - 1, len(items) - window_size))
                end_idx = min(len(items), start_idx + window_size)

                y = 14
                for i in range(start_idx, end_idx):
                    prefix = ">" if i == selected_idx else " "
                    display_text = f"{prefix}{items[i]}"[:16]
                    self.oled.text(display_text, 0, y)
                    y += 12
                self.oled.show()
                return
            except Exception:
                pass

        window_size = 5
        start_idx = max(0, min(selected_idx - 2, len(items) - window_size))
        end_idx = min(len(items), start_idx + window_size)

        lines = []
        for i in range(start_idx, end_idx):
            prefix = " > " if i == selected_idx else "   "
            lines.append(f"{prefix}{items[i]}")

        self.render_box(lines, title=f"{title} ({selected_idx+1}/{len(items)})")

    def show_typing(self, account):
        if self.oled:
            try:
                self.oled.fill(0)
                self.oled.text("TYPING KEY...", 10, 10)
                self.oled.text(account[:15], 10, 28)
                self.oled.text("Entering USB HID", 0, 48)
                self.oled.show()
                return
            except Exception:
                pass

        lines = [
            "*** TYPING PASSWORD ***",
            "",
            f"Account: {account}",
            "Entering over USB HID...",
            "",
            "Done!"
        ]
        self.render_box(lines, title="USB Keyboard")

    def show_webserver(self, pin, ip, port=80):
        if self.oled:
            try:
                self.oled.fill(0)
                self.oled.text("PORTAL ACTIVE", 10, 0)
                self.oled.hline(0, 10, 128, 1)
                self.oled.text(f"PIN: {pin}", 10, 18)
                self.oled.text(f"IP: {ip[:12]}", 0, 34)
                self.oled.text("BAK = Stop", 10, 50)
                self.oled.show()
                return
            except Exception:
                pass

        lines = [
            "*** WEB PORTAL ONLINE ***",
            "",
            f"5-Digit PIN: {pin}",
            f"Device IP  : {ip}:{port}",
            "",
            "Press BAK (Key0) to Stop"
        ]
        self.render_box(lines, title="Remote Vault Portal")

    def show_message(self, title, msg):
        if self.oled:
            try:
                self.oled.fill(0)
                self.oled.text(title[:16], 0, 10)
                self.oled.hline(0, 22, 128, 1)
                self.oled.text(msg[:16], 0, 32)
                self.oled.show()
                return
            except Exception:
                pass

        lines = ["", msg, ""]
        self.render_box(lines, title=title)
