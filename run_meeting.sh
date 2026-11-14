#!/usr/bin/env bash
# Start VanishCam as a v4l2loopback virtual webcam on Linux (Wayland/Niri friendly).
# Usage: ./run_meeting.sh [extra vanish_cam.py args], e.g. ./run_meeting.sh --mode goku
set -euo pipefail

REPO="$(dirname "$(readlink -f "$0")")"
PYTHON="$REPO/.venv/bin/python"

find_device() {
    for dev in /sys/class/video4linux/video*; do
        [[ -r "$dev/name" ]] && [[ "$(<"$dev/name")" == "VanishCam" ]] && echo "/dev/$(basename "$dev")" && return
    done
}

if [[ ! -d /sys/module/v4l2loopback ]]; then
    echo "[run_meeting] Loading v4l2loopback (sudo needed)..."
    sudo modprobe v4l2loopback exclusive_caps=1 card_label="VanishCam"
fi

DEVICE="$(find_device)"
if [[ -z "$DEVICE" ]]; then
    echo "[run_meeting] v4l2loopback is loaded but no 'VanishCam' device found." >&2
    echo "Reload it with: sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback exclusive_caps=1 card_label=VanishCam" >&2
    exit 1
fi

if holders="$(fuser /dev/video0 2>/dev/null | xargs)" && [[ -n "$holders" ]]; then
    echo "[run_meeting] /dev/video0 is busy. Stop the webcam in the browser tab or app below, then retry:" >&2
    ps -o pid=,comm= -p "${holders// /,}" >&2 || true
    exit 1
fi

ARGS=("$@")
[[ " ${ARGS[*]} " == *" --mode "* ]] || ARGS+=(--mode naruto)
[[ " ${ARGS[*]} " == *" --camera "* ]] || ARGS+=(--camera 0)
[[ " ${ARGS[*]} " == *" --bg-delay "* ]] || ARGS+=(--bg-delay 7)
[[ " ${ARGS[*]} " == *" --async-gestures "* ]] || ARGS+=(--async-gestures)
[[ " ${ARGS[*]} " == *" --preview-hud "* ]] || ARGS+=(--preview-hud)

echo "[run_meeting] Virtual camera: $DEVICE (pick 'VanishCam' in your meeting app)"
# The pip OpenCV build only ships the Qt xcb plugin, so route this app through XWayland.
QT_QPA_PLATFORM=xcb exec "$PYTHON" "$REPO/vanish_cam.py" \
    --virtual-camera --virtual-backend v4l2loopback --virtual-device "$DEVICE" "${ARGS[@]}"
