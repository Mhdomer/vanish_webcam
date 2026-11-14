"""Webcam locale: dissolvenza avviata dal gesto con indice e medio a V."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

if __name__ == "__main__" and not getattr(sys, "frozen", False):
    from mediapipe_log_filter import needs_filter, run_local_filtered
    if needs_filter(sys.argv[1:]):
        raise SystemExit(run_local_filtered(Path(__file__).resolve(), sys.argv[1:]))

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

try:
    from .goku_settings import choose_goku_delay
    from .itachi_effect import CROW_SHEET_PATH, SHARINGAN_PATH, EFFECT_SECONDS as ITACHI_SECONDS, ItachiCrowEffect, ItachiGestureGate, ItachiPoseRecognizer, load_crow_sprites, load_sharingan_art
    from .license_client import LicenseError, activate_license, load_config, show_license_error
    from .goku_effect import (
        GokuGestureGate, GokuPoseRecognizer, GokuTeleport, HOLD_SECONDS,
        TELEPORT_SECONDS,
    )
    from .particles_effect import PARTICLE_SECONDS, ParticleEffect
    from .snap_effect import (
        CHIME_SOUND_PATH, REBUILD_SECONDS, SNAP_SECONDS, SNAP_SOUND_PATH,
        VOID_MESSAGES, SnapPoseRecognizer, SnapRebuildEffect, SnapVoidEffect,
    )
    from .naruto_effect import (
        EFFECT_SECONDS, LOG_PATH, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_substitution, substitution_anchor,
    )
    from .vanish_sound import SOUND_PATH, TELEPORT_SOUND_PATH, VanishSound
except ImportError:
    from goku_settings import choose_goku_delay
    from itachi_effect import CROW_SHEET_PATH, SHARINGAN_PATH, EFFECT_SECONDS as ITACHI_SECONDS, ItachiCrowEffect, ItachiGestureGate, ItachiPoseRecognizer, load_crow_sprites, load_sharingan_art
    from license_client import LicenseError, activate_license, load_config, show_license_error
    from goku_effect import (
        GokuGestureGate, GokuPoseRecognizer, GokuTeleport, HOLD_SECONDS,
        TELEPORT_SECONDS,
    )
    from particles_effect import PARTICLE_SECONDS, ParticleEffect
    from snap_effect import (
        CHIME_SOUND_PATH, REBUILD_SECONDS, SNAP_SECONDS, SNAP_SOUND_PATH,
        VOID_MESSAGES, SnapPoseRecognizer, SnapRebuildEffect, SnapVoidEffect,
    )
    from naruto_effect import (
        EFFECT_SECONDS, LOG_PATH, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_substitution, substitution_anchor,
    )
    from vanish_sound import SOUND_PATH, TELEPORT_SOUND_PATH, VanishSound


APP_DIR = Path(__file__).resolve().parent
MODEL_DIR = APP_DIR / "models"
SAVED_BG_PATH = APP_DIR / "assets" / "last_bg.png"
STATE_FILE = Path("/tmp/vanish_cam.state.json")
CMD_FILE = Path("/tmp/vanish_cam.cmd")
REAPPEAR_SECONDS = 0.85
WINDOW_NAME = "Webcam - Preview"

SEGMENTER_MODEL = MODEL_DIR / "selfie_segmenter_landscape.tflite"
GESTURE_MODEL = MODEL_DIR / "gesture_recognizer.task"
HAND_MODEL = APP_DIR / "hand_landmarker.task"
FACE_MODEL = MODEL_DIR / "blaze_face_short_range.tflite"
ALL_MODES = ("normal", "naruto", "particles", "goku", "itachi", "snap")
# Firestore licenses the app/device, not individual effects. Report a known
# value until the server rules are updated for newly added local modes.
LICENSE_REPORTED_MODES = frozenset(("normal", "naruto", "particles", "goku"))
EDITION_MODES = {
    "full": ALL_MODES,
    "naruto": ("naruto",),
    "goku": ("goku",),
    "normal_particles": ("normal", "particles"),
}


def edition_modes(edition_file: Path | None = None) -> tuple[str, ...]:
    """Limit a packaged EXE to the modes listed in its bundled edition file."""
    edition_file = edition_file or APP_DIR / "edition.txt"
    if not edition_file.is_file():
        if getattr(sys, "frozen", False):
            raise RuntimeError("Configurazione dell'edizione non trovata nell'EXE.")
        return ALL_MODES
    edition = edition_file.read_text(encoding="utf-8").strip()
    if edition not in EDITION_MODES:
        raise RuntimeError(f"Edizione non riconosciuta: {edition}")
    return EDITION_MODES[edition]

MODEL_URLS = {
    SEGMENTER_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_segmenter_landscape/float16/latest/"
        "selfie_segmenter_landscape.tflite"
    ),
    GESTURE_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
        "gesture_recognizer/float16/1/gesture_recognizer.task"
    ),
    FACE_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/face_detector/"
        "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
    ),
}

CALIBRATION_SECONDS = 4.0
BACKGROUND_SAMPLE_SECONDS = 0.55
VANISH_SECONDS = 3.6
GESTURE_INTERVAL_SECONDS = 0.14


@dataclass
class AppState:
    phase: str = "calibrating"
    calibration_started: float = 0.0
    vanish_started: float | None = None
    last_gesture_check: float = 0.0
    fullscreen: bool = False
    gestures_paused: bool = False
    show_help: bool = False
    preview_visible: bool = True
    ghost_echo: bool = False
    editing_text: bool = False
    edit_buffer: str = ""


def positive_fps(value: str) -> float:
    fps = float(value)
    if not np.isfinite(fps) or not 1 <= fps <= 120:
        raise argparse.ArgumentTypeError("Gli FPS devono essere compresi tra 1 e 120.")
    return fps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Choose a disappearance effect for your webcam."
    )
    parser.add_argument(
        "--camera", type=int, default=None,
        help="Webcam index; if omitted, choose the webcam in the startup menu",
    )
    parser.add_argument("--width", type=int, default=960, help="Video width")
    parser.add_argument("--height", type=int, default=540, help="Video height")
    parser.add_argument(
        "--fullscreen", action="store_true", help="Start in fullscreen"
    )
    parser.add_argument(
        "--no-mirror", action="store_true", help="Do not mirror the webcam"
    )
    parser.add_argument("--fps", type=positive_fps, default=30.0, help="Max virtual output FPS (default: 30)")
    parser.add_argument(
        "--virtual-camera", action=argparse.BooleanOptionalAction, default=None,
        help="Require virtual camera; enabled by default if available. --no-virtual-camera disables it",
    )
    parser.add_argument(
        "--virtual-backend", choices=("obs", "unitycapture", "v4l2loopback"),
        help="Virtual camera driver to use",
    )
    parser.add_argument("--virtual-device", help="Virtual device name or path to use")
    parser.add_argument(
        "--mode", choices=edition_modes(),
        help="Skip the startup menu and launch the selected mode directly",
    )
    parser.add_argument(
        "--gesture-debug", action="store_true",
        help="Print gesture recognition status in the terminal (no video overlay)",
    )
    parser.add_argument(
        "--bg-delay", type=float, default=CALIBRATION_SECONDS,
        help=f"Seconds to step out of frame for background capture (default: {CALIBRATION_SECONDS:g})",
    )
    parser.add_argument(
        "--async-gestures", action="store_true",
        help="Run gesture recognition on a background thread so video stays at 30 FPS",
    )
    parser.add_argument(
        "--reuse-bg", action="store_true",
        help="Reuse the last saved empty-room background on startup (0s calibration)",
    )
    parser.add_argument(
        "--snap-text", type=str, default=None,
        help="Custom excuse text for Snap mode (e.g. 'COFFEE BREAK')",
    )
    parser.add_argument(
        "--preview-hud", action="store_true",
        help="Show preview-only countdown banner, status pill, and clickable H menu",
    )
    parser.add_argument(
        "--no-preview", action="store_true",
        help="Start without opening the local preview window (toggle anytime with 'vanish-cam preview')",
    )
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def choose_mode(available: tuple[str, ...] | None = None, check_license=None) -> str | None:
    """Simple keyboard/mouse menu shown before the clean camera feed."""
    available = available or edition_modes()
    display_modes = available
    title = "Choose Effect"
    selected = [None]
    compact = len(display_modes) > 6
    row_step = 94 if len(display_modes) > 5 else 115
    card_height = 80 if compact else row_step - 16 if len(display_modes) > 5 else 94
    rows = (len(display_modes) + 1) // 2 if compact else len(display_modes)
    window = np.zeros((120 + rows * row_step + 25, 700, 3), dtype=np.uint8)
    window[:] = (26, 29, 34)
    cv2.putText(window, "CHOOSE YOUR VANISH", (68, 88),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (236, 239, 242), 2, cv2.LINE_AA)
    labels = {
        "normal": ("NORMAL VANISH", "V sign  /  dissolve"),
        "naruto": ("NARUTO VANISH", "Palms together  /  log & smoke"),
        "particles": ("PARTICLES", "V sign  /  wind particles"),
        "goku": ("GOKU", "Two fingers to forehead  /  custom hold time"),
        "itachi": ("ITACHI UCHIHA DISAPPEAR", "Hands on chest  /  flock of crows"),
        "snap": ("SNAP VOID", "Snap fingers  /  vortex & BRB text"),
    }
    buttons = tuple(
        (mode, f"{index}  {labels[mode][0]}", labels[mode][1],
         (65 + ((index - 1) % 2) * 294 if compact else 65),
         120 + ((index - 1) // 2 if compact else index - 1) * row_step)
        for index, mode in enumerate(display_modes, 1)
    )
    for mode, heading, detail, left, top in buttons:
        disabled = mode not in available
        if disabled:
            heading = labels[mode][0]
            detail = "Coming soon"
        right = left + (277 if compact else 570)
        cv2.rectangle(window, (left, top), (right, top + card_height),
                      (35, 38, 43) if disabled else (48, 54, 62), -1, cv2.LINE_AA)
        cv2.rectangle(window, (left, top), (right, top + card_height),
                      (66, 71, 78) if disabled else (111, 142, 153), 2, cv2.LINE_AA)
        cv2.putText(window, heading, (left + 18, top + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45 if compact else 0.77,
                    (115, 120, 128) if disabled else (240, 245, 247), 2, cv2.LINE_AA)
        cv2.putText(window, detail, (left + 18, top + 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.37 if compact else 0.53,
                    (135, 141, 150) if disabled else (179, 195, 201), 1, cv2.LINE_AA)

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONUP:
            for mode, _, _, left, top in buttons:
                right = left + (277 if compact else 570)
                if mode in available and left <= x <= right and top <= y <= top + card_height:
                    selected[0] = mode

    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, on_mouse)
    try:
        while selected[0] is None:
            if check_license:
                check_license()
            cv2.imshow(title, window)
            key = cv2.waitKey(30) & 0xFF
            if ord("1") <= key < ord("1") + len(display_modes):
                candidate = display_modes[key - ord("1")]
                if candidate in available:
                    selected[0] = candidate
            elif key in (ord("q"), 27):
                return None
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                return None
        return selected[0]
    finally:
        cv2.destroyWindow(title)


def choose_camera(initial_index: int = 0, mirror: bool = True, check_license=None) -> int | None:
    """Preview camera indices 0-9 before opening the clean video output."""
    title = "Choose Webcam"
    selected = [max(0, min(9, initial_index))]
    confirmed = [False]
    opened_index = None
    capture = None
    preview_ready = False
    read_failures = 0

    def on_mouse(event, x, y, flags, userdata):
        if event != cv2.EVENT_LBUTTONUP or not 472 <= y <= 535:
            return
        if 70 <= x <= 165:
            selected[0] = max(0, selected[0] - 1)
        elif 180 <= x <= 275:
            selected[0] = min(9, selected[0] + 1)
        elif 445 <= x <= 710 and preview_ready:
            confirmed[0] = True

    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, on_mouse)
    try:
        while True:
            if check_license:
                check_license()
            if selected[0] != opened_index:
                if capture is not None:
                    capture.release()
                try:
                    capture = open_camera(selected[0], 640, 360)
                except RuntimeError:
                    capture = None
                opened_index = selected[0]
                preview_ready = False
                read_failures = 0

            window = np.full((560, 780, 3), (26, 29, 34), dtype=np.uint8)
            cv2.putText(window, "CHOOSE YOUR WEBCAM", (70, 59),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.86, (236, 239, 242), 2, cv2.LINE_AA)
            cv2.putText(window, "0-9 or A/D switch  |  ENTER confirm  |  R retry", (70, 82),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.43, (179, 195, 201), 1, cv2.LINE_AA)
            cv2.rectangle(window, (69, 94), (711, 456), (111, 142, 153), 2)
            if capture is not None:
                ok, frame = capture.read()
                if ok:
                    if mirror:
                        frame = cv2.flip(frame, 1)
                    window[95:455, 70:710] = cv2.resize(frame, (640, 360))
                    preview_ready = True
                    read_failures = 0
                else:
                    read_failures += 1
                    if read_failures >= 10:
                        capture.release()
                        capture = None
                        preview_ready = False
            if not preview_ready:
                message = ("Waiting for webcam signal..." if capture is not None
                           else "No signal from this webcam")
                cv2.putText(window, message, (125, 277),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.72, (179, 195, 201), 2, cv2.LINE_AA)

            for left, right, label in ((70, 165, "-"), (180, 275, "+")):
                cv2.rectangle(window, (left, 472), (right, 535), (48, 54, 62), -1)
                cv2.rectangle(window, (left, 472), (right, 535), (111, 142, 153), 2)
                cv2.putText(window, label, (left + 35, 516), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (240, 245, 247), 2, cv2.LINE_AA)
            cv2.putText(window, f"CAM {selected[0]}", (302, 514),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.72, (240, 245, 247), 2, cv2.LINE_AA)
            button_color = (78, 132, 124) if preview_ready else (48, 54, 62)
            cv2.rectangle(window, (445, 472), (710, 535), button_color, -1)
            cv2.putText(window, "USE THIS WEBCAM", (464, 511),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.57, (240, 245, 247), 2, cv2.LINE_AA)
            if check_license:
                check_license()
            cv2.imshow(title, window)

            key = cv2.waitKey(30) & 0xFF
            if ord("0") <= key <= ord("9"):
                selected[0] = key - ord("0")
            elif key in (ord("a"), ord("A")):
                selected[0] = max(0, selected[0] - 1)
            elif key in (ord("d"), ord("D")):
                selected[0] = min(9, selected[0] + 1)
            elif key in (ord("r"), ord("R")):
                opened_index = None
            elif key in (10, 13) and preview_ready:
                confirmed[0] = True
            elif key in (ord("q"), 27):
                return None
            if confirmed[0] and preview_ready:
                return selected[0]
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                return None
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyWindow(title)


def open_virtual_camera(args: argparse.Namespace, width: int, height: int):
    if args.virtual_camera is False:
        return None
    try:
        import pyvirtualcam

        camera = pyvirtualcam.Camera(
            width=width, height=height, fps=args.fps,
            fmt=pyvirtualcam.PixelFormat.BGR,
            backend=args.virtual_backend, device=args.virtual_device,
        )
    except (ImportError, RuntimeError, OSError, ValueError) as error:
        message = (
            "Virtual camera unavailable. Install OBS Studio (with OBS Virtual Camera) "
            "or v4l2loopback on Linux. If using OBS Virtual Camera, stop it in OBS first. "
            f"Details: {error}"
        )
        if args.virtual_camera is True or args.virtual_backend or args.virtual_device:
            raise RuntimeError(message) from error
        print(f"[Webcam] {message}\n[Webcam] Continuing with local preview.")
        return None
    print(f"[Webcam] Virtual output active: {camera.device} ({width}x{height}, {args.fps:g} max FPS)")
    return camera


def send_virtual_frame(camera, frame: np.ndarray) -> None:
    if frame.shape[:2] != (camera.height, camera.width):
        frame = cv2.resize(frame, (camera.width, camera.height), interpolation=cv2.INTER_LINEAR)
    if not frame.flags.c_contiguous:
        frame = np.ascontiguousarray(frame)
    camera.send(frame)


def download_models(mode: str = "normal") -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for destination, url in MODEL_URLS.items():
        if mode in ("naruto", "goku", "itachi", "snap") and destination == GESTURE_MODEL:
            continue
        if mode != "goku" and destination == FACE_MODEL:
            continue
        if destination.exists() and destination.stat().st_size > 100_000:
            continue

        temporary = destination.with_suffix(destination.suffix + ".part")
        print(f"[Vanish Lab] Downloading {destination.name}...")
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "Vanish-Lab/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                total = int(response.headers.get("Content-Length", 0))
                received = 0
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 256):
                        output.write(chunk)
                        received += len(chunk)
                        if total:
                            percent = int(received * 100 / total)
                            print(f"\r  {percent:3d}%", end="", flush=True)
            print()
            os.replace(temporary, destination)
        except (OSError, urllib.error.URLError) as error:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(
                "Could not download MediaPipe models. "
                "Check your internet connection and try again."
            ) from error


def open_camera(index: int, width: int, height: int) -> cv2.VideoCapture:
    if platform.system() == "Windows":
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(index)
    else:
        # Raw YUYV is bandwidth-capped on most UVC webcams (often 5-15 FPS at
        # 720p); MJPG keeps the full 30 FPS.
        capture = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        else:
            capture.release()
            capture = cv2.VideoCapture(index)

    if not capture.isOpened():
        raise RuntimeError(
            f"Webcam {index} unavailable. Close other apps or try --camera 1."
        )

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    # V4L2 with buffersize=1 halves UVC MJPG throughput (30 -> 15 fps) on Linux.
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1 if platform.system() == "Windows" else 2)
    return capture


def create_recognizer(
    mode: str = "normal",
) -> MultiViewGestureRecognizer | MultiViewHandLandmarker | GokuPoseRecognizer | ItachiPoseRecognizer | SnapPoseRecognizer:
    if mode == "goku":
        if not HAND_MODEL.is_file() or not FACE_MODEL.is_file():
            raise RuntimeError("Missing hand or face models for Goku mode.")
        hand_options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(HAND_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.35,
            min_hand_presence_confidence=0.35,
            min_tracking_confidence=0.45,
        )
        face_options = vision.FaceDetectorOptions(
            base_options=python.BaseOptions(model_asset_path=str(FACE_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            min_detection_confidence=0.5,
        )
        hands = vision.HandLandmarker.create_from_options(hand_options)
        try:
            fallback_hands = vision.HandLandmarker.create_from_options(
                replace(hand_options, running_mode=vision.RunningMode.IMAGE)
            )
            try:
                face = vision.FaceDetector.create_from_options(face_options)
            except Exception:
                fallback_hands.close()
                raise
        except Exception:
            hands.close()
            raise
        return GokuPoseRecognizer(hands, face, fallback_hands)
    if mode == "snap":
        if not HAND_MODEL.is_file():
            raise RuntimeError(f"Hand model not found: {HAND_MODEL}")
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(HAND_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.55,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55,
        )
        hands = vision.HandLandmarker.create_from_options(options)
        return SnapPoseRecognizer(hands)
    if mode in ("naruto", "itachi"):
        if not HAND_MODEL.is_file():
            raise RuntimeError(f"Hand model not found: {HAND_MODEL}")
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(HAND_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.35,
            min_hand_presence_confidence=0.35,
            min_tracking_confidence=0.45,
        )
        task_class = vision.HandLandmarker
        wrapper_class = MultiViewHandLandmarker
    else:
        classifier_options = mp.tasks.components.processors.ClassifierOptions(
            score_threshold=0.55,
            category_allowlist=["Victory"],
        )
        options = vision.GestureRecognizerOptions(
            base_options=python.BaseOptions(model_asset_path=str(GESTURE_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.35,
            min_hand_presence_confidence=0.35,
            min_tracking_confidence=0.5,
            canned_gesture_classifier_options=classifier_options,
        )
        task_class = vision.GestureRecognizer
        wrapper_class = MultiViewGestureRecognizer

    primary = task_class.create_from_options(options)
    try:
        alternate = task_class.create_from_options(
            replace(options, running_mode=vision.RunningMode.IMAGE)
        )
    except Exception:
        primary.close()
        raise
    if mode == "itachi":
        return ItachiPoseRecognizer(primary, alternate)
    return wrapper_class(primary, alternate)


def create_tasks(mode: str = "normal") -> tuple[
    vision.ImageSegmenter,
    MultiViewGestureRecognizer | MultiViewHandLandmarker | GokuPoseRecognizer | ItachiPoseRecognizer | SnapPoseRecognizer,
]:
    segmenter_options = vision.ImageSegmenterOptions(
        base_options=python.BaseOptions(model_asset_path=str(SEGMENTER_MODEL)),
        running_mode=vision.RunningMode.VIDEO,
        output_confidence_masks=True,
        output_category_mask=False,
    )
    segmenter = vision.ImageSegmenter.create_from_options(segmenter_options)
    try:
        recognizer = create_recognizer(mode)
    except Exception:
        segmenter.close()
        raise
    return segmenter, recognizer


def smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    values = np.clip((values - edge0) / max(edge1 - edge0, 1e-6), 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def ease_in_out_cubic(value: float) -> float:
    if value < 0.5:
        return 4.0 * value * value * value
    return 1.0 - ((-2.0 * value + 2.0) ** 3) / 2.0


def make_dissolve_fields(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7391)
    y, x = np.mgrid[0:height, 0:width]
    y_normal = y.astype(np.float32) / max(height - 1, 1)
    x_normal = x.astype(np.float32) / max(width - 1, 1)
    low_noise = rng.random((max(2, height // 10), max(2, width // 10)), dtype=np.float32)
    low_noise = cv2.resize(low_noise, (width, height), interpolation=cv2.INTER_CUBIC)
    fine_noise = rng.random((height, width), dtype=np.float32)
    field = (
        (1.0 - y_normal) * 0.72
        + low_noise * 0.17
        + fine_noise * 0.08
        + np.sin(x_normal * 18.0) * 0.025
    )
    return np.clip(field, 0.0, 1.0), fine_noise


def make_ghost_sample(frame: np.ndarray, max_width: int = 640) -> np.ndarray:
    """Create a downscaled, pre-tinted cyan Ghost Echo sample to minimize RAM and per-frame casts."""
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / float(w)
        sample = cv2.resize(
            frame,
            (max_width, max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        sample = frame.copy()
    sample[:, :, 2] = (sample[:, :, 2].astype(np.uint16) * 35 // 100).astype(np.uint8)
    sample[:, :, 0] = np.minimum(sample[:, :, 0].astype(np.uint16) + 55, 255).astype(np.uint8)
    return np.ascontiguousarray(sample)


def to_gesture_mp_image(frame: np.ndarray, max_width: int = 640) -> mp.Image:
    """Convert a BGR frame to an RGB MediaPipe Image, downscaling large frames to cut gesture CPU."""
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / float(w)
        small = cv2.resize(
            frame,
            (max_width, max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    else:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


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


def person_mask(
    segmenter: vision.ImageSegmenter,
    image: mp.Image,
    timestamp_ms: int,
    width: int,
    height: int,
) -> np.ndarray:
    result = segmenter.segment_for_video(image, timestamp_ms)
    if not result.confidence_masks:
        return np.zeros((height, width), dtype=np.float32)
    raw = np.squeeze(result.confidence_masks[0].numpy_view()).astype(np.float32)
    resized = cv2.resize(raw, (width, height), interpolation=cv2.INTER_LINEAR)
    resized = cv2.GaussianBlur(resized, (0, 0), sigmaX=2.2, sigmaY=2.2)
    return np.clip((resized - 0.12) / 0.68, 0.0, 1.0)


def alpha_composite(person: np.ndarray, background: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    alpha_3 = alpha[:, :, None]
    return (
        person.astype(np.float32) * alpha_3
        + background.astype(np.float32) * (1.0 - alpha_3)
    ).astype(np.uint8)


def apply_dissolve(
    frame: np.ndarray,
    background: np.ndarray,
    mask: np.ndarray,
    progress: float,
    field: np.ndarray,
    sparkle_noise: np.ndarray,
) -> np.ndarray:
    if progress <= 0.002:
        return alpha_composite(frame, background, mask)
    if progress >= 0.999:
        return background.copy()

    points = cv2.findNonZero((mask > 0.01).astype(np.uint8))
    if points is None:
        return background.copy()
    x, y, width, height = cv2.boundingRect(points)
    left, top = max(0, x - 18), max(0, y - 18)
    right = min(mask.shape[1], x + width + 18)
    bottom = min(mask.shape[0], y + height + 18)
    area = np.s_[top:bottom, left:right]
    mask = mask[area]
    field = field[area]
    sparkle_noise = sparkle_noise[area]
    eased = ease_in_out_cubic(progress)
    survival = smoothstep(eased - 0.055, eased + 0.055, field)
    alpha = mask * survival
    output = alpha_composite(frame[area], background[area], alpha)
    edge = (
        (np.abs(field - eased) < 0.018)
        & (mask > 0.48)
        & (sparkle_noise > 0.54)
    ).astype(np.float32)
    glow = cv2.GaussianBlur(edge, (0, 0), sigmaX=5.0, sigmaY=5.0)
    glow = np.clip(glow * 5.0 + edge, 0.0, 1.0)[:, :, None]
    cyan = np.full_like(output, (255, 228, 92), dtype=np.uint8)
    result = np.clip(
        output.astype(np.float32) * (1.0 - glow * 0.8)
        + cyan.astype(np.float32) * glow * 0.8,
        0,
        255,
    ).astype(np.uint8)
    canvas = background.copy()
    canvas[area] = result
    return canvas


def victory_landmark_score(points: np.ndarray) -> float:
    """Riconosci indice e medio distesi usando distanze 3D, non l'orientamento."""
    if points.shape != (21, 3) or not np.isfinite(points).all():
        return 0.0

    straightness = []
    extended = []
    folded = []
    lengths = []
    # MCP, PIP, DIP e punta: indice, medio, anulare, mignolo.
    for index, base in enumerate((5, 9, 13, 17)):
        finger = points[base : base + 4]
        length = float(np.linalg.norm(np.diff(finger, axis=0), axis=1).sum())
        if length < 1e-6:
            if index < 2:
                return 0.0
            straightness.append(0.0)
            lengths.append(0.0)
            extended.append(False)
            folded.append(True)
            continue
        ratio = float(np.linalg.norm(finger[3] - finger[0])) / length
        tip_distance = float(np.linalg.norm(finger[3] - points[0]))
        joint_distance = float(np.linalg.norm(finger[1] - points[0]))
        straightness.append(ratio)
        lengths.append(length)
        extended.append(ratio >= 0.82 and tip_distance > joint_distance * 1.10)
        folded.append(ratio < 0.78 or tip_distance <= joint_distance * 1.05)

    # Di lato le dita ripiegate possono apparire dritte ma molto corte:
    # non pretendere articolazioni ben visibili per anulare e mignolo.
    reference_length = min(lengths[:2])
    for index, base in ((2, 13), (3, 17)):
        reach = float(np.linalg.norm(points[base + 3] - points[base]))
        folded[index] = folded[index] or reach < reference_length * 0.65
    if not (extended[0] and extended[1] and folded[2] and folded[3]):
        return 0.0
    # Le due punte devono essere separate; il pollice puo' restare nascosto.
    separation = float(np.linalg.norm(points[8] - points[12]))
    if separation < min(lengths[:2]) * 0.20:
        return 0.0
    # Qualita' geometrica delle dita distese, non probabilita' del classificatore.
    return float(np.clip(min(straightness[:2]), 0.0, 1.0))


def classify_gesture_result(
    result: vision.GestureRecognizerResult,
    image: mp.Image,
) -> tuple[str, float]:
    # I landmark vengono restituiti anche quando il classificatore non riconosce
    # "Victory" (ad esempio con il dorso della mano rivolto alla webcam).
    for landmarks in result.hand_world_landmarks:
        points = np.array([(point.x, point.y, point.z) for point in landmarks])
        score = victory_landmark_score(points)
        if score:
            return "Victory", score
    # Controlla SEMPRE anche la geometria visibile: la profondita' stimata
    # puo' essere imprecisa quando palmo e dita piegate sono nascosti.
    for landmarks in result.hand_landmarks:
        points = np.array([(point.x * image.width, point.y * image.height, 0.0)
                           for point in landmarks])
        score = victory_landmark_score(points)
        if score:
            return "Victory", score
    for categories in result.gestures:
        for category in categories:
            if category.category_name == "Victory" and category.score >= 0.62:
                return "Victory", float(category.score)
    if result.hand_landmarks or result.hand_world_landmarks:
        return "Hand_Detected", 0.0
    return "No_Hand", 0.0


class MultiViewGestureRecognizer:
    """Riprova la rilevazione su fotogrammi ruotati senza alterare il tracking."""

    def __init__(self, primary, alternate):
        self.primary = primary
        self.alternate = alternate
        self.preferred_rotation: int | None = None
        self.preferred_crop: str | None = None
        self.next_retry_ms = 0
        self.retry_cursor = 0

    def recognize_gesture(self, image: mp.Image, timestamp_ms: int) -> tuple[str, float]:
        result = self.primary.recognize_for_video(image, timestamp_ms)
        best = classify_gesture_result(result, image)
        if best[0] == "Victory":
            self.preferred_rotation = None
            self.preferred_crop = None
            return best
        if timestamp_ms < self.next_retry_ms:
            return best

        # IMAGE forza una nuova rilevazione; il modello VIDEO resta sul frame
        # originale. Evita timestamp/tracking incoerenti tra rotazioni diverse.
        rgb = image.numpy_view()
        height, width = rgb.shape[:2]
        # Il palmo nella posa laterale e' spesso troppo piccolo nel frame
        # completo. I due ritagli inferiori si sovrappongono e coprono entrambe
        # le mani, anche quando l'immagine e' specchiata.
        crops = {
            "full": rgb,
            "lower_left": rgb[int(height * 0.28):, :int(width * 0.78)],
            "lower_right": rgb[int(height * 0.28):, int(width * 0.22):],
        }
        views = [("full", rotation) for rotation in (0, 1, 3, 2)]
        views += [(crop, rotation) for crop in ("lower_left", "lower_right")
                  for rotation in (0, 1, 3)]
        preferred = (self.preferred_crop, self.preferred_rotation)
        selected = []
        if preferred in views:
            selected.append(preferred)
        # Spread the expensive IMAGE attempts over successive video frames.
        while len(selected) < 3:
            view = views[self.retry_cursor % len(views)]
            self.retry_cursor += 1
            if view not in selected:
                selected.append(view)
        for crop, rotation in selected:
            rotated = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(np.rot90(crops[crop], rotation)),
            )
            result = self.alternate.recognize(rotated)
            candidate = classify_gesture_result(result, rotated)
            if candidate[0] == "Victory":
                self.preferred_rotation = rotation
                self.preferred_crop = crop
                self.next_retry_ms = timestamp_ms + int(GESTURE_INTERVAL_SECONDS * 1000)
                return candidate
            if candidate[0] == "Hand_Detected":
                best = candidate
        self.preferred_rotation = None
        self.preferred_crop = None
        self.next_retry_ms = timestamp_ms + int(GESTURE_INTERVAL_SECONDS * 1000)
        return best

    def close(self) -> None:
        try:
            self.primary.close()
        finally:
            self.alternate.close()


class MultiViewHandLandmarker:
    """Track two hands in video and retry difficult views with the hand model."""

    def __init__(self, primary, alternate):
        self.primary = primary
        self.alternate = alternate
        self.preferred_view: tuple[str, int] | None = None
        self.next_retry_ms = 0
        self.last_hand_count = 0
        self.retry_cursor = 0

    def recognize_joined_hands(self, image: mp.Image, timestamp_ms: int) -> bool:
        result = self.primary.detect_for_video(image, timestamp_ms)
        self.last_hand_count = len(result.hand_landmarks)
        if joined_hands_from_landmarks(result.hand_landmarks, image.width, image.height):
            self.preferred_view = None
            return True
        if timestamp_ms < self.next_retry_ms:
            return False

        rgb = image.numpy_view()
        height, width = rgb.shape[:2]
        views = {
            "full": rgb,
            "center": rgb[int(height * 0.18):, int(width * 0.12):int(width * 0.88)],
            "lower_left": rgb[int(height * 0.22):, :int(width * 0.78)],
            "lower_right": rgb[int(height * 0.22):, int(width * 0.22):],
        }
        attempts = [("full", rotation) for rotation in (1, 3, 2)]
        attempts += [("center", rotation) for rotation in (0, 1, 3)]
        attempts += [("lower_left", 0), ("lower_right", 0)]
        selected = []
        if self.preferred_view in attempts:
            selected.append(self.preferred_view)
        while len(selected) < 2:
            view = attempts[self.retry_cursor % len(attempts)]
            self.retry_cursor += 1
            if view not in selected:
                selected.append(view)
        for crop, rotation in selected:
            rotated = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(np.rot90(views[crop], rotation)),
            )
            result = self.alternate.detect(rotated)
            self.last_hand_count = max(self.last_hand_count, len(result.hand_landmarks))
            if joined_hands_from_landmarks(result.hand_landmarks, rotated.width, rotated.height):
                self.preferred_view = (crop, rotation)
                self.next_retry_ms = timestamp_ms + 90
                return True
        self.preferred_view = None
        self.next_retry_ms = timestamp_ms + (220 if self.last_hand_count == 0 else 80)
        return False

    def close(self) -> None:
        try:
            self.primary.close()
        finally:
            self.alternate.close()


def recognize_gesture(
    recognizer: MultiViewGestureRecognizer,
    image: mp.Image,
    timestamp_ms: int,
) -> tuple[str, float]:
    if isinstance(recognizer, MultiViewGestureRecognizer):
        return recognizer.recognize_gesture(image, timestamp_ms)
    return classify_gesture_result(recognizer.recognize_for_video(image, timestamp_ms), image)


def start_vanish_on_gesture(state: AppState, name: str, score: float, now: float) -> bool:
    """Avvia la dissolvenza al primo riconoscimento affidabile della V."""
    if state.phase == "ready" and name == "Victory" and score >= 0.62:
        state.phase = "vanishing"
        state.vanish_started = now
        return True
    return False


def start_naruto_on_join(state: AppState, joined: bool, now: float) -> bool:
    if state.phase == "ready" and joined:
        state.phase = "naruto_vanishing"
        state.vanish_started = now
        return True
    return False


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


def load_saved_background(width: int, height: int) -> np.ndarray | None:
    if not SAVED_BG_PATH.is_file():
        return None
    img = cv2.imread(str(SAVED_BG_PATH))
    if img is None:
        return None
    if img.shape[:2] != (height, width):
        src_ratio = img.shape[1] / float(max(1, img.shape[0]))
        dst_ratio = width / float(max(1, height))
        if abs(src_ratio - dst_ratio) > 0.05:
            return None
        img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
    return img


def save_background(background: np.ndarray) -> None:
    try:
        SAVED_BG_PATH.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(SAVED_BG_PATH), background)
    except OSError:
        pass


def write_ipc_state(
    running: bool,
    mode: str = "",
    state: AppState | None = None,
    snap_message: str = "",
) -> None:
    """Write live JSON state to /tmp/vanish_cam.state.json for CLI and Noctalia/Niri plugins."""
    payload = {
        "running": running,
        "pid": os.getpid() if running else None,
        "mode": mode if running else "",
        "phase": state.phase if (running and state is not None) else "off",
        "gestures_paused": bool(state.gestures_paused) if (running and state is not None) else False,
        "preview_visible": bool(state.preview_visible) if (running and state is not None) else False,
        "ghost_echo": bool(state.ghost_echo) if (running and state is not None) else False,
        "snap_message": snap_message if (running and mode == "snap") else "",
        "updated_at": round(time.time(), 2),
    }
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def poll_ipc_commands() -> list[str]:
    """Read and clear queued remote commands from /tmp/vanish_cam.cmd."""
    if not CMD_FILE.is_file():
        return []
    try:
        raw = CMD_FILE.read_text(encoding="utf-8")
        CMD_FILE.unlink(missing_ok=True)
        return [line.strip() for line in raw.splitlines() if line.strip()]
    except OSError:
        return []


def _hud_menu_buttons(w: int, h: int, mode: str, state: AppState) -> list[tuple[str, str, tuple[int, int, int, int]]]:
    is_away = state.phase in ("vanished", "frozen")
    action_label = "Reappear Now (R)" if is_away else "Vanish Now (V)"
    action_cmd = "reappear" if is_away else "vanish"
    freeze_label = "Unfreeze Camera (Z)" if state.phase == "frozen" else "Freeze Frame (Z)"
    pause_label = "Resume Gestures (G)" if state.gestures_paused else "Pause Gestures (G)"
    echo_label = f"Ghost Echo: {'ON' if state.ghost_echo else 'OFF'} (E)"
    items = [
        (action_cmd, action_label),
        ("freeze", freeze_label),
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
    modes = ("snap", "naruto", "normal", "particles", "itachi", "goku")
    inner_w = box_w - 32
    cell_w = (inner_w - 5 * 4) // 6
    my1 = by1 + 36
    for idx, m in enumerate(modes):
        mx1 = bx1 + 16 + idx * (cell_w + 4)
        mx2 = mx1 + cell_w if idx < 5 else bx1 + box_w - 16
        buttons.append((f"mode:{m}", m[:4].upper(), (mx1, my1, mx2, my1 + mode_row_h)))
    for idx, (cmd, label) in enumerate(items):
        y1 = my1 + mode_row_h + 8 + idx * (row_h + gap)
        buttons.append((cmd, label, (bx1 + 16, y1, bx1 + box_w - 16, y1 + row_h)))
    return buttons


def draw_preview_hud(
    frame: np.ndarray,
    mode: str,
    state: AppState,
    snap_message: str = "",
) -> np.ndarray:
    """Draw a subtle bottom status pill and clickable control menu on preview only."""
    out = frame.copy() if frame is not None else frame
    h, w = out.shape[:2]
    gesture_state = "PAUSED" if state.gestures_paused else "ON"
    mode_tag = f"SNAP: {snap_message}" if mode == "snap" and snap_message else mode.upper()
    if state.phase == "frozen":
        mode_tag = f"{mode_tag} [FROZEN]"
    elif state.ghost_echo:
        mode_tag = f"{mode_tag} [ECHO]"
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


def set_fullscreen(enabled: bool) -> None:
    mode = cv2.WINDOW_FULLSCREEN if enabled else cv2.WINDOW_NORMAL
    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, mode)


def self_test() -> int:
    """Check bundled resources and model initialization without opening a webcam."""
    load_config()
    modes = edition_modes()
    required = [SEGMENTER_MODEL]
    if any(mode in modes for mode in ("normal", "particles")):
        required.append(GESTURE_MODEL)
    if any(mode in modes for mode in ("naruto", "goku", "itachi")):
        required.append(HAND_MODEL)
    if "goku" in modes:
        required.extend((FACE_MODEL, TELEPORT_SOUND_PATH))
    if "itachi" in modes:
        required.extend((CROW_SHEET_PATH, SHARINGAN_PATH))
    if "naruto" in modes:
        required.extend((LOG_PATH, SOUND_PATH))
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing resources: {', '.join(missing)}")
    if "naruto" in modes:
        load_log()
    if "itachi" in modes:
        load_crow_sprites()
        load_sharingan_art()
    for sound_path in (SOUND_PATH, TELEPORT_SOUND_PATH):
        if sound_path not in required:
            continue
        sound = VanishSound(sound_path)
        sound.close()
    for mode in modes:
        segmenter, recognizer = create_tasks(mode)
        try:
            recognizer.close()
        finally:
            segmenter.close()
    print("[Webcam] Self-test passed: models, assets, and audio present.")
    return 0


def run(license_session=None) -> int:
    args = parse_args()
    if getattr(args, "self_test", False):
        return self_test()
    available = edition_modes()
    check = license_session.ensure_valid if license_session is not None else None
    mode = args.mode or (available[0] if len(available) == 1 else (
        choose_mode(available, check_license=check) if check else choose_mode(available)))
    if mode is None:
        return 0
    if license_session is not None:
        license_session.backend.mode = mode if mode in LICENSE_REPORTED_MODES else "full"
    if args.camera is None:
        args.camera = (choose_camera(mirror=not args.no_mirror, check_license=check)
                       if check else choose_camera(mirror=not args.no_mirror))
        if args.camera is None:
            return 0
    if mode == "goku":
        args.goku_delay = choose_goku_delay(check_license=check) if check else choose_goku_delay()
        if args.goku_delay is None:
            return 0
    with ExitStack() as resources:
        if check:
            check()
            return run_camera(args, resources, mode, license_session)
        return run_camera(args, resources, mode)


def run_camera(args: argparse.Namespace, resources: ExitStack, mode: str, license_session=None) -> int:
    if hasattr(cv2, "setNumThreads"):
        cv2.setNumThreads(2)
    download_models(mode)
    capture = open_camera(args.camera, args.width, args.height)
    resources.callback(capture.release)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    segmenter, recognizer = create_tasks(mode)
    active_recognizer = [recognizer]
    resources.callback(segmenter.close)
    resources.callback(lambda: active_recognizer[0].close())
    log_sprite = load_log() if mode == "naruto" else None
    sound_path = {"naruto": SOUND_PATH, "goku": TELEPORT_SOUND_PATH, "snap": SNAP_SOUND_PATH}.get(mode)
    vanish_sound = VanishSound(sound_path) if sound_path is not None else None
    active_sound = [vanish_sound]
    resources.callback(lambda: active_sound[0].close() if active_sound[0] is not None else None)
    chime_sound = VanishSound(CHIME_SOUND_PATH) if mode == "snap" and CHIME_SOUND_PATH.is_file() else None
    active_chime = [chime_sound]
    resources.callback(lambda: active_chime[0].close() if active_chime[0] is not None else None)
    resources.callback(cv2.destroyAllWindows)

    start_preview = not bool(getattr(args, "no_preview", False))
    state = AppState(
        calibration_started=time.perf_counter(),
        fullscreen=args.fullscreen,
        preview_visible=start_preview,
    )
    if state.preview_visible:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, args.width, args.height)
        if state.fullscreen:
            set_fullscreen(True)

    background: np.ndarray | None = None
    background_samples: list[np.ndarray] = []
    last_mask: np.ndarray | None = None
    last_mask_at = float("-inf")
    dissolve_field: np.ndarray | None = None
    sparkle_noise: np.ndarray | None = None
    log_anchor: tuple[int, int, int] | None = None
    log_cache: dict[int, np.ndarray] = {}
    vanished_frame: np.ndarray | None = None
    frozen_frame: np.ndarray | None = None
    echo_buffer: list[np.ndarray] = []
    last_echo_sample = 0.0
    particle_effect: ParticleEffect | None = None
    itachi_effect: ItachiCrowEffect | None = None
    itachi_gate = ItachiGestureGate() if mode == "itachi" else None
    goku_effect: GokuTeleport | None = None
    goku_delay = getattr(args,"goku_delay",HOLD_SECONDS)
    goku_gate = GokuGestureGate(hold_seconds=goku_delay) if mode == "goku" else None
    goku_countdown_remaining: float | None = None
    snap_effect: SnapVoidEffect | None = None
    snap_rebuild: SnapRebuildEffect | None = None
    custom_snap_text = (getattr(args, "snap_text", None) or "").strip()
    snap_messages = (custom_snap_text, *VOID_MESSAGES) if custom_snap_text else VOID_MESSAGES
    snap_msg_idx = 0
    snap_primed = False
    snap_pos = (0, 0)
    reused_bg_checked = False
    preview_hud = bool(getattr(args, "preview_hud", False))
    pending_keys: list[int] = []
    pending_mode_switch: list[str] = []
    frame_size = [args.width, args.height]
    last_ipc_signature = None
    last_ipc_write = 0.0

    def on_preview_mouse(event, x, y, flags, userdata):
        nonlocal snap_messages, snap_msg_idx, last_ipc_signature
        if event != cv2.EVENT_LBUTTONUP:
            return
        w, h = frame_size
        if state.show_help:
            for cmd, _, (rx1, ry1, rx2, ry2) in _hud_menu_buttons(w, h, mode, state):
                if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                    if cmd.startswith("mode:"):
                        pending_mode_switch.append(cmd.split(":", 1)[1])
                        return
                    if cmd == "edit-text":
                        if state.editing_text:
                            custom = state.edit_buffer.strip()
                            if custom:
                                snap_messages = (custom, *VOID_MESSAGES)
                                snap_msg_idx = 0
                                last_ipc_signature = None
                            state.editing_text = False
                        else:
                            state.edit_buffer = ""
                            state.editing_text = True
                        return
                    key_map = {
                        "vanish": ord("v"),
                        "reappear": ord("r"),
                        "freeze": ord("z"),
                        "pause": ord("g"),
                        "echo": ord("e"),
                        "recapture": ord(" "),
                        "load-bg": ord("b"),
                        "next-text": ord("t"),
                        "preview": ord("p"),
                        "help": ord("h"),
                    }
                    if cmd in key_map:
                        pending_keys.append(key_map[cmd])
                    return
        if 14 <= x <= 380 and h - 48 <= y <= h - 10:
            pending_keys.append(ord("h"))

    if preview_hud and state.preview_visible:
        try:
            cv2.setMouseCallback(WINDOW_NAME, on_preview_mouse)
        except cv2.error:
            pass
    virtual_camera = None
    virtual_camera_initialized = False
    calibration_seconds = max(BACKGROUND_SAMPLE_SECONDS, getattr(args, "bg_delay", CALIBRATION_SECONDS))
    calibration_remaining = None
    bg_ready_until = 0.0
    last_gesture_report = 0.0
    async_gestures = bool(getattr(args, "async_gestures", False)) and mode not in ("goku", "itachi", "snap")
    gesture_executor = ThreadPoolExecutor(max_workers=1) if async_gestures else None
    if gesture_executor is not None:
        resources.callback(gesture_executor.shutdown, wait=True)
    gesture_future: Future | None = None
    started = time.perf_counter()

    def toggle_preview_window():
        state.preview_visible = not state.preview_visible
        if state.preview_visible:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(WINDOW_NAME, frame_size[0], frame_size[1])
            if state.fullscreen:
                set_fullscreen(True)
            if preview_hud:
                try:
                    cv2.setMouseCallback(WINDOW_NAME, on_preview_mouse)
                except cv2.error:
                    pass
            print("[Webcam] Preview window shown.")
        else:
            state.show_help = False
            try:
                cv2.destroyWindow(WINDOW_NAME)
                cv2.waitKey(1)
            except cv2.error:
                pass
            print("[Webcam] Preview window hidden (run 'vanish-cam preview' to show again).")

    def switch_mode(new_mode: str):
        nonlocal mode, recognizer, log_sprite, vanish_sound, chime_sound
        nonlocal itachi_gate, goku_gate, goku_countdown_remaining, gesture_executor, gesture_future
        nonlocal particle_effect, itachi_effect, goku_effect, snap_effect, snap_rebuild
        nonlocal log_anchor, vanished_frame, snap_primed, last_ipc_signature
        if new_mode == mode or new_mode not in ALL_MODES:
            return
        download_models(new_mode)
        if gesture_future is not None:
            try:
                gesture_future.result(timeout=0.5)
            except Exception:
                pass
            gesture_future = None
        new_rec = create_recognizer(new_mode)
        active_recognizer[0].close()
        recognizer = new_rec
        active_recognizer[0] = new_rec
        if new_mode == "naruto" and log_sprite is None:
            log_sprite = load_log()
        new_sound_path = {"naruto": SOUND_PATH, "goku": TELEPORT_SOUND_PATH, "snap": SNAP_SOUND_PATH}.get(new_mode)
        if active_sound[0] is not None:
            active_sound[0].close()
            active_sound[0] = None
        vanish_sound = VanishSound(new_sound_path) if new_sound_path is not None else None
        active_sound[0] = vanish_sound
        if new_mode == "snap" and chime_sound is None and CHIME_SOUND_PATH.is_file():
            chime_sound = VanishSound(CHIME_SOUND_PATH)
            active_chime[0] = chime_sound
        itachi_gate = ItachiGestureGate() if new_mode == "itachi" else None
        goku_gate = GokuGestureGate(hold_seconds=goku_delay) if new_mode == "goku" else None
        goku_countdown_remaining = None
        if bool(getattr(args, "async_gestures", False)) and new_mode not in ("goku", "itachi", "snap") and gesture_executor is None:
            gesture_executor = ThreadPoolExecutor(max_workers=1)
            resources.callback(gesture_executor.shutdown, wait=True)
        particle_effect = None
        itachi_effect = None
        goku_effect = None
        snap_effect = None
        snap_rebuild = None
        log_anchor = None
        snap_primed = False
        if state.phase not in ("calibrating", "ready", "vanished"):
            state.phase = "ready"
        if state.phase == "vanished" and background is not None:
            vanished_frame = background.copy()
        mode = new_mode
        last_ipc_signature = None
        print(f"[Webcam] Switched mode live -> {mode.upper()}")
    print(f"[Webcam] Step out of frame for {calibration_seconds:g}s: capturing background (ENTER to capture now).")
    print("[Webcam] Controls: H help, SPACE new background, B load saved room, G pause gestures, F fullscreen, Q quit.")
    if mode == "goku":
        print(f"[Webcam] Goku: hold two fingers together on your forehead for {goku_delay:g}s to vanish or reappear. "
              "Release the pose before repeating.")
    else:
        print("[Webcam] Also: V vanish, R reappear.")
        if mode == "itachi":
            print("[Itachi] Touch both hands in front of the center of your chest. "
                  "Release and repeat to reappear.")
        elif mode == "snap":
            print(f"[Snap] Pinch thumb + middle finger then snap to vanish (message: {snap_messages[0]}).")
            print("[Snap] Show a peace sign (or press R) to rebuild. Press T to cycle excuse message.")

    is_real_capture = isinstance(capture, cv2.VideoCapture)
    skipped_decode = False
    last_static_send = 0.0

    def ensure_live_frame(cur_frame: np.ndarray) -> np.ndarray:
        nonlocal skipped_decode
        if not skipped_decode:
            return cur_frame
        ok, live = capture.retrieve()
        skipped_decode = False
        if not ok:
            return cur_frame
        return live if args.no_mirror else cv2.flip(live, 1)

    try:
        while True:
            if license_session is not None:
                license_session.ensure_valid()
            static_idle = (
                is_real_capture
                and background is not None
                and (
                    (state.phase == "frozen" and frozen_frame is not None)
                    or (
                        state.phase == "vanished"
                        and vanished_frame is not None
                        and not state.ghost_echo
                        and (state.gestures_paused or mode in ("normal", "naruto", "particles"))
                    )
                )
            )
            if static_idle:
                if not capture.grab():
                    raise RuntimeError("La webcam ha smesso di restituire immagini.")
                skipped_decode = True
                camera_frame = frozen_frame if state.phase == "frozen" else vanished_frame
            else:
                if skipped_decode:
                    capture.grab()
                    skipped_decode = False
                ok, camera_frame = capture.read()
                if not ok:
                    raise RuntimeError("La webcam ha smesso di restituire immagini.")

            skip_flip = (
                static_idle
                or (state.phase == "frozen" and frozen_frame is not None)
                or (
                    state.phase == "vanished"
                    and vanished_frame is not None
                    and (state.gestures_paused or mode in ("normal", "naruto", "particles"))
                )
            )
            if not args.no_mirror and not skip_flip:
                camera_frame = cv2.flip(camera_frame, 1)

            height, width = camera_frame.shape[:2]
            if not virtual_camera_initialized:
                virtual_camera = open_virtual_camera(args, width, height)
                virtual_camera_initialized = True
                if virtual_camera is not None:
                    resources.callback(virtual_camera.close)
            if not reused_bg_checked:
                reused_bg_checked = True
                if getattr(args, "reuse_bg", False) and background is None:
                    saved = load_saved_background(width, height)
                    if saved is not None:
                        background = saved
                        state.phase = "ready"
                        bg_ready_until = time.perf_counter() + 1.5
                        print("[Webcam] Loaded saved background (press SPACE to recapture).")
            if mode == "normal" and (dissolve_field is None or dissolve_field.shape != (height, width)):
                dissolve_field, sparkle_noise = make_dissolve_fields(height, width)
            now = time.perf_counter()

            elapsed_ms = int((now - started) * 1000)
            mp_image = None

            if state.ghost_echo and state.phase == "ready" and now - last_echo_sample >= 0.10:
                last_echo_sample = now
                echo_buffer.append(make_ghost_sample(camera_frame))
                if len(echo_buffer) > 25:
                    echo_buffer.pop(0)

            if (mode == "itachi" and background is not None
                    and not state.gestures_paused
                    and state.phase in ("ready", "vanished")
                    and now - state.last_gesture_check >= 0.09):
                state.last_gesture_check = now
                mp_image = to_gesture_mp_image(camera_frame)
                mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                last_mask, last_mask_at = mask, now
                touching = recognizer.recognize_pose(mp_image, elapsed_ms, mask)
                if args.gesture_debug and now - last_gesture_report >= 1.0:
                    print(f"[Itachi] hands={recognizer.last_hand_count}, chest={touching}")
                    last_gesture_report = now
                if itachi_gate.update(touching, now):
                    try:
                        itachi_effect = ItachiCrowEffect(camera_frame, mask)
                    except ValueError:
                        itachi_gate.reset()
                    else:
                        appearing = state.phase == "vanished"
                        state.phase = "itachi_appearing" if appearing else "itachi_disappearing"
                        state.vanish_started = now
                        vanished_frame = None
                        print("[Itachi] Crows reforming." if appearing
                              else "[Itachi] Dispersing into crows.")

            if (mode == "goku" and background is not None
                    and not state.gestures_paused
                    and state.phase in ("ready", "vanished")
                    and now - state.last_gesture_check >= 0.10):
                state.last_gesture_check = now
                mp_image = to_gesture_mp_image(camera_frame)
                pose = recognizer.recognize_pose(mp_image, elapsed_ms)
                if args.gesture_debug and now - last_gesture_report >= 1.0:
                    held = 0.0 if goku_gate.hold_started is None else now - goku_gate.hold_started
                    print(f"[Goku] faces={recognizer.last_face_count}, "
                          f"hands={recognizer.last_hand_count}, pose={pose}, "
                          f"held={held:.2f}/{goku_gate.hold_seconds:g}s")
                    last_gesture_report = now
                if goku_gate.update(pose, now):
                    action = "Reappearing" if state.phase == "vanished" else "Vanishing"
                    print(f"[Goku] {action}!")
                    goku_countdown_remaining = None
                    mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                    goku_effect = GokuTeleport(camera_frame, background, mask)
                    appearing = state.phase == "vanished"
                    state.phase = "goku_appearing" if appearing else "goku_vanishing"
                    state.vanish_started = time.perf_counter()
                    vanish_sound.play()
                elif pose and goku_gate.armed and goku_gate.hold_started is not None:
                    left = goku_gate.hold_seconds - (now - goku_gate.hold_started)
                    remaining = (max(.1,float(np.ceil(left*10)/10)) if goku_gate.hold_seconds < 1
                                 else max(1,int(np.ceil(left))))
                    if remaining != goku_countdown_remaining:
                        action = "Reappearing" if state.phase == "vanished" else "Vanishing"
                        print(f"[Goku] {action} in {remaining:g}...")
                        goku_countdown_remaining = remaining
                elif goku_gate.hold_started is None:
                    goku_countdown_remaining = None

            snap_interval = 0.22 if state.phase == "vanished" else 0.05
            if (mode == "snap" and background is not None
                    and not state.gestures_paused
                    and state.phase in ("ready", "vanished")
                    and now - state.last_gesture_check >= snap_interval):
                state.last_gesture_check = now
                mp_image = to_gesture_mp_image(camera_frame)
                if state.phase == "ready":
                    snapped, snap_primed, snap_pos = recognizer.detect_snap(mp_image, elapsed_ms, width, height)
                    if snapped:
                        mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                        msg = snap_messages[snap_msg_idx % len(snap_messages)]
                        snap_effect = SnapVoidEffect(
                            camera_frame, mask, snap_pos, message=msg,
                            on_assemble=chime_sound.play if chime_sound is not None else None,
                        )
                        if vanish_sound is not None:
                            vanish_sound.play()
                        state.phase = "snap_vanishing"
                        state.vanish_started = time.perf_counter()
                        vanished_frame = None
                else:
                    snap_primed = False
                    if recognizer.detect_peace_sign(mp_image, elapsed_ms):
                        mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                        snap_rebuild = SnapRebuildEffect(mask, width, height)
                        if chime_sound is not None:
                            chime_sound.play()
                        state.phase = "snap_rebuilding"
                        state.vanish_started = time.perf_counter()
                        vanished_frame = None

            if state.phase == "calibrating":
                elapsed = now - state.calibration_started
                remaining = max(0, int(np.ceil(calibration_seconds - elapsed)))
                if remaining != calibration_remaining:
                    print(f"[Webcam] Capturing background: {remaining}s.")
                    calibration_remaining = remaining
                if elapsed >= calibration_seconds - BACKGROUND_SAMPLE_SECONDS:
                    background_samples.append(camera_frame.copy())
                if elapsed >= calibration_seconds:
                    if background_samples:
                        stack = np.stack(background_samples[-18:], axis=0)
                        background = np.median(stack, axis=0).astype(np.uint8)
                    else:
                        background = camera_frame.copy()
                    background_samples.clear()
                    state.phase = "ready"
                    bg_ready_until = now + 1.8
                    save_background(background)
                    print("[Webcam] Background ready. You can step back into frame.")
                    if not state.preview_visible:
                        notify_desktop("VanishCam", "Empty room captured! You can step back in.")
                display = camera_frame

            elif background is None:
                state.phase = "calibrating"
                state.calibration_started = now
                display = camera_frame

            elif mode == "goku" and state.phase in ("goku_vanishing", "goku_appearing"):
                appearing = state.phase == "goku_appearing"
                age = time.perf_counter() - state.vanish_started
                display = goku_effect.render(background, age, appearing)
                if age >= TELEPORT_SECONDS:
                    state.phase = "ready" if appearing else "vanished"
                    vanished_frame = None if appearing else background.copy()

            elif mode == "itachi" and state.phase in ("itachi_disappearing", "itachi_appearing"):
                appearing = state.phase == "itachi_appearing"
                age = max(0.0, time.perf_counter() - state.vanish_started)
                display = itachi_effect.render(background, age, appearing)
                if age >= ITACHI_SECONDS:
                    state.phase = "ready" if appearing else "vanished"
                    vanished_frame = None if appearing else display
                    itachi_effect = None

            elif mode == "snap" and state.phase == "snap_vanishing":
                age = max(0.0, time.perf_counter() - state.vanish_started)
                display = snap_effect.render(background, age)
                if age >= SNAP_SECONDS:
                    state.phase = "vanished"
                    vanished_frame = background.copy()
                    snap_effect = None

            elif mode == "snap" and state.phase == "snap_rebuilding":
                age = max(0.0, time.perf_counter() - state.vanish_started)
                mp_image = to_gesture_mp_image(camera_frame)
                mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                display = snap_rebuild.render(camera_frame, background, mask, age)
                if age >= REBUILD_SECONDS:
                    state.phase = "ready"
                    snap_rebuild = None

            elif state.phase == "frozen":
                if frozen_frame is None:
                    frozen_frame = camera_frame.copy()
                display = frozen_frame

            elif state.phase == "vanished":
                if vanished_frame is None:
                    vanished_frame = background.copy()
                    if mode == "naruto" and log_anchor is not None:
                        overlay_log(vanished_frame, log_sprite, landed_log_anchor(log_anchor, height),
                                    cache=log_cache)
                if state.ghost_echo and echo_buffer and int(now * 0.45) % 2 == 0:
                    echo_idx = int((now * 10.0) % len(echo_buffer))
                    ghost = echo_buffer[echo_idx]
                    if ghost.shape[:2] != (height, width):
                        ghost = cv2.resize(ghost, (width, height), interpolation=cv2.INTER_LINEAR)
                    alpha = 0.24 + 0.08 * float(np.sin(now * 9.0))
                    display = cv2.addWeighted(ghost, alpha, vanished_frame, 1.0 - alpha, 0)
                else:
                    display = vanished_frame

            elif state.phase == "reappearing" and state.vanish_started is not None:
                progress = min(1.0, max(0.0, (time.perf_counter() - state.vanish_started) / REAPPEAR_SECONDS))
                ease = ease_in_out_cubic(progress)
                base_frame = vanished_frame if vanished_frame is not None else background
                display = cv2.addWeighted(camera_frame, ease, base_frame, 1.0 - ease, 0)
                if progress >= 1.0:
                    state.phase = "ready"
                    state.vanish_started = None
                    vanished_frame = None
                    log_anchor = None
                    last_mask = None
                    last_mask_at = float("-inf")
                    particle_effect = None

            else:
                mask = last_mask
                gesture_result = None
                if gesture_future is not None and gesture_future.done():
                    gesture_result = gesture_future.result()
                    gesture_future = None

                if (
                    state.phase == "ready"
                    and not state.gestures_paused
                    and mode not in ("goku", "itachi")
                    and gesture_future is None
                    and now - state.last_gesture_check >=
                    (0.08 if mode == "naruto" else GESTURE_INTERVAL_SECONDS)
                ):
                    state.last_gesture_check = now
                    mp_image = to_gesture_mp_image(camera_frame)
                    if gesture_executor is not None:
                        fn = recognizer.recognize_joined_hands if mode == "naruto" else recognize_gesture
                        fn_args = (mp_image, elapsed_ms) if mode == "naruto" else (recognizer, mp_image, elapsed_ms)
                        gesture_future = gesture_executor.submit(fn, *fn_args)
                    elif mode != "naruto":
                        gesture_result = recognize_gesture(recognizer, mp_image, elapsed_ms)
                    else:
                        gesture_result = recognizer.recognize_joined_hands(mp_image, elapsed_ms)

                if gesture_result is not None and state.phase == "ready" and not state.gestures_paused:
                    if mode != "naruto":
                        name, score = gesture_result
                        if args.gesture_debug and now - last_gesture_report >= 1.0:
                            print(
                                f"[Gesture] {name}, score={score:.2f}, "
                                f"crop={recognizer.preferred_crop or 'full'}, "
                                f"rotation={recognizer.preferred_rotation or 0}"
                            )
                            last_gesture_report = now
                        start_vanish_on_gesture(state, name, score, now)
                    else:
                        joined = gesture_result
                        if args.gesture_debug and now - last_gesture_report >= 1.0:
                            print(f"[Hands] detected={recognizer.last_hand_count}, "
                                  f"joined={joined}, view={recognizer.preferred_view or 'full'}")
                            last_gesture_report = now
                        if start_naruto_on_join(state, joined, time.perf_counter()):
                            vanish_sound.play()

                if state.phase in ("vanishing", "naruto_vanishing"):
                    # Normal tracks the silhouette at 20 Hz. Particles captures
                    # it once; Naruto needs it only while the person is visible.
                    needs_mask = (
                        (mode == "normal" and (mask is None or now - last_mask_at >= 0.05))
                        or (mode == "particles" and particle_effect is None)
                        or (mode == "naruto" and (log_anchor is None or now - state.vanish_started < 0.13))
                    )
                    if needs_mask:
                        if mp_image is None:
                            rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                        mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                        last_mask = mask
                        last_mask_at = now
                    if mode == "naruto" and log_anchor is None:
                        log_anchor = substitution_anchor(mask)

                if mode == "naruto" and state.phase == "naruto_vanishing":
                    age = max(0.04, time.perf_counter() - state.vanish_started)
                    display = render_substitution(
                        camera_frame, background, mask, log_sprite, log_anchor, age, log_cache
                    )
                    if age >= EFFECT_SECONDS:
                        state.phase = "vanished"
                        vanished_frame = display
                elif mode == "particles" and state.phase == "vanishing":
                    if particle_effect is None:
                        particle_effect = ParticleEffect(camera_frame, mask)
                    age = time.perf_counter() - state.vanish_started
                    display = particle_effect.render(background, age)
                    if age >= PARTICLE_SECONDS:
                        state.phase = "vanished"
                        vanished_frame = display
                elif state.phase == "ready":
                    display = camera_frame
                else:
                    progress = 0.0
                    if state.phase == "vanishing" and state.vanish_started is not None:
                        progress = min(
                            1.0, (time.perf_counter() - state.vanish_started) / VANISH_SECONDS
                        )
                        if progress >= 1.0:
                            state.phase = "vanished"
                    display = apply_dissolve(
                        camera_frame, background, mask, progress, dissolve_field, sparkle_noise
                    )
                    if state.phase == "vanished":
                        vanished_frame = display

            if license_session is not None:
                license_session.ensure_valid()
            if virtual_camera is not None and (not static_idle or now - last_static_send >= 0.070):
                send_virtual_frame(virtual_camera, display)
                last_static_send = now
            frame_size[0], frame_size[1] = width, height
            active_snap_msg = snap_messages[snap_msg_idx % len(snap_messages)] if mode == "snap" else ""
            ipc_sig = (mode, state.phase, state.gestures_paused, state.preview_visible, state.ghost_echo, active_snap_msg)
            if ipc_sig != last_ipc_signature or (now - last_ipc_write >= 2.0):
                write_ipc_state(True, mode, state, active_snap_msg)
                last_ipc_signature = ipc_sig
                last_ipc_write = now

            if state.preview_visible:
                preview_display = display
                if preview_hud:
                    if state.phase == "calibrating":
                        elapsed = now - state.calibration_started
                        if elapsed >= calibration_seconds - BACKGROUND_SAMPLE_SECONDS:
                            preview_display = draw_preview_banner(
                                display,
                                "CAPTURING EMPTY ROOM... STAY OUT",
                                "Hold still for a moment",
                                accent=(80, 220, 140),
                            )
                        else:
                            left = max(1, int(np.ceil(calibration_seconds - BACKGROUND_SAMPLE_SECONDS - elapsed)))
                            preview_display = draw_preview_banner(
                                display,
                                f"STEP OUT OF FRAME: {left}s",
                                "ENTER: capture now  |  B: load saved room  |  SPACE: restart",
                                accent=(0, 200, 255),
                            )
                    elif now < bg_ready_until:
                        preview_display = draw_preview_banner(
                            display,
                            "BACKGROUND READY! Step back in",
                            "Saved for --reuse-bg  |  SPACE to recapture",
                            accent=(80, 220, 140),
                        )
                    elif state.gestures_paused:
                        preview_display = draw_preview_banner(
                            display,
                            "GESTURES PAUSED",
                            "Press G to resume gesture detection",
                            accent=(120, 165, 255),
                        )
                    elif mode == "snap" and state.phase == "ready" and snap_primed:
                        preview_display = display.copy()
                        pulse = np.sin(now * 12.0)
                        r = 22 + int(5 * pulse)
                        cv2.circle(preview_display, snap_pos, r + 9, (0, 90, 160), 2)
                        cv2.circle(preview_display, snap_pos, r, (0, 200, 255), 2)
                        cv2.circle(preview_display, snap_pos, 6, (0, 255, 255), -1)
                        cv2.putText(preview_display, "READY TO SNAP!", (max(10, snap_pos[0] - 70), max(30, snap_pos[1] - 40)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
                    if state.phase != "calibrating":
                        preview_display = draw_preview_hud(preview_display, mode, state, active_snap_msg)
                cv2.imshow(WINDOW_NAME, preview_display)

            for ipc_cmd in poll_ipc_commands():
                if ipc_cmd.startswith("snap-text:"):
                    custom = ipc_cmd.split(":", 1)[1].strip()
                    if custom:
                        snap_messages = (custom, *VOID_MESSAGES)
                        snap_msg_idx = 0
                        last_ipc_signature = None
                        print(f"[Snap] Custom excuse set: {custom}")
                elif ipc_cmd.startswith("mode:"):
                    target_mode = ipc_cmd.split(":", 1)[1].strip().lower()
                    if target_mode in ALL_MODES:
                        pending_mode_switch.append(target_mode)
                elif ipc_cmd == "toggle-action":
                    pending_keys.append(ord("r") if state.phase in ("vanished", "frozen") else ord("v"))
                elif ipc_cmd == "preview":
                    pending_keys.append(ord("p"))
                elif ipc_cmd == "freeze":
                    pending_keys.append(ord("z"))
                elif ipc_cmd == "echo":
                    pending_keys.append(ord("e"))
                else:
                    cmd_map = {
                        "vanish": ord("v"),
                        "reappear": ord("r"),
                        "pause": ord("g"),
                        "recapture": ord(" "),
                        "load-bg": ord("b"),
                        "next-text": ord("t"),
                        "help": ord("h"),
                        "fullscreen": ord("f"),
                        "quit": ord("q"),
                    }
                    if ipc_cmd in cmd_map:
                        pending_keys.append(cmd_map[ipc_cmd])

            while pending_mode_switch:
                switch_mode(pending_mode_switch.pop(0))

            raw_key = (cv2.waitKey(1) & 0xFF) if state.preview_visible else 255
            if state.editing_text and raw_key not in (0, 255):
                if raw_key in (10, 13):
                    custom = state.edit_buffer.strip()
                    if custom:
                        snap_messages = (custom, *VOID_MESSAGES)
                        snap_msg_idx = 0
                        last_ipc_signature = None
                        print(f"[Snap] Custom excuse set: {custom}")
                    state.editing_text = False
                elif raw_key == 27:
                    state.editing_text = False
                elif raw_key in (8, 127):
                    state.edit_buffer = state.edit_buffer[:-1]
                elif 32 <= raw_key <= 126 and len(state.edit_buffer) < 22:
                    state.edit_buffer += chr(raw_key).upper()
                if virtual_camera is not None:
                    virtual_camera.sleep_until_next_frame()
                continue

            key = pending_keys.pop(0) if (raw_key in (0, 255) and pending_keys) else raw_key
            if key in (ord("q"), 27):
                break
            if key in (ord("1"), ord("2"), ord("3"), ord("4"), ord("5"), ord("6")) and preview_hud:
                hotkey_modes = ("snap", "naruto", "normal", "particles", "itachi", "goku")
                switch_mode(hotkey_modes[key - ord("1")])
            elif key == ord("p") and preview_hud:
                toggle_preview_window()
            elif key == ord("z") and preview_hud:
                if state.phase == "frozen":
                    state.phase = "ready"
                    frozen_frame = None
                    print("[Webcam] Unfroze camera.")
                elif state.phase == "ready":
                    frozen_frame = display.copy()
                    state.phase = "frozen"
                    print("[Webcam] Camera frozen (press Z or R to unfreeze).")
            elif key == ord("e") and preview_hud:
                state.ghost_echo = not state.ghost_echo
                if not state.ghost_echo:
                    echo_buffer.clear()
                print(f"[Webcam] Ghost Echo {'enabled' if state.ghost_echo else 'disabled'}.")
            elif key in (10, 13) and state.phase == "calibrating":
                state.calibration_started = min(
                    state.calibration_started,
                    now - (calibration_seconds - BACKGROUND_SAMPLE_SECONDS),
                )
                print("[Webcam] Capturing background now...")
            elif key == ord(" "):
                state.phase = "calibrating"
                state.calibration_started = now
                state.vanish_started = None
                log_anchor = None
                last_mask = None
                last_mask_at = float("-inf")
                vanished_frame = None
                frozen_frame = None
                particle_effect = None
                itachi_effect = None
                if itachi_gate is not None:
                    itachi_gate.reset()
                goku_effect = None
                if goku_gate is not None:
                    goku_gate.reset()
                    goku_countdown_remaining = None
                snap_effect = None
                snap_rebuild = None
                snap_primed = False
                if mode == "snap":
                    recognizer.reset()
                background_samples.clear()
                calibration_remaining = None
                print(f"[Webcam] Step out of frame for {calibration_seconds:g}s: capturing new background.")
                if not state.preview_visible:
                    notify_desktop("VanishCam", f"Step out of frame ({calibration_seconds:g}s) to capture empty room.")
            elif key == ord("t") and mode == "snap":
                snap_msg_idx = (snap_msg_idx + 1) % len(snap_messages)
                print(f"[Snap] Excuse message: {snap_messages[snap_msg_idx]}")
            elif key == ord("b"):
                saved = load_saved_background(width, height)
                if saved is not None:
                    background = saved
                    background_samples.clear()
                    state.phase = "ready"
                    state.vanish_started = None
                    vanished_frame = None
                    frozen_frame = None
                    bg_ready_until = now + 1.5
                    print("[Webcam] Loaded saved background.")
                else:
                    print("[Webcam] No matching saved background found (capture one with SPACE first).")
            elif key == ord("r"):
                if skipped_decode:
                    camera_frame = ensure_live_frame(camera_frame)
                elif skip_flip and not args.no_mirror:
                    camera_frame = cv2.flip(camera_frame, 1)
                if state.phase == "frozen":
                    state.phase = "ready"
                    frozen_frame = None
                    print("[Webcam] Unfroze camera.")
                elif background is not None and mode == "snap" and state.phase == "vanished":
                    mp_image = to_gesture_mp_image(camera_frame)
                    mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                    snap_rebuild = SnapRebuildEffect(mask, width, height)
                    if chime_sound is not None:
                        chime_sound.play()
                    state.phase = "snap_rebuilding"
                    state.vanish_started = time.perf_counter()
                    vanished_frame = None
                elif background is not None and mode == "itachi" and state.phase == "vanished":
                    mp_image = to_gesture_mp_image(camera_frame)
                    mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                    try:
                        itachi_effect = ItachiCrowEffect(camera_frame, mask)
                    except ValueError:
                        state.phase = "reappearing"
                        state.vanish_started = time.perf_counter()
                        vanished_frame = None
                    else:
                        state.phase = "itachi_appearing"
                        state.vanish_started = time.perf_counter()
                        vanished_frame = None
                elif background is not None and mode == "goku" and state.phase == "vanished" and preview_hud:
                    mp_image = to_gesture_mp_image(camera_frame)
                    mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                    if cv2.findNonZero((mask > 0.04).astype(np.uint8)) is None:
                        cv2.ellipse(mask, (width // 2, int(height * 0.58)), (width // 5, int(height * 0.35)), 0, 0, 360, 1.0, -1)
                    goku_effect = GokuTeleport(camera_frame, background, mask)
                    if goku_gate is not None:
                        goku_gate.reset()
                    goku_countdown_remaining = None
                    state.phase = "goku_appearing"
                    state.vanish_started = time.perf_counter()
                    if vanish_sound is not None:
                        vanish_sound.play()
                elif background is not None and mode not in ("goku", "itachi") and state.phase == "vanished":
                    if preview_hud:
                        state.phase = "reappearing"
                        state.vanish_started = time.perf_counter()
                        if mode == "naruto" and vanish_sound is not None:
                            vanish_sound.play()
                    else:
                        state.phase = "ready"
                        state.vanish_started = None
                        vanished_frame = None
                        log_anchor = None
                        last_mask = None
                        last_mask_at = float("-inf")
                        particle_effect = None
            elif key == ord("v") and background is not None and mode == "snap" and state.phase == "ready":
                mp_image = to_gesture_mp_image(camera_frame)
                mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                msg = snap_messages[snap_msg_idx % len(snap_messages)]
                snap_effect = SnapVoidEffect(
                    camera_frame, mask, (width // 2, height // 2), message=msg,
                    on_assemble=chime_sound.play if chime_sound is not None else None,
                )
                if vanish_sound is not None:
                    vanish_sound.play()
                state.phase = "snap_vanishing"
                state.vanish_started = time.perf_counter()
                vanished_frame = None
            elif key == ord("v") and background is not None and mode == "itachi" and state.phase == "ready":
                mp_image = to_gesture_mp_image(camera_frame)
                mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                try:
                    itachi_effect = ItachiCrowEffect(camera_frame, mask)
                except ValueError:
                    print("[Itachi] No person detected.")
                else:
                    state.phase = "itachi_disappearing"
                    state.vanish_started = time.perf_counter()
            elif key == ord("v") and background is not None and mode == "goku" and state.phase == "ready" and preview_hud:
                mp_image = to_gesture_mp_image(camera_frame)
                mask = person_mask(segmenter, mp_image, elapsed_ms, width, height)
                if cv2.findNonZero((mask > 0.04).astype(np.uint8)) is None:
                    cv2.ellipse(mask, (width // 2, int(height * 0.58)), (width // 5, int(height * 0.35)), 0, 0, 360, 1.0, -1)
                goku_effect = GokuTeleport(camera_frame, background, mask)
                if goku_gate is not None:
                    goku_gate.reset()
                goku_countdown_remaining = None
                state.phase = "goku_vanishing"
                state.vanish_started = time.perf_counter()
                if vanish_sound is not None:
                    vanish_sound.play()
            elif key == ord("v") and background is not None and mode not in ("goku", "itachi"):
                state.phase = "naruto_vanishing" if mode == "naruto" else "vanishing"
                state.vanish_started = time.perf_counter()
                if mode == "naruto":
                    vanish_sound.play()
                    log_anchor = None
                vanished_frame = None
                particle_effect = None
            elif key == ord("g"):
                state.gestures_paused = not state.gestures_paused
                if state.gestures_paused:
                    if itachi_gate is not None:
                        itachi_gate.reset()
                    if goku_gate is not None:
                        goku_gate.reset()
                        goku_countdown_remaining = None
                    print("[Webcam] Gesture recognition paused (press G to resume).")
                else:
                    print("[Webcam] Gesture recognition active.")
            elif key == ord("h"):
                state.show_help = not state.show_help
            elif key == ord("f"):
                state.fullscreen = not state.fullscreen
                set_fullscreen(state.fullscreen)
            if static_idle:
                time.sleep(0.045)
            elif virtual_camera is not None:
                virtual_camera.sleep_until_next_frame()
    finally:
        write_ipc_state(False)
        resources.close()

    return 0


def main() -> int:
    try:
        if any(flag in sys.argv[1:] for flag in ("--self-test", "--help", "-h")):
            return run()  # Model/resource checks only; never opens a camera.
        if not getattr(sys, "frozen", False):
            print("[Webcam] Local Python launch: skipping online license check.")
            return run()
        session = activate_license()
        if session is None:
            return 0
        with session:
            return run(session)
    except LicenseError as error:
        print(f"[License] {error}", file=sys.stderr)
        show_license_error(error)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"\n[Vanish Lab] ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
