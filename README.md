# Foss49Key - Hardware Password Manager & USB HID Auto-Typer

An ESP32-S3 MicroPython hardware password manager that emulates a USB keyboard to enter credentials into target computers. It features voice-activated cryptographic unlock via Deepgram speech-to-text, an encrypted on-chip vault, rotary encoder navigation, an on-demand web portal, and a host relay gateway accessible over Tailscale.

---

## Hardware Pinout Reference

| Peripheral | Signal | ESP32-S3 GPIO | Notes |
| :--- | :--- | :--- | :--- |
| **Rotary Encoder** | TRA (Phase A) | `GPIO 13` | Internal Pull-Up |
| | TRB (Phase B) | `GPIO 14` | Internal Pull-Up |
| | PSH (Switch) | `GPIO 12` | Internal Pull-Up (Active-Low) |
| **Buttons** | CON / KEY1 (OK) | `GPIO 11` | Confirm / Select / Voice Trigger |
| | BAK / KEY0 (Back) | `GPIO 10` | Return / Cancel / Stop Webserver |
| **I2S Microphone (ICS-43434)** | BCLK (SCK) | `GPIO 6` | Continuous Serial Clock |
| | DOUT (SD) | `GPIO 7` | Serial Data from mic |
| | LRCL (WS) | `GPIO 15` | Word Select (Left/Right Clock) |
| | SEL | `GPIO 16` | Channel select (LOW = Left channel) |
| **Display (Emulated & Optional SSD1306)** | SDA | `GPIO 8` | Hardware I2C 0 (or console emulation) |
| | SCL | `GPIO 9` | Hardware I2C 0 (or console emulation) |
| **USB Interface** | USB D- / D+ | `GPIO 19 / 20` | USB CDC Serial & USB HID Keyboard |

---

## System Architecture

```
                      +-----------------------------+
                      |   Public Domain / Visitor   |
                      +--------------+--------------+
                                     |
                                     v (Tailscale / Host IP)
                      +-----------------------------+
                      | Host Machine Relay Gateway  |
                      |   (relay_server/server.py)  |
                      |    Tailscale: 100.93.205.66 |
                      +--------------+--------------+
                                     | [PIN Gate: 5 Digits]
                                     |
                     +---------------+---------------+
                     |                               |
       (Direct Wi-Fi Proxy)             (USB Serial RPC Bridge)
       [Fallback if LAN open]          [Auto-Bypass AP Isolation]
                     |                               |
                     +---------------+---------------+
                                     |
                                     v
                      +-----------------------------+
                      |   ESP32-S3 Embedded Server  |
                      |   IP: 10.143.34.7 (Port 80) |
                      |    (Vault & Wi-Fi Config)   |
                      +-----------------------------+

 [Microphone] ---> [Deepgram STT] ---> [Passphrase SHA-256] ---> [AES-256 Vault Decrypt]
                                                                          |
                                                                          v
                                                          [USB HID Keyboard Auto-Typer]
```

---

## Operating Instructions

### 1. Device Boot & Wi-Fi
- The device boots MicroPython and automatically executes [main.py](file:///home/pjotir/gitrepos/foss49key/main.py).
- By default, it connects to **`NinerWiFi-Guest`** (or saved network in `wifi_config.json`).
- If no physical OLED is connected, the UI is automatically rendered in ASCII box frames directly to the console (`/dev/ttyACM0`).

### 2. Unlocking with 5-Word Voice Passphrase
- While the device is in the **`LOCKED`** state:
  1. Press **CON / KEY1** (`GPIO 11`) or the encoder push button (`GPIO 12`).
  2. Speak your **5-word passphrase** clearly into the microphone during the 3.5-second capture window (a live VU meter will display on console).
  3. The ESP32 sends the 16kHz linear PCM audio to **Deepgram** over HTTPS.
  4. The returned transcript is normalized and used to derive the AES-256 decryption key.
  5. *First-time setup*: The first passphrase you speak will initialize and lock the vault to that phrase!

### 3. Password Selection & Auto-Typing
- Once unlocked, rotate the rotary encoder to scroll through your saved credentials.
- Press **CON / KEY1** to select an account.
- The device will type the stored password into the computer connected over USB via the standard USB HID keyboard interface.

### 4. Remote Web Portal & Tailscale Relay
1. From the unlocked device menu, rotate to **`[ Start Web Server ]`** and press **OK**.
2. The ESP32 starts its local HTTP server and displays a random **5-digit PIN** (e.g. `48192`).
3. Launch the host relay server on this machine:
   ```bash
   ./relay_server/run_relay.sh
   ```
4. Visitors connecting to your domain or Tailscale endpoint:
   ```
   http://100.93.205.66:8080
   ```
   will see the secure Foss49Key PIN gate.
5. Entering the 5-digit PIN immediately opens the full management portal where you can:
   - View, copy, add, and delete password vault entries.
   - Scan for Wi-Fi networks and change Wi-Fi credentials.
   - Lock the device remotely.

