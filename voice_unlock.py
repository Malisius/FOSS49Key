# voice_unlock.py
# High-speed in-memory I2S audio capture & Deepgram transcription
# Optimized for ESP32-S3 with 8MB PSRAM

import time
import struct
import gc
import socket
import json

try:
    from machine import I2S, Pin
except ImportError:
    I2S = None
    Pin = None

try:
    import tls
except ImportError:
    tls = None

try:
    import micropython
except ImportError:
    class _DummyMicropython:
        @staticmethod
        def viper(fn):
            return fn
        @staticmethod
        def native(fn):
            return fn
    micropython = _DummyMicropython()

# Pin Definitions (ICS-43434)
SEL_PIN_NUM = 16
LRCL_PIN_NUM = 15   # WS
DOUT_PIN_NUM = 7    # SD
BCLK_PIN_NUM = 6    # SCK

SAMPLE_RATE = 16000

@micropython.native
def convert_and_amplify(src, dst, sample_count, dst_offset):
    """
    Converts 32-bit ICS-43434 I2S samples to 16-bit linear PCM with 8x gain boost.
    """
    s = 0
    d = dst_offset
    for _ in range(sample_count):
        # High word contains upper 16 bits
        b1 = src[s + 1]
        b2 = src[s + 2]
        b3 = src[s + 3]
        # Signed 16-bit high word
        w = (b3 << 8) | b2
        if w >= 0x8000:
            w -= 0x10000
        # 8x gain boost: shift left by 3 and combine with lower bits
        val = (w << 3) | (b1 >> 5)
        if val > 32767:
            val = 32767
        elif val < -32768:
            val = -32768
        if val < 0:
            val += 0x10000
        dst[d] = val & 0xFF
        dst[d + 1] = (val >> 8) & 0xFF
        s += 4
        d += 2

class VoiceUnlockManager:
    def __init__(self, key_file="deepgram.key"):
        self.key_file = key_file
        self.api_key = self._load_key()
        if Pin:
            self.sel_pin = Pin(SEL_PIN_NUM, Pin.OUT)
            self.sel_pin.value(0)  # Left channel
        else:
            self.sel_pin = None

    def _load_key(self):
        try:
            with open(self.key_file, "r") as f:
                return f.read().strip()
        except Exception:
            return "4884e0d3f6483801657ac4a61a19b6807302c939"

    def record_audio(self, duration_sec=3.0, on_progress=None):
        """Records 16kHz mono audio directly into 8MB PSRAM."""
        gc.collect()
        if self.sel_pin:
            self.sel_pin.value(0)

        total_samples = int(SAMPLE_RATE * duration_sec)
        out_pcm = bytearray(total_samples * 2)

        # Simulation fallback if I2S hardware missing
        if not I2S or not Pin:
            print("[Mic] Notice: Hardware I2S missing; simulating audio capture.")
            steps = int(duration_sec * 4)
            for i in range(steps):
                time.sleep(0.25)
                if on_progress:
                    on_progress("######              ", max(0.0, duration_sec - (i + 1) * 0.25))
            return out_pcm

        i2s = I2S(
            0,
            sck=Pin(BCLK_PIN_NUM),
            ws=Pin(LRCL_PIN_NUM),
            sd=Pin(DOUT_PIN_NUM),
            mode=I2S.RX,
            bits=32,
            format=I2S.MONO,
            rate=SAMPLE_RATE,
            ibuf=4096,
        )

        # Discard initial stabilization frames
        flush_buf = bytearray(1024)
        for _ in range(4):
            i2s.readinto(flush_buf)
            time.sleep_ms(10)

        chunk_samples = 512
        in_buf = bytearray(chunk_samples * 4)

        samples_recorded = 0
        t_start = time.ticks_ms()
        t_last_ui = 0

        print(f"[Mic] Recording {duration_sec}s into PSRAM...")
        try:
            while samples_recorded < total_samples:
                num_read = i2s.readinto(in_buf)
                if num_read:
                    samples_in_chunk = num_read // 4
                    samples_to_process = min(samples_in_chunk, total_samples - samples_recorded)

                    # Convert to 16-bit PCM with 8x gain directly into out_pcm
                    dst_offset = samples_recorded * 2
                    convert_and_amplify(in_buf, out_pcm, samples_to_process, dst_offset)
                    samples_recorded += samples_to_process

                    # Throttle UI updates to at most once every 150ms to prevent I2C bus starvation
                    now = time.ticks_ms()
                    if on_progress and (time.ticks_diff(now, t_last_ui) > 150 or samples_recorded >= total_samples):
                        t_last_ui = now
                        # Calculate peak for visual meter
                        peak = 0
                        for i in range(dst_offset, dst_offset + samples_to_process * 2, 8):
                            val = abs(struct.unpack("<h", out_pcm[i:i+2])[0])
                            if val > peak:
                                peak = val
                        meter_level = min(20, peak // 1500)
                        meter_bar = "#" * meter_level + " " * (20 - meter_level)
                        elapsed_s = time.ticks_diff(now, t_start) / 1000.0
                        remaining = max(0.0, duration_sec - elapsed_s)
                        on_progress(meter_bar, remaining)
        finally:
            i2s.deinit()

        print(f"[Mic] Captured {len(out_pcm)} bytes in PSRAM.")
        return out_pcm

    def transcribe_audio(self, pcm_data: bytes) -> str:
        """Sends linear16 PCM directly over high-speed TLS socket to Deepgram."""
        if not self.api_key:
            print("[Deepgram] Error: No API key available.")
            return ""

        if not pcm_data:
            return ""

        host = "api.deepgram.com"
        port = 443
        path = "/v1/listen?model=nova-2&punctuate=false&encoding=linear16&sample_rate=16000&channels=1"

        print(f"[Deepgram] Uploading {len(pcm_data)} bytes to Deepgram...")
        gc.collect()

        ss = None
        try:
            ai = socket.getaddrinfo(host, port)[0][-1]
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10.0)
            s.connect(ai)

            if tls:
                ctx = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
                ctx.verify_mode = tls.CERT_NONE
                ss = ctx.wrap_socket(s, server_hostname=host)
            else:
                import ssl
                ss = ssl.wrap_socket(s)

            headers = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Authorization: Token {self.api_key}\r\n"
                f"Content-Type: audio/raw\r\n"
                f"Content-Length: {len(pcm_data)}\r\n"
                f"Connection: close\r\n\r\n"
            )
            ss.write(headers.encode("utf-8"))
            # Fast in-memory upload in 4KB chunks
            mv = memoryview(pcm_data)
            offset = 0
            chunk_size = 4096
            while offset < len(pcm_data):
                end = min(offset + chunk_size, len(pcm_data))
                ss.write(mv[offset:end])
                offset = end

            # Read response
            resp_data = bytearray()
            while True:
                buf = ss.read(1024)
                if not buf:
                    break
                resp_data.extend(buf)

            resp_str = resp_data.decode("utf-8", "ignore")
            body_start = resp_str.find("\r\n\r\n")
            if body_start != -1:
                body = resp_str[body_start + 4:]
                data = json.loads(body)
                channels = data.get("results", {}).get("channels", [])
                if channels:
                    alts = channels[0].get("alternatives", [])
                    if alts:
                        raw_transcript = alts[0].get("transcript", "")
                        cleaned = self.clean_transcript(raw_transcript)
                        print(f"[Deepgram] Transcription: '{cleaned}' (raw: '{raw_transcript}')")
                        return cleaned
                print("[Deepgram] No transcript in response:", data)
                return ""
            else:
                print("[Deepgram] Invalid HTTP response:", resp_str[:120])
                return ""

        except Exception as e:
            print("[Deepgram] Request error:", e)
            return ""
        finally:
            if ss:
                try:
                    ss.close()
                except Exception:
                    pass
            gc.collect()

    def clean_transcript(self, text: str) -> str:
        """Normalizes transcript: lower-case, remove punctuation, normalize spaces."""
        text = text.lower()
        cleaned = []
        for ch in text:
            if ("a" <= ch <= "z") or ("0" <= ch <= "9") or (ch == " "):
                cleaned.append(ch)
        return " ".join("".join(cleaned).split())
