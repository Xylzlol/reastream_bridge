# ReaStream Bridge

Routes Spotify audio into FL Studio via ReaStream UDP, solving the WDM/ASIO clock drift problem that causes crackling in VSTHost and similar tools.

```
Spotify → VB-Cable → [ReaStream Bridge] → ReaStream UDP → FL Studio
```

## Why

FL Studio uses ASIO (hardware clock). Spotify uses WASAPI/WDM (Windows clock). These two clocks drift apart, causing crackling. This bridge captures from VB-Cable in **WASAPI exclusive mode**, buffers generously (2s), and sends on a precise timer with a PI controller that keeps the buffer centered — absorbing drift silently.

## Setup

### Prerequisites
- [VB-Cable](https://vb-audio.com/Cable/) — set as Spotify's output device
- [FL Studio](https://www.image-line.com/) with ReaStream receiver plugin on the mixer
- Python 3.10+

### Install
```bash
pip install -r requirements.txt
```

### Configure
1. **Windows Sound Settings**: Set VB-Cable (both Playback "CABLE Input" and Recording "CABLE Output") to **44100 Hz**
2. **Spotify**: Output device → CABLE Input (VB-Cable)
3. **FL Studio**: Audio settings → sample rate **44100 Hz**. Add **ReaStream** plugin to a mixer channel, set to "Receive" on identifier `default`

### Run
```bash
# Auto-detect VB-Cable and bridge to FL Studio
python reastream_bridge.py -d auto

# List devices (find your VB-Cable index)
python reastream_bridge.py --list

# Test with 440 Hz sine (verify chain without Spotify)
python reastream_bridge.py -d auto --test-tone

# Use 48000 Hz (match your FL Studio if it's not at 44100)
python reastream_bridge.py -d auto -r 48000
```

### Run in system tray (silent)
```bash
pip install pystray Pillow
pythonw bridge_tray.pyw
```
Green "R" appears in system tray. Hover for buffer status, right-click to quit.

### Auto-start on login
Double-click `install_startup.bat` — creates a shortcut in `shell:startup`.
To remove: run `remove_startup.bat`.

## How it works

1. **WASAPI exclusive capture** (`blocksize=0`) — bypasses the Windows audio mixer, gets frames directly from VB-Cable at the exact sample rate with no frame drops
2. **Ring buffer** (2 seconds) — absorbs any jitter or timing variation
3. **Timer-driven sender** — fires every `send_block / sample_rate` seconds, locked to the output clock
4. **PI controller** — monitors buffer fill level (target 50%) and micro-adjusts the read amount per cycle to keep input and output rates matched. Correction stays within ~0.1% under normal conditions
5. **ReaStream UDP packets** — reverse-engineered wire format matching VSTHost: 47-byte header, non-interleaved float32 audio, max 1200 bytes per packet

## ReaStream wire format

```
Offset  Type        Field
0       char[4]     Magic "MRSR"
4       uint32      Packet size (header + audio)
8       char[32]    Identifier (null-padded ASCII)
40      uint8       Channels
41      uint32      Sample rate
45      uint16      Audio byte count
47      float32[]   Audio data (non-interleaved)
```

## License

MIT
