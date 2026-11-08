# keyboard_hid.py
# USB HID Keyboard driver with comprehensive ASCII keymap for MicroPython on ESP32-S3

import time

try:
    import usb.device
    from usb.device.hid import HIDInterface
except ImportError:
    usb = None
    HIDInterface = None

KEYBOARD_REPORT_DESC = bytes(
    [
        0x05, 0x01,  # Usage Page (Generic Desktop)
        0x09, 0x06,  # Usage (Keyboard)
        0xA1, 0x01,  # Collection (Application)
        0x05, 0x07,  #   Usage Page (Key Codes)
        0x19, 0xE0,  #   Usage Minimum (224 - Left Control)
        0x29, 0xE7,  #   Usage Maximum (231 - Right GUI)
        0x15, 0x00,  #   Logical Minimum (0)
        0x25, 0x01,  #   Logical Maximum (1)
        0x75, 0x01,  #   Report Size (1)
        0x95, 0x08,  #   Report Count (8)
        0x81, 0x02,  #   Input (Data, Variable, Absolute) - Modifier byte
        0x95, 0x01,  #   Report Count (1)
        0x75, 0x08,  #   Report Size (8)
        0x81, 0x01,  #   Input (Constant) - Reserved byte
        0x95, 0x05,  #   Report Count (5)
        0x75, 0x01,  #   Report Size (1)
        0x05, 0x08,  #   Usage Page (LEDs)
        0x19, 0x01,  #   Usage Minimum (1)
        0x29, 0x05,  #   Usage Maximum (5)
        0x91, 0x02,  #   Output (Data, Variable, Absolute) - LED report
        0x95, 0x01,  #   Report Count (1)
        0x75, 0x03,  #   Report Size (3)
        0x91, 0x01,  #   Output (Constant) - LED report padding
        0x95, 0x06,  #   Report Count (6)
        0x75, 0x08,  #   Report Size (8)
        0x15, 0x00,  #   Logical Minimum (0)
        0x25, 0x65,  #   Logical Maximum (101)
        0x05, 0x07,  #   Usage Page (Key Codes)
        0x19, 0x00,  #   Usage Minimum (0)
        0x29, 0x65,  #   Usage Maximum (101)
        0x81, 0x00,  #   Input (Data, Array) - Key array (6 keys)
        0xC0,        # End Collection
    ]
)

MOD_NONE = 0x00
MOD_SHIFT = 0x02

# Build full ASCII map to (modifier, hid_code)
KEYMAP = {
    # Whitespace & Control
    " ": (MOD_NONE, 0x2C),
    "\t": (MOD_NONE, 0x2B),
    "\n": (MOD_NONE, 0x28),
    "\r": (MOD_NONE, 0x28),

    # Numbers 1-9, 0
    "1": (MOD_NONE, 0x1E), "2": (MOD_NONE, 0x1F), "3": (MOD_NONE, 0x20),
    "4": (MOD_NONE, 0x21), "5": (MOD_NONE, 0x22), "6": (MOD_NONE, 0x23),
    "7": (MOD_NONE, 0x24), "8": (MOD_NONE, 0x25), "9": (MOD_NONE, 0x26),
    "0": (MOD_NONE, 0x27),

    # Shifted Number Symbols
    "!": (MOD_SHIFT, 0x1E), "@": (MOD_SHIFT, 0x1F), "#": (MOD_SHIFT, 0x20),
    "$": (MOD_SHIFT, 0x21), "%": (MOD_SHIFT, 0x22), "^": (MOD_SHIFT, 0x23),
    "&": (MOD_SHIFT, 0x24), "*": (MOD_SHIFT, 0x25), "(": (MOD_SHIFT, 0x26),
    ")": (MOD_SHIFT, 0x27),

    # Punctuation & symbols
    "-": (MOD_NONE, 0x2D), "_": (MOD_SHIFT, 0x2D),
    "=": (MOD_NONE, 0x2E), "+": (MOD_SHIFT, 0x2E),
    "[": (MOD_NONE, 0x2F), "{": (MOD_SHIFT, 0x2F),
    "]": (MOD_NONE, 0x30), "}": (MOD_SHIFT, 0x30),
    "\\": (MOD_NONE, 0x31), "|": (MOD_SHIFT, 0x31),
    ";": (MOD_NONE, 0x33), ":": (MOD_SHIFT, 0x33),
    "'": (MOD_NONE, 0x34), '"': (MOD_SHIFT, 0x34),
    "`": (MOD_NONE, 0x35), "~": (MOD_SHIFT, 0x35),
    ",": (MOD_NONE, 0x36), "<": (MOD_SHIFT, 0x36),
    ".": (MOD_NONE, 0x37), ">": (MOD_SHIFT, 0x37),
    "/": (MOD_NONE, 0x38), "?": (MOD_SHIFT, 0x38),
}

# Letters a-z and A-Z
for i in range(26):
    char_lower = chr(ord("a") + i)
    char_upper = chr(ord("A") + i)
    keycode = 0x04 + i
    KEYMAP[char_lower] = (MOD_NONE, keycode)
    KEYMAP[char_upper] = (MOD_SHIFT, keycode)

class KeyboardHID:
    def __init__(self):
        self.hid = None
        self._init_usb()

    def _init_usb(self):
        try:
            self.hid = HIDInterface(report_descriptor=KEYBOARD_REPORT_DESC)
            dev = usb.device.get()
            dev.init(self.hid, builtin_driver=True)
            print("[USB HID] Keyboard interface initialized.")
        except Exception as e:
            print("[USB HID] Initialization note:", e)

    def send_key(self, modifier: int, keycode: int):
        if not self.hid:
            return
        report = bytearray(8)
        report[0] = modifier
        report[2] = keycode
        try:
            self.hid.send_report(report)
            time.sleep_ms(4)
            # Release
            self.hid.send_report(bytearray(8))
            time.sleep_ms(15)
        except Exception as e:
            print("[USB HID] Send error:", e)

    def type_string(self, text: str, delay_ms: int = 15):
        print(f"[USB HID] Typing text length={len(text)}...")
        for char in text:
            if char in KEYMAP:
                mod, code = KEYMAP[char]
                self.send_key(mod, code)
            else:
                print(f"[USB HID] Unknown character '{char}', skipping")
            time.sleep_ms(delay_ms)
        print("[USB HID] Typing complete.")

