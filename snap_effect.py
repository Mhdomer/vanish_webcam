"""Atomic Snap Void effect: snap fingers -> dissolve -> vortex -> excuse text -> crumble."""
from __future__ import annotations

import math
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
SNAP_SOUND_PATH = ASSETS_DIR / "snap.wav"
CHIME_SOUND_PATH = ASSETS_DIR / "chime.wav"

P1_DISSOLVE_END = 1.3
P2_VORTEX_END = 2.4
P3_ASSEMBLE_END = 3.8
P4_HOLD_END = 8.6
SNAP_SECONDS = 10.4
REBUILD_SECONDS = 1.1

VOID_MESSAGES = ("BRB...", "GONE", "AFK", "MY INTERNET DIED", "IN A MEETING")

STONE_COLORS = (
    (255, 120, 0),
    (0, 230, 255),
    (60, 60, 255),
    (200, 40, 160),
    (80, 220, 0),
    (30, 130, 255),
)
GOLD = (0, 215, 255)
_SPARK_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
_SMALL_SPARK_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))


class _ParticleSystem:
    """Contiguous NumPy arrays backing Snap void and rebuild particles."""

    __slots__ = (
        "x", "y", "vx", "vy", "tx", "ty", "has_target",
        "color", "life", "ease", "twinkle", "count",
    )

    def __init__(self, count: int) -> None:
        self.count = count
        self.x = np.zeros(count, dtype=np.float32)
        self.y = np.zeros(count, dtype=np.float32)
        self.vx = np.zeros(count, dtype=np.float32)
        self.vy = np.zeros(count, dtype=np.float32)
        self.tx = np.zeros(count, dtype=np.float32)
        self.ty = np.zeros(count, dtype=np.float32)
        self.has_target = np.zeros(count, dtype=bool)
        self.color = np.zeros((count, 3), dtype=np.uint8)
        self.life = np.ones(count, dtype=np.float32)
        self.ease = np.full(count, 0.12, dtype=np.float32)
        self.twinkle = np.zeros(count, dtype=np.float32)


class SnapPoseRecognizer:
    """Detect finger-snap (pinch thumb+middle then release) and peace sign to rebuild."""

    def __init__(self, hand_landmarker) -> None:
        self.detector = hand_landmarker
        self.last_hand_count = 0
        self.snap_primed = False
        self.prime_time = 0.0
        self.last_snap_pos: tuple[int, int] = (0, 0)

    def reset(self) -> None:
        self.snap_primed = False
        self.prime_time = 0.0

    def detect_snap(
        self, image: mp.Image, timestamp_ms: int, width: int, height: int
    ) -> tuple[bool, bool, tuple[int, int]]:
        result = self.detector.detect_for_video(image, timestamp_ms)
        self.last_hand_count = len(result.hand_landmarks)
        now = time.perf_counter()

        for landmarks in result.hand_landmarks:
            thumb = landmarks[4]
            middle = landmarks[12]
            dist = math.hypot(thumb.x - middle.x, thumb.y - middle.y)
            pos = (int(thumb.x * width), int(thumb.y * height))
            if dist < 0.045:
                self.snap_primed = True
                self.prime_time = now
                self.last_snap_pos = pos
                return False, True, pos
            if self.snap_primed and (now - self.prime_time < 0.35) and dist > 0.085:
                self.snap_primed = False
                return True, False, self.last_snap_pos

        if self.snap_primed and (now - self.prime_time > 0.4):
            self.snap_primed = False
        return False, self.snap_primed, self.last_snap_pos

    def detect_peace_sign(self, image: mp.Image, timestamp_ms: int) -> bool:
        result = self.detector.detect_for_video(image, timestamp_ms)
        self.last_hand_count = len(result.hand_landmarks)
        for lm in result.hand_landmarks:
            if lm[8].y < lm[6].y and lm[12].y < lm[10].y and lm[16].y > lm[14].y and lm[20].y > lm[18].y:
                return True
        return False

    def close(self) -> None:
        self.detector.close()


def _sample_text_targets(message: str, w: int, h: int, max_points: int):
    canvas = np.zeros((h, w), np.uint8)
    scale = 1.0
    while scale < 8.0:
        trial = scale + 0.25
        (tw, th), _ = cv2.getTextSize(message, cv2.FONT_HERSHEY_DUPLEX, trial, max(2, int(trial * 14)))
        if tw > w * 0.85 or th > h * 0.35:
            break
        scale = trial
    thickness = max(2, int(scale * 14))
    (tw, th), base = cv2.getTextSize(message, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
    org = ((w - tw) // 2, (h + th) // 2)
    cv2.putText(canvas, message, org, cv2.FONT_HERSHEY_DUPLEX, scale, 255, thickness, cv2.LINE_AA)

    ys, xs = np.where(canvas > 100)
    if len(xs) == 0:
        return None, None
    pts = np.column_stack((xs, ys)).astype(np.float32)
    if len(pts) > max_points:
        idx = np.random.choice(len(pts), max_points, replace=False)
        pts = pts[idx]
    else:
        need = min(max_points, len(pts) * 4)
        idx = np.random.choice(len(pts), need, replace=True)
        pts = pts[idx] + np.random.uniform(-2.5, 2.5, (need, 2)).astype(np.float32)
    bbox = (int(org[0]), int(org[1] - th), int(org[0] + tw), int(org[1] + base))
    return pts, bbox


def _draw_glow_layer(
    out_frame: np.ndarray,
    system: _ParticleSystem,
    layer: np.ndarray,
    kernel: np.ndarray = _SPARK_KERNEL,
) -> np.ndarray:
    if system.count == 0:
        return out_frame
    h, w = layer.shape[:2]
    ix = np.rint(system.x).astype(np.int32)
    iy = np.rint(system.y).astype(np.int32)
    alive = (system.life > 0.02) & (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    if not np.any(alive):
        return out_frame

    layer[:] = 0
    alpha = np.clip(system.life[alive], 0.0, 1.0)[:, None]
    cols = np.clip(system.color[alive].astype(np.float32) * alpha, 0, 255).astype(np.uint8)
    layer[iy[alive], ix[alive]] = cols

    core = cv2.dilate(layer, kernel)
    small_w, small_h = max(80, w // 4), max(45, h // 4)
    glow = cv2.resize(core, (small_w, small_h), interpolation=cv2.INTER_AREA)
    glow = cv2.GaussianBlur(glow, (0, 0), sigmaX=2.4, sigmaY=2.4)
    glow_up = cv2.resize(glow, (w, h), interpolation=cv2.INTER_LINEAR)
    cv2.add(out_frame, core, dst=out_frame)
    cv2.addWeighted(out_frame, 1.0, glow_up, 0.65, 0, dst=out_frame)
    return out_frame


class SnapVoidEffect:
    """Void sequence: dissolve -> blackhole vortex -> excuse text -> crumble."""

    def __init__(
        self,
        frame: np.ndarray,
        mask: np.ndarray,
        snap_pos: tuple[int, int],
        message: str = "BRB...",
        on_assemble=None,
    ) -> None:
        self.frame = frame.copy()
        self.mask = mask.copy()
        self.snap_pos = snap_pos
        self.message = message
        self.on_assemble = on_assemble
        self.h, self.w = frame.shape[:2]
        self._layer = np.zeros((self.h, self.w, 3), np.uint8)
        self._rng = np.random.default_rng()
        self.shockwave_radius = 5
        self.msg_assigned = False
        self.void_bbox: tuple[int, int, int, int] | None = None

        ys, xs = np.where(mask > 0.5)
        if len(xs) == 0:
            self.particles = _ParticleSystem(0)
            return

        sample_count = min(2400, len(xs))
        indices = self._rng.choice(len(xs), size=sample_count, replace=False)
        px = xs[indices].astype(np.float32)
        py = ys[indices].astype(np.float32)

        ps = _ParticleSystem(sample_count)
        ps.x = px
        ps.y = py

        sampled_bgr = frame[ys[indices], xs[indices]].astype(np.float32)
        base_colors = np.empty((sample_count, 3), dtype=np.uint8)
        base_colors[:, 0] = np.clip(sampled_bgr[:, 0] * 0.4 + 20, 0, 255)
        base_colors[:, 1] = np.clip(sampled_bgr[:, 1] * 0.8 + 120, 0, 255)
        base_colors[:, 2] = np.clip(sampled_bgr[:, 2] * 1.2 + 180, 0, 255)

        stone_mask = self._rng.random(sample_count) < 0.25
        stone_count = int(np.sum(stone_mask))
        if stone_count:
            palette = np.asarray(STONE_COLORS, dtype=np.uint8)
            base_colors[stone_mask] = palette[self._rng.integers(0, len(STONE_COLORS), size=stone_count)]
        ps.color = base_colors

        angles = np.arctan2(py - float(snap_pos[1]), px - float(snap_pos[0]))
        speeds = self._rng.uniform(2.0, 7.0, size=sample_count).astype(np.float32)
        ps.vx = (np.cos(angles) * speeds + self._rng.uniform(1.0, 5.0, size=sample_count)).astype(np.float32)
        ps.vy = (np.sin(angles) * speeds - self._rng.uniform(2.0, 6.0, size=sample_count)).astype(np.float32)
        ps.twinkle = self._rng.uniform(0.0, math.tau, size=sample_count).astype(np.float32)
        self.particles = ps

    def _assign_message_targets(self) -> None:
        self.msg_assigned = True
        if self.on_assemble is not None:
            self.on_assemble()
        if self.particles.count == 0:
            return
        pts, self.void_bbox = _sample_text_targets(self.message, self.w, self.h, self.particles.count)
        if pts is None:
            return
        assign_n = min(self.particles.count, len(pts))
        order = self._rng.permutation(self.particles.count)[:assign_n]
        self.particles.tx[order] = pts[:assign_n, 0]
        self.particles.ty[order] = pts[:assign_n, 1]
        self.particles.has_target[order] = True
        self.particles.ease[order] = self._rng.uniform(0.07, 0.15, size=assign_n).astype(np.float32)

    def render(self, background: np.ndarray, age: float) -> np.ndarray:
        out_frame = background.copy()
        ps = self.particles
        if age < P1_DISSOLVE_END:
            progress = age / P1_DISSOLVE_END
            body_alpha = float(np.clip((1.0 - progress) * 1.5, 0.0, 1.0))
            active_u8 = (self.mask > (0.5 + progress * 0.5)).view(np.uint8)
            faded_body = cv2.addWeighted(self.frame, body_alpha, background, 1.0 - body_alpha, 0)
            cv2.copyTo(faded_body, active_u8, out_frame)

            self.shockwave_radius += int(25 * (1.0 - progress * 0.5))
            if self.shockwave_radius < max(self.w, self.h):
                cv2.circle(out_frame, self.snap_pos, self.shockwave_radius, (255, 220, 100), max(1, int(6 * (1.0 - progress))))
                cv2.circle(out_frame, self.snap_pos, max(1, self.shockwave_radius - 12), (0, 180, 255), 2)

            if ps.count:
                ps.x += ps.vx
                ps.y += ps.vy
                ps.vx *= 0.985
                ps.vy *= 0.985
                ps.life.fill(1.0)
            return _draw_glow_layer(out_frame, ps, self._layer)

        if age < P2_VORTEX_END:
            if ps.count:
                cx, cy = float(self.snap_pos[0]), float(self.snap_pos[1])
                dx = cx - ps.x
                dy = cy - ps.y
                d = np.maximum(1.0, np.hypot(dx, dy))
                ux = dx / d
                uy = dy / d
                ps.vx = ps.vx * 0.82 + ux * 4.2 - uy * 4.6
                ps.vy = ps.vy * 0.82 + uy * 4.2 + ux * 4.6
                ps.x += ps.vx
                ps.y += ps.vy
                ps.life.fill(1.0)
            _draw_glow_layer(out_frame, ps, self._layer)
            core_r = 14 + int(4 * math.sin(age * 18))
            cv2.circle(out_frame, self.snap_pos, core_r + 8, (0, 60, 120), -1)
            cv2.circle(out_frame, self.snap_pos, core_r, (0, 0, 0), -1)
            cv2.circle(out_frame, self.snap_pos, core_r + 2, (0, 160, 255), 1)
            return out_frame

        if age < P3_ASSEMBLE_END:
            if not self.msg_assigned:
                self._assign_message_targets()
            if ps.count:
                tgt = ps.has_target
                free = ~tgt
                if np.any(tgt):
                    ps.x[tgt] += (ps.tx[tgt] - ps.x[tgt]) * ps.ease[tgt]
                    ps.y[tgt] += (ps.ty[tgt] - ps.y[tgt]) * ps.ease[tgt]
                    ps.life[tgt] = 1.0
                if np.any(free):
                    ps.x[free] += ps.vx[free] * 0.4
                    ps.y[free] += ps.vy[free] * 0.4 - 0.3
                    ps.life[free] = np.maximum(0.0, ps.life[free] - 0.012)
            return _draw_glow_layer(out_frame, ps, self._layer)

        now = time.perf_counter()
        if age < P4_HOLD_END:
            if ps.count:
                tgt = ps.has_target
                free = ~tgt
                if np.any(tgt):
                    phase_x = now * 2.0 + ps.twinkle[tgt]
                    phase_y = now * 1.6 + ps.twinkle[tgt]
                    ps.x[tgt] = ps.tx[tgt] + np.sin(phase_x) * 1.2
                    ps.y[tgt] = ps.ty[tgt] + np.cos(phase_y) * 1.2
                    ps.life[tgt] = 0.72 + 0.28 * np.sin(now * 6.0 + ps.twinkle[tgt])
                if np.any(free):
                    ps.x[free] += ps.vx[free] * 0.2
                    ps.y[free] += ps.vy[free] * 0.2 - 0.2
                    ps.life[free] = np.maximum(0.0, ps.life[free] - 0.010)
            return _draw_glow_layer(out_frame, ps, self._layer)

        if age < SNAP_SECONDS:
            if self.void_bbox is not None:
                _, y0, _, y1 = self.void_bbox
                crumble_progress = (age - P4_HOLD_END) / (SNAP_SECONDS - P4_HOLD_END)
                line_y = y0 - 30 + (y1 - y0 + 60) * crumble_progress
            else:
                line_y = 0.0
            if ps.count:
                release = ps.has_target & (ps.ty <= line_y)
                n_rel = int(np.sum(release))
                if n_rel:
                    ps.has_target[release] = False
                    ps.vx[release] = self._rng.uniform(-1.0, 1.0, size=n_rel).astype(np.float32)
                    ps.vy[release] = self._rng.uniform(-1.5, 0.0, size=n_rel).astype(np.float32)
                tgt = ps.has_target
                free = ~tgt
                if np.any(free):
                    ps.vy[free] += 0.35
                    ps.x[free] += ps.vx[free]
                    ps.y[free] += ps.vy[free]
                    ps.life[free] = np.maximum(0.0, ps.life[free] - 0.016)
                if np.any(tgt):
                    ps.x[tgt] = ps.tx[tgt] + np.sin(now * 2.0 + ps.twinkle[tgt]) * 1.2
                    ps.y[tgt] = ps.ty[tgt] + np.cos(now * 1.6 + ps.twinkle[tgt]) * 1.2
                    ps.life[tgt] = 0.72 + 0.28 * np.sin(now * 6.0 + ps.twinkle[tgt])
            return _draw_glow_layer(out_frame, ps, self._layer)

        return out_frame


class SnapRebuildEffect:
    """Sparks converge from screen edges back into the person's silhouette."""

    def __init__(self, mask: np.ndarray, width: int, height: int) -> None:
        self._layer = np.zeros((height, width, 3), np.uint8)
        rng = np.random.default_rng()
        ys, xs = np.where(mask > 0.5)
        if len(xs) == 0:
            self.particles = _ParticleSystem(0)
            return

        sample_count = min(800, len(xs))
        indices = rng.choice(len(xs), size=sample_count, replace=False)
        ps = _ParticleSystem(sample_count)
        ps.tx = xs[indices].astype(np.float32)
        ps.ty = ys[indices].astype(np.float32)
        ps.has_target.fill(True)

        sides = rng.integers(0, 4, size=sample_count)
        sx = np.empty(sample_count, dtype=np.float32)
        sy = np.empty(sample_count, dtype=np.float32)
        m0 = sides == 0
        m1 = sides == 1
        m2 = sides == 2
        m3 = sides == 3
        sx[m0] = rng.uniform(-80, width + 80, size=int(np.sum(m0)))
        sy[m0] = -80.0
        sx[m1] = rng.uniform(-80, width + 80, size=int(np.sum(m1)))
        sy[m1] = float(height + 80)
        sx[m2] = -80.0
        sy[m2] = rng.uniform(-80, height + 80, size=int(np.sum(m2)))
        sx[m3] = float(width + 80)
        sy[m3] = rng.uniform(-80, height + 80, size=int(np.sum(m3)))
        ps.x = sx
        ps.y = sy

        palette = np.asarray(STONE_COLORS + (GOLD,), dtype=np.uint8)
        ps.color = palette[rng.integers(0, len(palette), size=sample_count)]
        self.particles = ps

    def render(self, frame: np.ndarray, background: np.ndarray, mask: np.ndarray, age: float) -> np.ndarray:
        progress = min(1.0, age / REBUILD_SECONDS)
        ease = 1.0 - (1.0 - progress) ** 3
        active_u8 = (mask > 0.5).view(np.uint8)
        body = cv2.addWeighted(frame, ease, background, 1.0 - ease, 0)
        out_frame = background.copy()
        cv2.copyTo(body, active_u8, out_frame)

        ps = self.particles
        if ps.count:
            follow = min(1.0, ease + 0.15)
            ps.x += (ps.tx - ps.x) * follow
            ps.y += (ps.ty - ps.y) * follow
            ps.life.fill(max(0.0, 1.0 - progress * 0.6))
        return _draw_glow_layer(out_frame, ps, self._layer, kernel=_SMALL_SPARK_KERNEL)
