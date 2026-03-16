"""
ReaStream Bridge — System Tray launcher.

Runs reastream_bridge.py silently in the background with a system tray icon.
Right-click the tray icon to see status or quit.

Requirements (one-time):
    pip install pystray Pillow sounddevice numpy
"""

import os
import sys
import threading
import time

# Ensure we can import the bridge module from the same directory
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Redirect stdout/stderr to a log file (no console in .pyw mode)
# encoding="utf-8" is critical — the bridge prints Unicode box chars (╔═╗)
# and Windows default codepage (cp1252) can't encode them
log_path = os.path.join(script_dir, "bridge.log")
log_file = open(log_path, "w", encoding="utf-8", buffering=1)
sys.stdout = log_file
sys.stderr = log_file

import pystray
from PIL import Image, ImageDraw, ImageFont

from reastream_bridge import ReaStreamBridge, find_vb_cable, _windows_boost


# ---------------------------------------------------------------------------
# Tray icon image (green "R" on dark background)
# ---------------------------------------------------------------------------
def create_icon_image(color="lime"):
    img = Image.new("RGBA", (64, 64), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    # Try to use a nice font, fall back to default
    try:
        font = ImageFont.truetype("arial.ttf", 44)
    except Exception:
        font = ImageFont.load_default()
    draw.text((14, 6), "R", fill=color, font=font)
    return img


# ---------------------------------------------------------------------------
# Bridge runner
# ---------------------------------------------------------------------------
class BridgeTray:
    def __init__(self):
        self.bridge = None
        self.icon = None
        self.status = "Starting..."
        self._monitor_thread = None

    def _run_bridge(self):
        """Start the bridge in the background."""
        try:
            dev_idx = find_vb_cable()
            if dev_idx is None:
                self.status = "ERROR: VB-Cable not found"
                return

            self.bridge = ReaStreamBridge(
                device_index=dev_idx,
                output_rate=44100,
                channels=2,
                buffer_seconds=2.0,
                send_block=512,
            )
            self.bridge.start()
            self.status = "Running"

            # Monitor loop — update status periodically
            while self.bridge.running:
                time.sleep(2.0)
                fill = self.bridge.ring.fill_fraction
                buf_ms = fill * self.bridge.buffer_seconds * 1000
                self.status = f"Running — buf {buf_ms:.0f}ms ({fill:.0%})"
                if self.icon:
                    self.icon.title = f"ReaStream Bridge: {self.status}"

        except Exception as e:
            self.status = f"ERROR: {e}"
            print(f"Bridge error: {e}", flush=True)

    def _on_quit(self, icon, item):
        """Handle quit from tray menu."""
        self.status = "Stopping..."
        if self.bridge:
            self.bridge.stop()
        icon.stop()

    def _get_status(self, item):
        return self.status

    def run(self):
        """Main entry point — sets up tray icon and starts bridge."""
        # Start bridge in background thread
        bridge_thread = threading.Thread(target=self._run_bridge, daemon=True)
        bridge_thread.start()

        # Give bridge a moment to start
        time.sleep(0.5)

        # Create tray icon
        menu = pystray.Menu(
            pystray.MenuItem(self._get_status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

        self.icon = pystray.Icon(
            name="ReaStream Bridge",
            icon=create_icon_image(),
            title=f"ReaStream Bridge: {self.status}",
            menu=menu,
        )

        # This blocks until icon.stop() is called
        self.icon.run()

        # Cleanup
        if self.bridge and self.bridge.running:
            self.bridge.stop()

        log_file.close()


if __name__ == "__main__":
    app = BridgeTray()
    app.run()
