# VanishCam (Linux & Meeting Edition)

Real-time webcam disappearance effects for video meetings, forked from [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) with Linux `v4l2loopback` integration, Wayland/XWayland support, V4L2 30 FPS fixes, an English UI, and the **Snap Void** mode inspired by [turfin-logic/atomic-snap-vanish](https://github.com/turfin-logic/atomic-snap-vanish) (MIT).

Video is processed locally on your computer. Nothing is recorded or sent to a server. Any countdowns, status pills, and hotkey overlays appear **only** in your local preview window and are never sent to the virtual camera feed.

---

## Modes

| Mode | Trigger Gesture | Visual Effect | Audio |
|---|---|---|---|
| `naruto` (default) | Palms together in front of chest (fingers side by side) | Smoke puff and falling wooden log | `assets/vanish.MP3` |
| `snap` | Pinch thumb + middle finger, then snap apart (peace sign to rebuild) | Dissolve -> blackhole vortex -> particle excuse text (`BRB...`, `GONE`, `AFK`, `MY INTERNET DIED`, `IN A MEETING`) -> dust crumble | `assets/snap.wav` & `assets/chime.wav` |
| `normal` | V sign (index + middle) | Silhouette dissolves upward with sparkles (~3.6s) | None |
| `particles` | V sign (index + middle) | Silhouette breaks into wind-drifted fragments (~2.1s) | None |
| `goku` | Index + middle fingers held together on forehead | Instant Transmission speed lines & teleport (repeat gesture to return; `V`/`R` disabled) | `assets/teleport.MP3` |
| `itachi` | Both hands touching in front of chest | Crow swarm dispersion, blood-red tint, Sharingan flash (repeat gesture or `R` to reform) | None |

---

## Linux Setup (CachyOS / Arch + Wayland/Niri)

### 1. Python Environment (Python 3.12)
`mediapipe==1.0.1` requires Python 3.12 (system Python 3.14 is not supported). Use `uv` to create `.venv`:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

### 2. Virtual Camera (`v4l2loopback`)
Install the DKMS module and headers for your kernels:

```bash
sudo pacman -S v4l2loopback-dkms linux-cachyos-headers linux-cachyos-lts-headers
```

The launcher script loads `v4l2loopback` with `exclusive_caps=1` (`card_label="VanishCam"`) so Chromium-based browsers (Google Meet, Discord, Zoom) enumerate `/dev/video2` (`VanishCam`) as a capture device.

### 3. Running for a Meeting
Close any browser tab or app holding `/dev/video0`, then start the launcher:

```bash
./run_meeting.sh
```

In your meeting app (Google Meet, Zoom, Teams, Discord), select **VanishCam** as your camera.

Useful launch options:
```bash
./run_meeting.sh --mode snap --snap-text "COFFEE BREAK"
./run_meeting.sh --mode snap --reuse-bg        # 0s startup using saved room frame
./run_meeting.sh --mode goku
./run_meeting.sh --no-mirror                   # Send unmirrored video to the meeting
./run_meeting.sh --width 640 --height 360      # Lower CPU/battery draw
./run_meeting.sh --bg-delay 10                 # Custom background capture countdown
```

---

## What Changed From Upstream

### Performance & Linux Fixes
- **V4L2 + MJPG + `buffersize=2` (`vanish_cam.py`):** On Linux UVC webcams, OpenCV's default `YUYV` format capped capture at ~7.4 fps at `960x540`, and `CAP_PROP_BUFFERSIZE=1` halved `MJPG` throughput to ~15.3 fps. Explicitly using `cv2.CAP_V4L2`, `MJPG`, and `buffersize=2` restores full **~29.9 fps** capture.
- **Async Gesture Worker (`--async-gestures`):** Offloads MediaPipe gesture/hand detection for `normal`, `naruto`, and `particles` onto a single-worker `ThreadPoolExecutor` so 30 to 85 ms fallback detections never stall the 30 fps virtual camera stream.
- **Zero-Copy Virtual Send:** Skips `np.ascontiguousarray()` when frames are already contiguous.
- **Wayland/Niri Qt Workaround (`run_meeting.sh`):** Pip `opencv-contrib-python` ships only the `xcb` Qt plugin. `run_meeting.sh` sets `QT_QPA_PLATFORM=xcb` per process to route the preview window through `xwayland-satellite` without altering global desktop Qt settings.

### UX & Meeting Controls
- **English UI & Logs:** Translated `goku_settings.py`, `vanish_cam.py` menus, CLI `--help`, and terminal output to English.
- **Preview-Only Countdown & Status HUD:** Shows a clear countdown banner (`STEP OUT OF FRAME: 7s` -> `CAPTURING EMPTY ROOM...` -> `BACKGROUND READY!`), a subtle bottom status pill, and an on-demand hotkey cheat sheet (`H`) strictly in the local preview window (never sent to the virtual camera).
- **Saved Background (`--reuse-bg` / `B`):** Automatically saves your clean room background locally to `assets/last_bg.png` (git-ignored) so you can start future meetings in 0 seconds.
- **Gesture Pause (`G`):** Toggles gesture detection on/off so talking with your hands never triggers an accidental vanish mid-sentence.

---

## Controls (Preview Window Focused)

- `H`: Toggle hotkey cheat sheet overlay
- `SPACE`: Recapture empty room background (`ENTER` during countdown captures immediately)
- `B`: Load last saved room background (`assets/last_bg.png`)
- `G`: Pause / resume gesture detection
- `V`: Manually trigger the active vanish effect (disabled in `goku` mode)
- `R`: Reappear / rebuild (disabled in `goku` mode)
- `T`: Cycle Snap mode excuse text (`BRB...`, `GONE`, `AFK`, `MY INTERNET DIED`, `IN A MEETING`, or custom `--snap-text`)
- `F`: Toggle fullscreen
- `Q` or `ESC`: Quit and release cameras

---

## Windows Executables (Upstream)

Original Windows `.bat` scripts (`AVVIA_LOCALE.bat`, `AVVIA_OBS.bat`, `AVVIA_VIRTUAL.bat`, `BUILD_WINDOWS.bat`) and Firebase licensing client (`license_client.py`, `licensing_backend/`) remain in the repo from upstream. Running `vanish_cam.py` directly from Python skips the license check.

---

## Credits

- Original project by [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) (support the author via [PayPal](https://paypal.me/nicovic17) or [Revolut](https://revolut.me/nicoauriemma)).
- Snap Void effect (`snap_effect.py`, `assets/snap.wav`, `assets/chime.wav`) adapted from [turfin-logic/atomic-snap-vanish](https://github.com/turfin-logic/atomic-snap-vanish) (MIT License).
