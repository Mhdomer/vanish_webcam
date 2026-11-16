#!/usr/bin/env bash
# Start VanishCam as a v4l2loopback virtual webcam on Linux (Wayland/Niri friendly).
# Usage: ./run_meeting.sh [extra vanish_cam.py args], e.g. ./run_meeting.sh --mode goku
set -euo pipefail

REPO="$(dirname "$(readlink -f "$0")")"
PYTHON="$REPO/.venv/bin/python"

notify_err() {
    echo "$1" >&2
    command -v notify-send >/dev/null 2>&1 && notify-send -u critical -a "VanishCam" "VanishCam Error" "$1" || true
}

find_device() {
    for dev in /sys/class/video4linux/video*; do
        [[ -r "$dev/name" ]] && [[ "$(<"$dev/name")" == "VanishCam" ]] && echo "/dev/$(basename "$dev")" && return
    done
}

find_physical_camera() {
    local dev idx path
    for dev in $(ls -1dv /sys/class/video4linux/video* 2>/dev/null); do
        [[ -r "$dev/name" ]] || continue
        [[ "$(<"$dev/name")" == "VanishCam" ]] && continue
        path="/dev/$(basename "$dev")"
        idx="${path#/dev/video}"
        if command -v v4l2-ctl >/dev/null 2>&1; then
            v4l2-ctl -d "$path" --info 2>/dev/null | awk '/Device Caps/{f=1} f && /Video Capture/{ok=1} END{exit !ok}' || continue
        fi
        echo "$idx"
        return
    done
}

if [[ ! -d /sys/module/v4l2loopback ]]; then
    echo "[run_meeting] Loading v4l2loopback (sudo needed)..."
    sudo modprobe v4l2loopback exclusive_caps=1 card_label="VanishCam"
fi

DEVICE="$(find_device)"
if [[ -z "$DEVICE" ]]; then
    notify_err "[run_meeting] v4l2loopback loaded, but no 'VanishCam' device found."
    echo "Reload it with: sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback video_nr=10 exclusive_caps=1 card_label=VanishCam" >&2
    exit 1
fi

ARGS=("$@")
CAMERA_IDX=""
for ((i=0; i<${#ARGS[@]}; i++)); do
    if [[ "${ARGS[i]}" == "--camera" ]] && (( i + 1 < ${#ARGS[@]} )); then
        CAMERA_IDX="${ARGS[i+1]}"
        break
    fi
done
if [[ -z "$CAMERA_IDX" ]]; then
    CAMERA_IDX="$(find_physical_camera)"
    if [[ -z "$CAMERA_IDX" ]]; then
        notify_err "[run_meeting] No physical webcam capture device found."
        exit 1
    fi
    ARGS+=(--camera "$CAMERA_IDX")
fi

CAMERA_DEV="/dev/video$CAMERA_IDX"
if holders="$(fuser "$CAMERA_DEV" 2>/dev/null | xargs)" && [[ -n "$holders" ]]; then
    busy_procs="$(ps -o comm= -p "${holders// /,}" 2>/dev/null | paste -sd, - || true)"
    notify_err "$CAMERA_DEV is busy (${busy_procs:-another app}). Close the browser/app camera tab and retry."
    ps -o pid=,comm= -p "${holders// /,}" >&2 || true
    exit 1
fi

[[ " ${ARGS[*]} " == *" --mode "* ]] || ARGS+=(--mode naruto)
[[ " ${ARGS[*]} " == *" --bg-delay "* ]] || ARGS+=(--bg-delay 7)
[[ " ${ARGS[*]} " == *" --goku-delay "* ]] || ARGS+=(--goku-delay 0.30)
[[ " ${ARGS[*]} " == *" --async-gestures "* ]] || ARGS+=(--async-gestures)
[[ " ${ARGS[*]} " == *" --preview-hud "* ]] || ARGS+=(--preview-hud)

echo "[run_meeting] Physical camera: $CAMERA_DEV -> Virtual camera: $DEVICE (pick 'VanishCam' in your meeting app)"
# The pip OpenCV build only ships the Qt xcb plugin, so route this app through XWayland.
PYTHONUNBUFFERED=1 QT_QPA_PLATFORM=xcb exec "$PYTHON" "$REPO/vanish_cam.py" \
    --virtual-camera --virtual-backend v4l2loopback --virtual-device "$DEVICE" "${ARGS[@]}"
