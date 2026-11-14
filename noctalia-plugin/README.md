# VanishCam (Noctalia v4 Plugin)

Live virtual webcam controller for [VanishCam](https://github.com/Mhdomer/vanish_webcam) on Wayland (`Niri`, `Hyprland`, `Sway`) using `v4l2loopback`.

## Features

- **Zero-Fork Live Bar Capsule (`BarWidget.qml`):** Reads `/tmp/vanish_cam.state.json` via `FileView` with zero subprocess forks, showing live status (`OFF`, `CALIB`, `SNAP`, `FROZEN`, `PAUSED`, `VANISHED`).
- **Studio Control Panel (`Panel.qml`):**
  - Start / Stop virtual webcam (`/dev/video2`).
  - **Vanish Now (`V`) / Reappear Smoothly (`R`)** across all 6 modes (including Goku Instant Transmission and Itachi Crows).
  - **Freeze Frame (`Z`)** (0% MediaPipe CPU while frozen), **Blur Room (`W`)** (lightweight downscaled portrait blur), and **Ghost Echo (`E`)** spectral replay.
  - **Headless Default & Eco Mode (`540p @ 24 FPS`):** Starts cleanly without an extra preview window (`startHidden: true` in settings), with optional Eco resolution/FPS scaling to minimize CPU heat.
  - **Pause / Resume Hand Gestures (`G`)** and **Show / Hide Local Preview (`P`)**.
  - **6-Mode Live Hot-Swap Grid:** Switch between `Snap Void`, `Naruto`, `Normal`, `Particles`, `Itachi`, and `Goku` without restarting `/dev/video0` or `/dev/video2`.
  - **Editable Snap Void Particle Excuse:** Type any custom message (`COFFEE BREAK`, `5 MIN`, etc.) or pick from one-click presets (`BRB...`, `GONE`, `AFK`, `MY INTERNET DIED`, `IN A MEETING`).
  - **Room Calibration:** Instant 0s load of saved room frame (`B`) or 7s recapture countdown (`SPACE`).

## Requirements

- [Mhdomer/vanish_webcam](https://github.com/Mhdomer/vanish_webcam) installed with `vanish-cam` in `~/.local/bin` or `PATH`.
- `v4l2loopback-dkms` loaded with `exclusive_caps=1 card_label="VanishCam"`.
