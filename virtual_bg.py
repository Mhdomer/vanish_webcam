"""Virtual background presets, custom image loading (center-crop), and blur caching."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

BACKGROUNDS_DIR = Path(__file__).resolve().parent / "assets" / "backgrounds"
PRESET_IDS = ("studio-dark", "minimal-blue", "cyber-grid")


def list_presets() -> list[dict[str, str]]:
    """Return built-in presets and any user images placed under assets/backgrounds/."""
    items = [
        {"id": "studio-dark", "label": "Studio Dark"},
        {"id": "minimal-blue", "label": "Minimal Blue"},
        {"id": "cyber-grid", "label": "Cyber Grid"},
    ]
    seen = {p["id"] for p in items}
    if BACKGROUNDS_DIR.is_dir():
        for path in sorted(BACKGROUNDS_DIR.iterdir()):
            if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp") and path.stem not in seen:
                items.append({"id": str(path), "label": path.stem.replace("_", " ").replace("-", " ").title()})
    return items


def _generate_preset(name: str, width: int, height: int) -> np.ndarray | None:
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    cx, cy = (x - 0.5), (y - 0.44)
    radial = np.exp(-(cx * cx * 2.8 + cy * cy * 3.4))

    if name == "studio-dark":
        canvas = np.zeros((height, width, 3), dtype=np.float32)
        canvas[:, :, 0] = 26.0 + 30.0 * radial + 10.0 * (1.0 - y)
        canvas[:, :, 1] = 24.0 + 26.0 * radial + 8.0 * (1.0 - y)
        canvas[:, :, 2] = 28.0 + 24.0 * radial + 6.0 * y
        out = np.clip(canvas, 0, 255).astype(np.uint8)
        for bx, by, r, col in (
            (int(width * 0.16), int(height * 0.24), max(24, width // 16), (62, 54, 48)),
            (int(width * 0.84), int(height * 0.28), max(28, width // 14), (72, 58, 42)),
            (int(width * 0.76), int(height * 0.78), max(18, width // 22), (55, 65, 82)),
        ):
            cv2.circle(out, (bx, by), r, col, -1)
        return cv2.GaussianBlur(out, (0, 0), sigmaX=max(8.0, width / 60.0))

    if name == "minimal-blue":
        canvas = np.zeros((height, width, 3), dtype=np.float32)
        canvas[:, :, 0] = 74.0 + 52.0 * radial + 18.0 * (1.0 - x)
        canvas[:, :, 1] = 48.0 + 36.0 * radial + 12.0 * (1.0 - y)
        canvas[:, :, 2] = 26.0 + 22.0 * radial + 10.0 * y
        out = np.clip(canvas, 0, 255).astype(np.uint8)
        cv2.circle(out, (int(width * 0.2), int(height * 0.22)), max(30, width // 12), (128, 92, 54), -1)
        cv2.circle(out, (int(width * 0.82), int(height * 0.74)), max(36, width // 11), (112, 80, 44), -1)
        return cv2.GaussianBlur(out, (0, 0), sigmaX=max(10.0, width / 45.0))

    if name == "cyber-grid":
        canvas = np.zeros((height, width, 3), dtype=np.float32)
        canvas[:, :, 0] = 48.0 + 34.0 * radial + 20.0 * y
        canvas[:, :, 1] = 20.0 + 30.0 * radial + 12.0 * (1.0 - y)
        canvas[:, :, 2] = 32.0 + 18.0 * y
        out = np.clip(canvas, 0, 255).astype(np.uint8)
        horizon = int(height * 0.56)
        overlay = out.copy()
        step_y = max(14, height // 18)
        for gy in range(horizon, height, step_y):
            cv2.line(overlay, (0, gy), (width, gy), (165, 115, 25), 1, cv2.LINE_AA)
        cols = 14
        for i in range(-cols, cols + 1):
            bx = int(width * 0.5 + i * (width / 10.0))
            tx = int(width * 0.5 + i * (width / 42.0))
            cv2.line(overlay, (tx, horizon), (bx, height), (195, 135, 35), 1, cv2.LINE_AA)
        cv2.line(overlay, (0, horizon), (width, horizon), (225, 190, 60), 2, cv2.LINE_AA)
        return cv2.addWeighted(overlay, 0.35, out, 0.65, 0)

    return None


def _fit_cover(img: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize and center-crop an image to fill (width, height) without distortion."""
    ih, iw = img.shape[:2]
    if iw == width and ih == height:
        return img
    scale = max(width / float(max(1, iw)), height / float(max(1, ih)))
    new_w = max(width, int(round(iw * scale)))
    new_h = max(height, int(round(ih * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(img, (new_w, new_h), interpolation=interp)
    x1 = max(0, (new_w - width) // 2)
    y1 = max(0, (new_h - height) // 2)
    return np.ascontiguousarray(resized[y1:y1 + height, x1:x1 + width])


def load_virtual_background(spec: str, width: int, height: int) -> tuple[np.ndarray | None, str]:
    """Resolve a preset name or image path into a fitted BGR frame and clean display key."""
    cleaned = (spec or "").strip()
    if not cleaned or cleaned.lower() in ("off", "none"):
        return None, ""
    lower = cleaned.lower()
    if lower in PRESET_IDS:
        preset = _generate_preset(lower, width, height)
        if preset is not None:
            return preset, lower

    candidate = Path(cleaned).expanduser()
    if not candidate.is_file() and BACKGROUNDS_DIR.is_dir():
        in_dir = BACKGROUNDS_DIR / cleaned
        if in_dir.is_file():
            candidate = in_dir
    if candidate.is_file():
        loaded = cv2.imread(str(candidate))
        if loaded is not None:
            return _fit_cover(loaded, width, height), str(candidate)
    return None, ""


def make_blurred_background(background: np.ndarray | None) -> np.ndarray | None:
    """Create a blurred copy of an arbitrary background frame once for fast reuse."""
    if background is None:
        return None
    h, w = background.shape[:2]
    small = cv2.resize(background, (max(160, w // 4), max(90, h // 4)), interpolation=cv2.INTER_AREA)
    blurred_small = cv2.GaussianBlur(small, (0, 0), sigmaX=5.5, sigmaY=5.5)
    return cv2.resize(blurred_small, (w, h), interpolation=cv2.INTER_LINEAR)
