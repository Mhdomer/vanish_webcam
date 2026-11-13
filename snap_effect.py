"""Atomic Snap Void effect: snap fingers -> dissolve -> vortex -> excuse text -> crumble."""
from __future__ import annotations

import math
import random
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


class _Particle:
    __slots__ = ("x", "y", "vx", "vy", "color", "life", "size", "tx", "ty", "ease", "twinkle")

    def __init__(
        self,
        x: float,
        y: float,
        color: tuple[int, int, int],
        vx: float = 0.0,
        vy: float = 0.0,
        size: int = 3,
        target: tuple[float, float] | None = None,
        ease: float = 0.12,
        twinkle: float = 0.0,
    ) -> None:
        self.x = float(x)
        self.y = float(y)
        self.vx = vx
        self.vy = vy
        self.color = color
        self.life = 1.0
        self.size = size
        self.tx = None if target is None else float(target[0])
        self.ty = None if target is None else float(target[1])
        self.ease = ease
        self.twinkle = twinkle


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
    pts = np.column_stack((xs, ys)).astype(np.float64)
    if len(pts) > max_points:
        idx = np.random.choice(len(pts), max_points, replace=False)
        pts = pts[idx]
    else:
        need = min(max_points, len(pts) * 4)
        idx = np.random.choice(len(pts), need, replace=True)
        pts = pts[idx] + np.random.uniform(-2.5, 2.5, (need, 2))
    bbox = (int(org[0]), int(org[1] - th), int(org[0] + tw), int(org[1] + base))
    return pts, bbox


def _draw_glow_layer(out_frame: np.ndarray, spark_list: list[_Particle], layer: np.ndarray) -> np.ndarray:
    if not spark_list:
        return out_frame
    layer[:] = 0
    for s in spark_list:
        a = max(0.0, min(1.0, s.life))
        if a <= 0.0:
            continue
        color = (min(255, int(s.color[0] * a)), min(255, int(s.color[1] * a)), min(255, int(s.color[2] * a)))
        if s.size > 1:
            glow_color = (color[0] // 4, color[1] // 4, color[2] // 4)
            cv2.circle(layer, (int(s.x), int(s.y)), s.size * 3, glow_color, -1)
        cv2.circle(layer, (int(s.x), int(s.y)), s.size, color, -1)
    cv2.add(out_frame, layer, dst=out_frame)
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
        self.shockwave_radius = 5
        self.msg_assigned = False
        self.void_bbox: tuple[int, int, int, int] | None = None
        self.particles: list[_Particle] = []

        ys, xs = np.where(mask > 0.5)
        if len(xs) > 0:
            sample_count = min(2400, len(xs))
            indices = np.random.choice(len(xs), size=sample_count, replace=False)
            for idx in indices:
                px, py = int(xs[idx]), int(ys[idx])
                b, g, r = frame[py, px]
                if random.random() < 0.25:
                    color = random.choice(STONE_COLORS)
                else:
                    color = (
                        min(255, int(b * 0.4 + 20)),
                        min(255, int(g * 0.8 + 120)),
                        min(255, int(r * 1.2 + 180)),
                    )
                angle = math.atan2(py - snap_pos[1], px - snap_pos[0])
                speed = random.uniform(2.0, 7.0)
                vx = math.cos(angle) * speed + random.uniform(1.0, 5.0)
                vy = math.sin(angle) * speed - random.uniform(2.0, 6.0)
                self.particles.append(
                    _Particle(px, py, color, vx=vx, vy=vy, size=random.randint(2, 4), twinkle=random.uniform(0, math.tau))
                )

    def _assign_message_targets(self) -> None:
        self.msg_assigned = True
        if self.on_assemble is not None:
            self.on_assemble()
        if not self.particles:
            return
        pts, self.void_bbox = _sample_text_targets(self.message, self.w, self.h, len(self.particles))
        if pts is None:
            return
        order = np.random.permutation(len(self.particles))
        for i, p_idx in enumerate(order):
            if i >= len(pts):
                break
            p = self.particles[p_idx]
            p.tx, p.ty = float(pts[i][0]), float(pts[i][1])
            p.ease = random.uniform(0.07, 0.15)

    def render(self, background: np.ndarray, age: float) -> np.ndarray:
        out_frame = background.copy()
        if age < P1_DISSOLVE_END:
            progress = age / P1_DISSOLVE_END
            body_alpha = float(np.clip((1.0 - progress) * 1.5, 0.0, 1.0))
            dissolve_threshold = 0.5 + progress * 0.5
            mask_3d = (self.mask > dissolve_threshold)[:, :, np.newaxis]
            faded_body = cv2.addWeighted(self.frame, body_alpha, background, 1.0 - body_alpha, 0)
            out_frame = np.where(mask_3d, faded_body, background)

            self.shockwave_radius += int(25 * (1.0 - progress * 0.5))
            if self.shockwave_radius < max(self.w, self.h):
                cv2.circle(out_frame, self.snap_pos, self.shockwave_radius, (255, 220, 100), max(1, int(6 * (1.0 - progress))))
                cv2.circle(out_frame, self.snap_pos, max(1, self.shockwave_radius - 12), (0, 180, 255), 2)

            for p in self.particles:
                p.x += p.vx
                p.y += p.vy
                p.vx *= 0.985
                p.vy *= 0.985
                p.life = 1.0
            return _draw_glow_layer(out_frame, self.particles, self._layer)

        if age < P2_VORTEX_END:
            cx, cy = self.snap_pos
            for p in self.particles:
                dx, dy = cx - p.x, cy - p.y
                d = max(1.0, math.hypot(dx, dy))
                ux, uy = dx / d, dy / d
                p.vx = p.vx * 0.82 + ux * 4.2 - uy * 4.6
                p.vy = p.vy * 0.82 + uy * 4.2 + ux * 4.6
                p.x += p.vx
                p.y += p.vy
                p.life = 1.0
            _draw_glow_layer(out_frame, self.particles, self._layer)
            core_r = 14 + int(4 * math.sin(age * 18))
            cv2.circle(out_frame, self.snap_pos, core_r + 8, (0, 60, 120), -1)
            cv2.circle(out_frame, self.snap_pos, core_r, (0, 0, 0), -1)
            cv2.circle(out_frame, self.snap_pos, core_r + 2, (0, 160, 255), 1)
            return out_frame

        if age < P3_ASSEMBLE_END:
            if not self.msg_assigned:
                self._assign_message_targets()
            for p in self.particles:
                if p.tx is not None:
                    p.x += (p.tx - p.x) * p.ease
                    p.y += (p.ty - p.y) * p.ease
                    p.life = 1.0
                else:
                    p.x += p.vx * 0.4
                    p.y += p.vy * 0.4 - 0.3
                    p.life = max(0.0, p.life - 0.012)
            return _draw_glow_layer(out_frame, self.particles, self._layer)

        now = time.perf_counter()
        if age < P4_HOLD_END:
            for p in self.particles:
                if p.tx is not None:
                    p.x = p.tx + math.sin(now * 2.0 + p.twinkle) * 1.2
                    p.y = p.ty + math.cos(now * 1.6 + p.twinkle) * 1.2
                    p.life = 0.72 + 0.28 * math.sin(now * 6.0 + p.twinkle)
                else:
                    p.x += p.vx * 0.2
                    p.y += p.vy * 0.2 - 0.2
                    p.life = max(0.0, p.life - 0.010)
            return _draw_glow_layer(out_frame, self.particles, self._layer)

        if age < SNAP_SECONDS:
            if self.void_bbox is not None:
                _, y0, _, y1 = self.void_bbox
                crumble_progress = (age - P4_HOLD_END) / (SNAP_SECONDS - P4_HOLD_END)
                line_y = y0 - 30 + (y1 - y0 + 60) * crumble_progress
            else:
                line_y = 0.0
            for p in self.particles:
                if p.tx is not None and p.ty <= line_y:
                    p.tx = p.ty = None
                    p.vx = random.uniform(-1.0, 1.0)
                    p.vy = random.uniform(-1.5, 0.0)
                if p.tx is None:
                    p.vy += 0.35
                    p.x += p.vx
                    p.y += p.vy
                    p.life = max(0.0, p.life - 0.016)
                else:
                    p.x = p.tx + math.sin(now * 2.0 + p.twinkle) * 1.2
                    p.y = p.ty + math.cos(now * 1.6 + p.twinkle) * 1.2
                    p.life = 0.72 + 0.28 * math.sin(now * 6.0 + p.twinkle)
            return _draw_glow_layer(out_frame, self.particles, self._layer)

        return out_frame


class SnapRebuildEffect:
    """Sparks converge from screen edges back into the person's silhouette."""

    def __init__(self, mask: np.ndarray, width: int, height: int) -> None:
        self._layer = np.zeros((height, width, 3), np.uint8)
        self.particles: list[_Particle] = []
        ys, xs = np.where(mask > 0.5)
        if len(xs) > 0:
            sample_count = min(800, len(xs))
            indices = np.random.choice(len(xs), size=sample_count, replace=False)
            for idx in indices:
                tx, ty = float(xs[idx]), float(ys[idx])
                side = random.random()
                if side < 0.25:
                    sx, sy = random.uniform(-80, width + 80), -80.0
                elif side < 0.5:
                    sx, sy = random.uniform(-80, width + 80), height + 80.0
                elif side < 0.75:
                    sx, sy = -80.0, random.uniform(-80, height + 80)
                else:
                    sx, sy = width + 80.0, random.uniform(-80, height + 80)
                color = random.choice(STONE_COLORS + (GOLD,))
                self.particles.append(_Particle(sx, sy, color, size=2, target=(tx, ty)))

    def render(self, frame: np.ndarray, background: np.ndarray, mask: np.ndarray, age: float) -> np.ndarray:
        progress = min(1.0, age / REBUILD_SECONDS)
        ease = 1.0 - (1.0 - progress) ** 3
        mask_3d = (mask > 0.5)[:, :, np.newaxis]
        body = cv2.addWeighted(frame, ease, background, 1.0 - ease, 0)
        out_frame = np.where(mask_3d, body, background)

        follow = min(1.0, ease + 0.15)
        for sp in self.particles:
            sp.x += (sp.tx - sp.x) * follow
            sp.y += (sp.ty - sp.y) * follow
            sp.life = 1.0 - progress * 0.6
        return _draw_glow_layer(out_frame, self.particles, self._layer)
