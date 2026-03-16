#!/usr/bin/env python3
"""
ReaStream Bridge — WASAPI-to-ReaStream audio bridge with clock drift correction.

Replaces VSTHost in the chain:
    Spotify -> VB-Cable -> [THIS SCRIPT] -> ReaStream UDP -> FL Studio

How it works:
  1. Opens VB-Cable via WASAPI (blocksize=0 to avoid PortAudio frame drops)
  2. Buffers into a ring buffer (2+ seconds — latency is acceptable)
  3. Timer-driven sender locked to the output sample rate
  4. PI controller keeps the buffer centered, absorbing WDM/ASIO clock drift

Usage:
    python reastream_bridge.py --list                  # find your VB-Cable device index
    python reastream_bridge.py -d auto                 # auto-detect and run
    python reastream_bridge.py -d auto --test-tone     # send 440 Hz sine to verify chain

Requirements:
    pip install sounddevice numpy
"""

import argparse
import socket
import struct
import sys
import threading
import time

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print("ERROR: sounddevice not installed. Run:  pip install sounddevice")
    sys.exit(1)


# ---------------------------------------------------------------------------
# ReaStream protocol constants (reverse-engineered from VSTHost sniff)
# ---------------------------------------------------------------------------
REASTREAM_MAGIC_AUDIO = b"MRSR"
REASTREAM_HEADER_FMT = "<4sI32sBIH"  # magic, pkt_size, ident, channels, rate, audio_bytes
REASTREAM_HEADER_SIZE = struct.calcsize(REASTREAM_HEADER_FMT)  # 47
REASTREAM_DEFAULT_PORT = 58710
REASTREAM_DEFAULT_ID = "default"
REASTREAM_MAX_AUDIO_BYTES = 1200  # max audio bytes per packet


# ---------------------------------------------------------------------------
# Windows helpers
# ---------------------------------------------------------------------------
def _windows_boost():
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        ctypes.windll.winmm.timeBeginPeriod(1)
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00000080)
        h = k32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        k32.GetConsoleMode(h, ctypes.byref(mode))
        mode.value &= ~0x0040
        mode.value |= 0x0080
        k32.SetConsoleMode(h, mode)
        return True
    except Exception:
        return False


def _set_thread_priority_high():
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), 2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------
class RingBuffer:
    def __init__(self, capacity_frames, channels):
        self.capacity = capacity_frames
        self.channels = channels
        self.buf = np.zeros((capacity_frames, channels), dtype=np.float32)
        self.write_pos = 0
        self.read_pos = 0
        self.available = 0
        self._lock = threading.Lock()

    def write(self, data):
        frames = data.shape[0]
        with self._lock:
            space = self.capacity - self.available
            if frames > space:
                drop = frames - space
                self.read_pos = (self.read_pos + drop) % self.capacity
                self.available -= drop
            wp = self.write_pos
            end = wp + frames
            if end <= self.capacity:
                self.buf[wp:end] = data
            else:
                first = self.capacity - wp
                self.buf[wp:] = data[:first]
                self.buf[: frames - first] = data[first:]
            self.write_pos = end % self.capacity
            self.available += frames
        return frames

    def read(self, frames):
        with self._lock:
            n = min(frames, self.available)
            if n == 0:
                return np.zeros((0, self.channels), dtype=np.float32)
            rp = self.read_pos
            end = rp + n
            if end <= self.capacity:
                out = self.buf[rp:end].copy()
            else:
                first = self.capacity - rp
                out = np.concatenate([self.buf[rp:], self.buf[: n - first]])
            self.read_pos = end % self.capacity
            self.available -= n
        return out

    @property
    def fill_fraction(self):
        with self._lock:
            return self.available / self.capacity if self.capacity else 0.0


# ---------------------------------------------------------------------------
# ReaStream packet builder
# ---------------------------------------------------------------------------
def make_packet_builder(identifier, sample_rate, channels):
    """Return a closure that builds ReaStream packets without per-call overhead."""
    ident_bytes = identifier.encode("ascii")[:32].ljust(32, b"\x00")
    max_frames = REASTREAM_MAX_AUDIO_BYTES // (channels * 4)
    # Pre-pack the static portion of the header (magic + placeholder size + ident + ch + rate)
    # We still need to pack per-packet because pkt_size and audio_bytes vary for the last chunk.
    pack = struct.pack

    def build(audio):
        packets = []
        total_frames = audio.shape[0]
        offset = 0
        while offset < total_frames:
            n = min(max_frames, total_frames - offset)
            chunk = audio[offset : offset + n]
            audio_raw = chunk.T.astype(np.float32).tobytes()  # non-interleaved
            chunk_len = len(audio_raw)
            total_size = REASTREAM_HEADER_SIZE + chunk_len
            header = pack(
                REASTREAM_HEADER_FMT, REASTREAM_MAGIC_AUDIO, total_size,
                ident_bytes, channels, sample_rate, chunk_len,
            )
            packets.append(header + audio_raw)
            offset += n
        return packets

    return build


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------
class ReaStreamBridge:
    def __init__(self, device_index, output_rate=44100, channels=2,
                 buffer_seconds=2.0, send_block=512,
                 reastream_id=REASTREAM_DEFAULT_ID,
                 reastream_port=REASTREAM_DEFAULT_PORT,
                 target_ip="127.0.0.1", test_tone=False):
        self.device_index = device_index
        self.output_rate = output_rate
        self.channels = channels
        self.send_block = send_block      # frames per send cycle (for packet building)
        self.buffer_seconds = buffer_seconds
        self.reastream_id = reastream_id
        self.reastream_port = reastream_port
        self.target_ip = target_ip
        self.test_tone = test_tone

        cap = int(output_rate * buffer_seconds)
        self.ring = RingBuffer(cap, channels)

        self.target_fill = 0.5
        self.running = False
        self._stream = None
        self._sender = None
        self._tone_phase = 0.0
        self._capture_frames = 0
        self._capture_callbacks = 0

    def _capture_cb(self, indata, frames, time_info, status):
        self._capture_frames += indata.shape[0]
        self._capture_callbacks += 1
        self.ring.write(indata)

    def _tone_generator(self):
        freq = 440.0
        chunk = 2048
        rate = self.output_rate
        while self.running:
            fill = self.ring.fill_fraction
            if fill > 0.7:
                time.sleep(0.05)
                continue
            t = (np.arange(chunk) + self._tone_phase) / rate
            sine = np.sin(2 * np.pi * freq * t) * 0.25
            stereo = np.column_stack([sine, sine])
            self.ring.write(stereo)
            self._tone_phase += chunk
            if fill > 0.4:
                time.sleep(0.01)

    def _sender_loop(self):
        _set_thread_priority_high()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
        except OSError:
            pass
        dest = (self.target_ip, self.reastream_port)
        sendto = sock.sendto  # avoid attribute lookup in hot loop
        send_block = self.send_block
        out_rate = self.output_rate
        send_interval = send_block / out_rate  # e.g. 512/44100 = 11.6ms
        build_packets = make_packet_builder(self.reastream_id, out_rate, self.channels)

        # Pre-allocate resampling arrays (PI correction keeps read count near send_block,
        # so we size for ±10% and lazily reallocate only if that's exceeded)
        _resample_cap = int(send_block * 1.15)
        _resample_indices = np.linspace(0, 1, send_block, dtype=np.float32)
        _resample_frac = np.empty((send_block, 1), dtype=np.float32)

        # Wait for buffer to reach target fill
        print("  Filling buffer...")
        while self.running and self.ring.fill_fraction < self.target_fill:
            time.sleep(0.02)
        if not self.running:
            return
        print(f"  Buffer ready ({self.ring.fill_fraction:.0%}). Transmitting.\n")

        # PI controller — keeps buffer centered at 50%
        Kp = 0.03
        Ki = 0.005
        integral_error = 0.0
        sample_debt = 0.0

        perf_counter = time.perf_counter
        next_send = perf_counter()
        stats_t = next_send
        pkts = 0
        underruns = 0
        last_capture_frames = self._capture_frames
        frames_sent = 0

        while self.running:
            now = perf_counter()
            if now < next_send:
                sleep_for = next_send - now
                if sleep_for > 0.0002:
                    time.sleep(sleep_for * 0.75)
                continue

            next_send += send_interval
            if now - next_send > send_interval * 2:
                next_send = now + send_interval

            # PI: adjust read amount to keep buffer centered
            fill = self.ring.fill_fraction
            fill_err = fill - self.target_fill  # positive = too full
            integral_error += fill_err * send_interval
            integral_error = max(-2.0, min(2.0, integral_error))

            correction = 1.0 + Kp * fill_err + Ki * integral_error

            read_exact = send_block * correction + sample_debt
            read_frames = max(1, int(round(read_exact)))
            sample_debt = read_exact - read_frames

            data = self.ring.read(read_frames)
            if data.shape[0] == 0:
                underruns += 1
                continue

            # Resample to exactly send_block if PI adjusted the read count
            actual = data.shape[0]
            if actual != send_block and actual >= 2:
                # Reallocate index arrays only when source length exceeds pre-allocated capacity
                if actual > _resample_cap:
                    _resample_cap = int(actual * 1.15)
                scaled = _resample_indices * (actual - 1)
                idx_floor = scaled.astype(np.intp)
                np.subtract(scaled, idx_floor, out=_resample_frac[:, 0])
                idx_ceil = np.minimum(idx_floor + 1, actual - 1)
                inv_frac = 1.0 - _resample_frac
                data = data[idx_floor] * inv_frac + data[idx_ceil] * _resample_frac

            for pkt in build_packets(data):
                try:
                    sendto(pkt, dest)
                    pkts += 1
                except OSError as e:
                    print(f"  [!] Send error: {e}")
            frames_sent += send_block

            # Stats every 5s
            if now - stats_t >= 5.0:
                elapsed = now - stats_t
                buf_ms = fill * self.buffer_seconds * 1000
                cap_delta = self._capture_frames - last_capture_frames
                cap_rate = cap_delta / elapsed
                out_actual = frames_sent / elapsed
                last_capture_frames = self._capture_frames
                frames_sent = 0
                print(
                    f"  buf {buf_ms:6.0f} ms ({fill:5.1%}) | "
                    f"capture {cap_rate:7.0f}/s | "
                    f"output {out_actual:7.0f}/s | "
                    f"pkt/s {pkts / elapsed:6.1f} | "
                    f"corr {correction:.5f} | "
                    f"underruns {underruns}"
                )
                pkts = 0
                underruns = 0
                stats_t = now

        sock.close()

    def start(self):
        self.running = True
        _windows_boost()

        if self.test_tone:
            print(f"  Mode: test tone (440 Hz sine)")
            t = threading.Thread(target=self._tone_generator, daemon=True)
            t.start()
        else:
            # Try WASAPI modes in order of preference:
            #  1. Exclusive mode — bypasses Windows audio mixer entirely,
            #     gives us direct device access at the exact sample rate
            #  2. Shared mode with auto_convert — lets WASAPI handle rate
            #     conversion properly instead of dropping frames
            #  3. Plain shared mode — last resort
            #
            # blocksize=0 always — avoids PortAudio rebuffering frame drops
            # (see python-sounddevice issue #127)

            modes = [
                ("exclusive", sd.WasapiSettings(exclusive=True)),
                ("shared+auto_convert", sd.WasapiSettings(auto_convert=True)),
                ("shared (plain)", None),
            ]

            opened = False
            for mode_name, extra in modes:
                try:
                    kwargs = dict(
                        device=self.device_index,
                        samplerate=self.output_rate,
                        channels=self.channels,
                        dtype="float32",
                        blocksize=0,
                        callback=self._capture_cb,
                    )
                    if extra is not None:
                        kwargs["extra_settings"] = extra
                    self._stream = sd.InputStream(**kwargs)
                    self._stream.start()
                    self._wasapi_mode = mode_name
                    opened = True
                    print(f"  WASAPI mode: {mode_name}")
                    break
                except Exception as e:
                    print(f"  [!] {mode_name} failed: {e}")

            if not opened:
                print("  [!] Could not open audio device in any mode.")
                self.running = False
                return

        self._sender = threading.Thread(target=self._sender_loop, daemon=True)
        self._sender.start()

        wmode = getattr(self, '_wasapi_mode', 'test-tone')
        print(f"""
  ╔══════════════════════════════════════════════════════════╗
  ║  ReaStream Bridge running                               ║
  ╠══════════════════════════════════════════════════════════╣
  ║  Device:      {str(self.device_index):>6s}                                 ║
  ║  Sample rate: {self.output_rate:>6d} Hz                              ║
  ║  WASAPI:      {wmode:<40s}  ║
  ║  Channels:    {self.channels:>6d}                                 ║
  ║  Send block:  {self.send_block:>6d} samples                        ║
  ║  Buffer:      {self.buffer_seconds:>6.1f} s  (target fill 50%)          ║
  ║  ReaStream:   {self.target_ip}:{self.reastream_port:<5d}  id="{self.reastream_id}"      ║
  ╚══════════════════════════════════════════════════════════╝
  Press Ctrl+C to stop.
""")

    def stop(self):
        self.running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
        if self._sender:
            self._sender.join(timeout=2.0)
        print("\n  Bridge stopped.")


# ---------------------------------------------------------------------------
# Device listing
# ---------------------------------------------------------------------------
def list_devices():
    devs = sd.query_devices()
    apis = {i: sd.query_hostapis(i)["name"] for i in range(len(sd.query_hostapis()))}
    print("\n  Available audio input devices:\n")
    print(f"  {'Idx':>4s}  {'Name':<45s} {'In':>3s}  {'Rate':>6s}  {'API'}")
    print(f"  {'---':>4s}  {'----':<45s} {'--':>3s}  {'----':>6s}  {'---'}")
    for i, d in enumerate(devs):
        if d["max_input_channels"] > 0:
            api_name = apis.get(d["hostapi"], "?")
            marker = " <-- VB-Cable?" if "cable" in d["name"].lower() else ""
            print(
                f"  [{i:3d}]  {d['name']:<45s} {d['max_input_channels']:>3d}  "
                f"{int(d['default_samplerate']):>6d}  {api_name}{marker}"
            )
    print()


def find_vb_cable():
    devs = sd.query_devices()
    apis = {i: sd.query_hostapis(i)["name"] for i in range(len(sd.query_hostapis()))}
    candidates = []
    for i, d in enumerate(devs):
        if d["max_input_channels"] > 0 and "cable" in d["name"].lower():
            api = apis.get(d["hostapi"], "")
            priority = 2 if "wasapi" in api.lower() else (1 if "wdm" in api.lower() else 0)
            candidates.append((priority, i, d["name"], api))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, idx, name, api = candidates[0]
    print(f"  Auto-detected VB-Cable: [{idx}] {name} ({api})")
    return idx


# ---------------------------------------------------------------------------
# Sniff mode
# ---------------------------------------------------------------------------
def sniff_reastream(port=REASTREAM_DEFAULT_PORT, count=10):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as e:
        print(f"  [!] Cannot bind to port {port}: {e}")
        return
    print(f"\n  Listening for ReaStream packets on port {port}  ({count} packets)...\n")
    for i in range(count):
        data, addr = sock.recvfrom(65536)
        size = len(data)
        print(f"  --- Packet {i+1} from {addr[0]}:{addr[1]}  ({size} bytes) ---")
        header_hex = data[:min(52, size)].hex(" ")
        print(f"  Raw header: {header_hex}")
        if size >= REASTREAM_HEADER_SIZE:
            try:
                magic, pkt_size, ident, ch, sr, bs = struct.unpack_from(REASTREAM_HEADER_FMT, data, 0)
                ident_str = ident.split(b"\x00")[0].decode("ascii", errors="replace")
                audio_len = size - REASTREAM_HEADER_SIZE
                print(f"  Decoded: magic={magic} pkt_size={pkt_size} id=\"{ident_str}\"")
                print(f"           ch={ch} rate={sr} audio_bytes={bs} payload={audio_len}")
            except Exception as e:
                print(f"  Decode error: {e}")
        print()
    sock.close()
    print("  Sniff complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="ReaStream Bridge — WASAPI to ReaStream with drift correction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list                          List audio devices
  %(prog)s -d auto                         Auto-detect VB-Cable and run
  %(prog)s -d 5                            Bridge device 5
  %(prog)s -d auto --test-tone             Send 440 Hz sine (verify chain)
  %(prog)s -d auto -r 48000                Use 48000 Hz (match FL Studio)
        """,
    )
    p.add_argument("--list", "-l", action="store_true", help="List input devices")
    p.add_argument("--device", "-d", default=None, help="Device index or 'auto'")
    p.add_argument("--rate", "-r", type=int, default=44100,
                   help="Sample rate — must match FL Studio AND VB-Cable (default 44100)")
    p.add_argument("--channels", "-c", type=int, default=2)
    p.add_argument("--buffer", "-b", type=float, default=2.0, help="Ring buffer seconds (default 2.0)")
    p.add_argument("--send-block", type=int, default=512, help="Frames per send cycle (default 512)")
    p.add_argument("--reastream-id", default=REASTREAM_DEFAULT_ID)
    p.add_argument("--port", "-p", type=int, default=REASTREAM_DEFAULT_PORT)
    p.add_argument("--ip", default="127.0.0.1")
    p.add_argument("--test-tone", action="store_true", help="Send 440 Hz sine instead of capturing")
    p.add_argument("--sniff", action="store_true", help="Listen for ReaStream packets (debug)")
    p.add_argument("--sniff-count", type=int, default=10)

    args = p.parse_args()

    if args.list:
        list_devices()
        return
    if args.sniff:
        sniff_reastream(port=args.port, count=args.sniff_count)
        return

    dev_idx = None
    if args.device is None or args.device.lower() == "auto":
        dev_idx = find_vb_cable()
        if dev_idx is None:
            print("  Could not auto-detect VB-Cable. Use --list and specify -d <index>.")
            return
    else:
        try:
            dev_idx = int(args.device)
        except ValueError:
            print(f"  Invalid device: {args.device}")
            return

    bridge = ReaStreamBridge(
        device_index=dev_idx,
        output_rate=args.rate,
        channels=args.channels,
        buffer_seconds=args.buffer,
        send_block=args.send_block,
        reastream_id=args.reastream_id,
        reastream_port=args.port,
        target_ip=args.ip,
        test_tone=args.test_tone,
    )
    bridge.start()

    try:
        while bridge.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        bridge.stop()


if __name__ == "__main__":
    main()
