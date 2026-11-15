"""Preview-only HUD overlays, banners, and clickable control menu."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

MODES_META_PATH = Path(__file__).resolve().parent / "noctalia-plugin" / "modes.json"
_FALLBACK_MODES = (
    ("snap", "SNAP"),
    ("naruto", "NARU"),
    ("normal", "NORM"),
    ("particles", "PART"),
    ("itachi", "ITAC"),
    ("goku", "GOKU"),
)


def load_mode_buttons_meta(path: Path = MODES_META_PATH) -> tuple[tuple[str, str], ...]:
    """Return ordered (mode_id, short_label) pairs from shared modes.json or fallback."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        parsed = tuple((str(e["id"]), str(e.get("shortLabel") or e["id"][:4].upper())) for e in entries)
        if parsed:
            return parsed
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return _FALLBACK_MODES


def draw_preview_banner(
    frame: np.ndarray,
    headline: str,
    subtitle: str = "",
    accent: tuple[int, int, int] = (0, 200, 255),
) -> np.ndarray:
    """Draw a preview-only status banner without touching the virtual camera frame."""
    out = frame.copy()
    h, w = out.shape[:2]
    bar_h = 84 if subtitle else 54
    overlay = out[:bar_h].copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (20, 22, 26), -1)
    cv2.addWeighted(overlay, 0.72, out[:bar_h], 0.28, 0, out[:bar_h])
    cv2.rectangle(out, (0, bar_h - 3), (w, bar_h), accent, -1)
    cv2.putText(out, headline, (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.85, accent, 2, cv2.LINE_AA)
    if subtitle:
        cv2.putText(out, subtitle, (20, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (220, 230, 237), 1, cv2.LINE_AA)
    return out


def _hud_menu_buttons(w: int, h: int, mode: str, state) -> list[tuple[str, str, tuple[int, int, int, int]]]:
    is_away = state.phase in ("vanished", "frozen")
    action_label = "Reappear Now (R)" if is_away else "Vanish Now (V)"
    action_cmd = "reappear" if is_away else "vanish"
    freeze_label = "Unfreeze Camera (Z)" if state.phase == "frozen" else "Freeze Frame (Z)"
    pause_label = "Resume Gestures (G)" if state.gestures_paused else "Pause Gestures (G)"
    blur_label = f"Blur BG: {'ON' if state.blur_bg else 'OFF'} (W)"
    vbg = getattr(state, "virtual_bg", "") or ""
    vbg_short = Path(vbg).stem[:14] if ("/" in vbg or "\\" in vbg) else vbg
    vbg_label = f"Virtual BG: {vbg_short or 'OFF'}"
    mirror_label = f"Mirror Output: {'ON' if getattr(state, 'mirror', True) else 'OFF'} (M)"
    echo_label = f"Ghost Echo: {'ON' if state.ghost_echo else 'OFF'} (E)"
    items = [
        (action_cmd, action_label),
        ("freeze", freeze_label),
        ("blur", blur_label),
        ("bg-image:cycle", vbg_label),
        ("mirror", mirror_label),
        ("pause", pause_label),
        ("echo", echo_label),
        ("recapture", "Recapture Room (SPACE)"),
        ("load-bg", "Load Saved Room (B)"),
    ]
    if mode == "snap":
        items.append(("next-text", "Next Snap Excuse (T)"))
        edit_label = f"Type: {state.edit_buffer}_ [ENTER]" if state.editing_text else "Edit Custom Excuse (Click)"
        items.append(("edit-text", edit_label))
    items.append(("preview", "Hide Preview Window (P)"))
    items.append(("help", "Close Menu (H)"))

    box_w = min(w - 40, 360)
    row_h, gap = 29, 5
    mode_row_h = 28
    box_h = 82 + len(items) * (row_h + gap)
    bx1 = (w - box_w) // 2
    by1 = max(10, (h - box_h) // 2)
    buttons = []
    modes = load_mode_buttons_meta()
    n_modes = len(modes)
    inner_w = box_w - 32
    cell_w = (inner_w - max(0, n_modes - 1) * 4) // max(1, n_modes)
    my1 = by1 + 36
    for idx, (m_id, short_label) in enumerate(modes):
        mx1 = bx1 + 16 + idx * (cell_w + 4)
        mx2 = mx1 + cell_w if idx < n_modes - 1 else bx1 + box_w - 16
        buttons.append((f"mode:{m_id}", short_label, (mx1, my1, mx2, my1 + mode_row_h)))
    for idx, (cmd, label) in enumerate(items):
        y1 = my1 + mode_row_h + 8 + idx * (row_h + gap)
        buttons.append((cmd, label, (bx1 + 16, y1, bx1 + box_w - 16, y1 + row_h)))
    return buttons


def draw_preview_hud(
    frame: np.ndarray,
    mode: str,
    state,
    snap_message: str = "",
) -> np.ndarray:
    """Draw a subtle bottom status pill and clickable control menu on preview only."""
    out = frame.copy() if frame is not None else frame
    h, w = out.shape[:2]
    gesture_state = "PAUSED" if state.gestures_paused else "ON"
    mode_tag = f"SNAP: {snap_message}" if mode == "snap" and snap_message else mode.upper()
    if state.phase == "frozen":
        mode_tag = f"{mode_tag} [FROZEN]"
    elif getattr(state, "virtual_bg", ""):
        mode_tag = f"{mode_tag} [VBG+BLUR]" if state.blur_bg else f"{mode_tag} [VBG]"
    elif state.blur_bg and state.phase == "ready":
        mode_tag = f"{mode_tag} [BLUR]"
    elif state.ghost_echo:
        mode_tag = f"{mode_tag} [ECHO]"
    if not getattr(state, "mirror", True):
        mode_tag = f"{mode_tag} [RAW]"
    pill = f"{mode_tag}  |  GESTURES {gesture_state}  |  [H] MENU"
    (tw, th), _ = cv2.getTextSize(pill, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    pad_x, pad_y = 12, 8
    x1, y2 = 14, h - 14
    x2, y1 = min(w - 14, x1 + tw + pad_x * 2), max(14, y2 - th - pad_y * 2)
    roi = out[y1:y2, x1:x2]
    dark = np.full_like(roi, (20, 22, 26))
    cv2.addWeighted(dark, 0.72, roi, 0.28, 0, roi)
    cv2.putText(out, pill, (x1 + pad_x, y2 - pad_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (210, 222, 228), 1, cv2.LINE_AA)

    if state.show_help:
        buttons = _hud_menu_buttons(w, h, mode, state)
        bx1 = buttons[0][2][0] - 16
        by1 = buttons[0][2][1] - 36
        bx2 = buttons[-1][2][2] + 16
        by2 = min(h - 10, buttons[-1][2][3] + 12)
        panel = out[by1:by2, bx1:bx2]
        bg = np.full_like(panel, (20, 22, 26))
        cv2.addWeighted(bg, 0.86, panel, 0.14, 0, panel)
        cv2.rectangle(out, (bx1, by1), (bx2, by2), (111, 142, 153), 1)
        cv2.putText(out, "LOCAL CONTROL MENU (Preview Only)", (bx1 + 18, by1 + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 215, 255), 1, cv2.LINE_AA)
        for cmd, label, (rx1, ry1, rx2, ry2) in buttons:
            if cmd.startswith("mode:"):
                is_active = cmd.split(":", 1)[1] == mode
                fill = (0, 140, 180) if is_active else (36, 40, 46)
                cv2.rectangle(out, (rx1, ry1), (rx2, ry2), fill, -1)
                cv2.rectangle(out, (rx1, ry1), (rx2, ry2), (0, 215, 255) if is_active else (80, 95, 105), 1)
                cv2.putText(out, label, (rx1 + 6, ry1 + 19),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 255, 255) if is_active else (190, 200, 208), 1, cv2.LINE_AA)
            else:
                if cmd in ("vanish", "reappear"):
                    fill = (52, 92, 76)
                elif cmd == "edit-text" and state.editing_text:
                    fill = (95, 72, 30)
                else:
                    fill = (42, 47, 54)
                cv2.rectangle(out, (rx1, ry1), (rx2, ry2), fill, -1)
                border_col = (0, 215, 255) if (cmd == "edit-text" and state.editing_text) else (95, 122, 132)
                cv2.rectangle(out, (rx1, ry1), (rx2, ry2), border_col, 1)
                cv2.putText(out, label, (rx1 + 12, ry1 + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.43, (235, 240, 244), 1, cv2.LINE_AA)
    return out
