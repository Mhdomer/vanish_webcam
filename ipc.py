"""IPC state/command files and desktop notifications for headless operation."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

STATE_FILE = Path("/tmp/vanish_cam.state.json")
CMD_FILE = Path("/tmp/vanish_cam.cmd")


def notify_desktop(summary: str, body: str) -> None:
    """Send a non-blocking desktop notification on Linux when running headless."""
    notify_bin = shutil.which("notify-send")
    if not notify_bin:
        return
    try:
        subprocess.Popen(
            [notify_bin, "-a", "VanishCam", "-t", "2800", summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def write_ipc_state(
    running: bool,
    mode: str = "",
    state=None,
    snap_message: str = "",
    state_file: Path = STATE_FILE,
) -> None:
    """Write atomic live JSON state to /tmp/vanish_cam.state.json."""
    payload = {
        "running": running,
        "pid": os.getpid() if running else None,
        "mode": mode if running else "",
        "phase": state.phase if (running and state is not None) else "off",
        "gestures_paused": bool(state.gestures_paused) if (running and state is not None) else False,
        "preview_visible": bool(state.preview_visible) if (running and state is not None) else False,
        "ghost_echo": bool(state.ghost_echo) if (running and state is not None) else False,
        "blur_bg": bool(state.blur_bg) if (running and state is not None) else False,
        "virtual_bg": str(getattr(state, "virtual_bg", "") or "") if (running and state is not None) else "",
        "snap_message": snap_message if (running and mode == "snap") else "",
        "updated_at": round(time.time(), 2),
    }
    try:
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, state_file)
    except OSError:
        pass


def poll_ipc_commands(cmd_file: Path = CMD_FILE) -> list[str]:
    """Read and clear queued remote commands from /tmp/vanish_cam.cmd."""
    if not cmd_file.is_file():
        return []
    try:
        raw = cmd_file.read_text(encoding="utf-8")
        cmd_file.unlink(missing_ok=True)
        return [line.strip() for line in raw.splitlines() if line.strip()]
    except OSError:
        return []
