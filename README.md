# ReaStream Bridge

Routes desktop audio into any DAW over UDP using the [ReaStream](https://www.reaper.fm/reaplugs/) protocol. Fixes the WDM/ASIO clock drift crackling you get with VSTHost and similar tools.

Works with any DAW that can load VST plugins — FL Studio, Reaper, Ableton, Cubase, Bitwig, etc. Just load ReaStream as a VST on a track/mixer channel and set it to receive.

```
Spotify/Discord/etc → VB-Cable → [ReaStream Bridge] → UDP → Your DAW
```

## Why this exists

DAWs typically run on ASIO (hardware clock). Desktop apps use WASAPI/WDM (Windows clock). These clocks drift apart over time, causing crackling. This bridge captures from VB-Cable in WASAPI exclusive mode, buffers 2 seconds of audio, and uses a PI controller to keep the buffer centered at 50% — absorbing drift silently.

## Use case: low-latency instruments + Spotify over Discord screenshare

The main problem this solves: you want to use ASIO in your DAW for low-latency live instrument monitoring, but you also want Spotify/YouTube/Discord audio playing inside the DAW so that when you screenshare your DAW window on Discord, viewers hear everything — your instruments and your music — synced together.

The full signal chain:

```
Spotify → VB-Cable → [ReaStream Bridge] → UDP → DAW mixer (ReaStream receive)
                                                      ↓
Guitar/Mic → Audio Interface (ASIO) ──────────→ DAW mixer
                                                      ↓
                                              DAW master out → ASIO → headphones
                                                      ↓
                                              Voxengo Recorder → MME device
                                                      ↓
                                              Discord screenshare captures DAW window + audio
```

Your instruments stay on ASIO with minimal latency. Spotify audio arrives through the bridge with ~2s delay (not audible to Discord viewers since they're hearing everything through the same output). Discord screenshare picks up the DAW window audio via [Voxengo Recorder](https://www.voxengo.com/product/recorder/).

### Voxengo Recorder setup

[Voxengo Recorder](https://www.voxengo.com/product/recorder/) is a free VST plugin that mirrors your DAW's master output to an MME device, which is what Discord can capture during screenshare.

![Voxengo Recorder settings](voxengo_settings.png)

1. Download and install [Voxengo Recorder](https://www.voxengo.com/product/recorder/)
2. Load it as a VST on your DAW's master bus
3. Set **Output To** to **MME**
4. Set the **MME Device** to any output device you're not listening through — it just needs to exist so Discord can see audio coming from the DAW window. A disabled onboard sound card output, a secondary VB-Cable, or any unused MME device works.
5. Set **Bit Depth** to 32, **Buffer Count** and **Buffer Size** to taste (16/512 is fine)
6. Click **Start**

Now when you screenshare your DAW window on Discord, Discord captures the audio Voxengo is sending to that MME device. Viewers hear your instruments and Spotify together.

## Setup

### Prerequisites
- [VB-Cable](https://vb-audio.com/Cable/) — virtual audio cable (free)
- [ReaPlugs VST](https://www.reaper.fm/reaplugs/) — contains the ReaStream plugin
- Python 3.10+

### Install
```
pip install -r requirements.txt
```

### Configure

1. **VB-Cable sample rate**: Open Windows Sound Settings → Playback → "CABLE Input" → Properties → Advanced → set to **44100 Hz**. Do the same for Recording → "CABLE Output".

2. **Desktop app output**: Set whatever app you want to route (Spotify, Discord, browser, etc.) to output to "CABLE Input (VB-Cable)".

3. **Your DAW** (FL Studio example, but any DAW works):
   - Audio settings → make sure sample rate is **44100 Hz** (must match VB-Cable)
   - Add **ReaStream** (from ReaPlugs) to a mixer insert
   - Set ReaStream to **Receive** mode
   - Set the identifier to `default`

4. **FL Studio only — fixed size buffers**: Go to Options → Audio Settings → open the **Troubleshooting** section → enable **Fixed size buffers**. Without this, FL Studio feeds ReaStream variable-length audio blocks, which causes it to drop incoming UDP packets and you'll get silence or stuttering. This doesn't affect other DAWs.

### The `default` identifier

ReaStream uses a text identifier to match senders and receivers on the same network. Both sides must use the same string. This bridge sends on identifier `default` by default, which matches ReaStream's own default. If you're running multiple bridges or have other ReaStream traffic, change it with `--reastream-id myname` and set the same string in the ReaStream plugin.

### Run
```
python reastream_bridge.py -d auto              # auto-detect VB-Cable
python reastream_bridge.py --list               # list audio devices
python reastream_bridge.py -d auto --test-tone  # 440 Hz sine to verify the chain
python reastream_bridge.py -d auto -r 48000     # match FL Studio at 48k
```

### System tray mode
```
pythonw bridge_tray.pyw
```
Green "R" icon in the tray. Hover for buffer status, right-click to quit.

### Auto-start on login
Run `install_startup.bat` — creates a startup shortcut for the tray app. Remove with `remove_startup.bat`.

## Deep setup — WASAPI exclusive mode

The bridge tries three capture modes in order:

1. **WASAPI exclusive** — bypasses the Windows audio mixer entirely. Direct device access, no resampling, no mixing. This is the best mode. For it to work, VB-Cable's sample rate in Windows Sound Settings *must exactly match* the `--rate` argument (default 44100).

2. **WASAPI shared + auto_convert** — falls back here if exclusive fails (e.g. another app has exclusive access). Windows handles resampling. Untested — may or may not work well.

3. **WASAPI shared (plain)** — last resort. Untested. May have sample rate mismatches.

The bridge uses `blocksize=0` in all modes, which tells PortAudio to deliver frames as they arrive from the hardware instead of rebuffering into fixed-size chunks. This avoids the frame-drop bug that plagues VSTHost.

### Tuning

| Flag | Default | What it does |
|------|---------|--------------|
| `-b` | `2.0` | Ring buffer size in seconds. Larger = more latency but more resilient to jitter. 2s is plenty. |
| `--send-block` | `512` | Frames per send cycle. Smaller = lower latency, more CPU. 512 at 44100 Hz = ~11.6ms per cycle. |
| `-r` | `44100` | Sample rate. Must match VB-Cable AND your DAW. |
| `--ip` | `127.0.0.1` | Target IP. Change for sending to another machine. |
| `-p` | `58710` | UDP port. Standard ReaStream port. |

### Debugging

```
python reastream_bridge.py --sniff         # listen for incoming ReaStream packets
python reastream_bridge.py --sniff --sniff-count 20
```

The bridge prints stats every 5 seconds: buffer fill, capture rate, output rate, PI correction factor, and underrun count. If the correction factor drifts far from 1.00000, something is wrong with sample rate matching.

## Wire format

ReaStream UDP packets (reverse-engineered):

```
Offset  Type        Field
0       char[4]     Magic "MRSR"
4       uint32      Packet size (header + audio)
8       char[32]    Identifier (null-padded ASCII)
40      uint8       Channels
41      uint32      Sample rate
45      uint16      Audio byte count
47      float32[]   Audio data (non-interleaved: all ch0 samples, then all ch1 samples)
```

## License

MIT
