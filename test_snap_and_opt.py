import argparse
import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from local_app import goku_effect, hud, ipc, virtual_bg
from local_app import vanish_cam as app
from local_app.itachi_effect import ItachiPoseRecognizer
from local_app.snap_effect import P1_DISSOLVE_END, P2_VORTEX_END, P3_ASSEMBLE_END, P4_HOLD_END, SNAP_SECONDS, SnapRebuildEffect, SnapVoidEffect


def _lm_hand(cx: float = 0.5, cy: float = 0.5):
    return [SimpleNamespace(x=cx + (i % 3) * 0.005, y=cy + (i // 3) * 0.005) for i in range(21)]


class SnapVectorizedTests(unittest.TestCase):
    def test_snap_void_and_rebuild_render_all_phases(self):
        h, w = 90, 160
        frame = np.full((h, w, 3), 180, dtype=np.uint8)
        bg = np.full((h, w, 3), 20, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.float32)
        mask[20:70, 50:110] = 1.0

        assembled = []
        effect = SnapVoidEffect(frame, mask, (80, 45), message="BRB...", on_assemble=lambda: assembled.append(True))
        self.assertGreater(effect.particles.count, 0)

        for age in (0.2, P1_DISSOLVE_END + 0.1, P2_VORTEX_END + 0.2, P3_ASSEMBLE_END + 0.2, P4_HOLD_END + 0.5, SNAP_SECONDS + 0.1):
            out = effect.render(bg, age)
            self.assertEqual(out.shape, (h, w, 3))
            self.assertEqual(out.dtype, np.uint8)
        self.assertEqual(assembled, [True])

        rebuild = SnapRebuildEffect(mask, w, h)
        out_r = rebuild.render(frame, bg, mask, 0.5)
        self.assertEqual(out_r.shape, (h, w, 3))
        self.assertEqual(out_r.dtype, np.uint8)


class ItachiLazyMaskTests(unittest.TestCase):
    def test_skips_mask_when_fewer_than_two_hands(self):
        detector = Mock()
        detector.detect_for_video.return_value = SimpleNamespace(hand_landmarks=[_lm_hand()])
        fallback = Mock()
        fallback.detect.return_value = SimpleNamespace(hand_landmarks=[])
        rec = ItachiPoseRecognizer(detector, fallback)

        mask_calls = 0

        def lazy_mask():
            nonlocal mask_calls
            mask_calls += 1
            return np.ones((90, 160), dtype=np.float32)

        img = app.mp.Image(image_format=app.mp.ImageFormat.SRGB, data=np.zeros((90, 160, 3), dtype=np.uint8))
        self.assertFalse(rec.recognize_pose(img, 10, lazy_mask))
        self.assertEqual(mask_calls, 0)
        self.assertEqual(rec.detect_hands_candidates(img, 100), [])


class IpcHudAndBlendTests(unittest.TestCase):
    def test_alpha_composite_matches_float_reference(self):
        rng = np.random.default_rng(42)
        p = rng.integers(0, 255, (48, 80, 3), dtype=np.uint8)
        b = rng.integers(0, 255, (48, 80, 3), dtype=np.uint8)
        alpha = rng.random((48, 80), dtype=np.float32)
        fast = app.alpha_composite(p, b, alpha)
        ref = (p.astype(np.float32) * alpha[:, :, None] + b.astype(np.float32) * (1.0 - alpha[:, :, None])).astype(np.uint8)
        self.assertEqual(fast.dtype, np.uint8)
        self.assertLessEqual(int(np.max(np.abs(fast.astype(int) - ref.astype(int)))), 2)

    def test_ipc_roundtrip_and_shared_hud_modes(self):
        with TemporaryDirectory() as tmp:
            st_file = Path(tmp) / "state.json"
            cmd_file = Path(tmp) / "cmd.txt"
            state = app.AppState(phase="ready", blur_bg=True)
            ipc.write_ipc_state(True, "snap", state, snap_message="AFK", state_file=st_file)
            loaded = json.loads(st_file.read_text(encoding="utf-8"))
            self.assertTrue(loaded["running"])
            self.assertEqual(loaded["mode"], "snap")
            self.assertTrue(loaded["blur_bg"])
            self.assertEqual(loaded["snap_message"], "AFK")

            cmd_file.write_text("vanish\nblur\n", encoding="utf-8")
            self.assertEqual(ipc.poll_ipc_commands(cmd_file), ["vanish", "blur"])
            self.assertFalse(cmd_file.exists())

        buttons = hud._hud_menu_buttons(640, 480, "snap", app.AppState())
        mode_cmds = [b[0] for b in buttons if b[0].startswith("mode:")]
        self.assertEqual(mode_cmds, ["mode:snap", "mode:naruto", "mode:normal", "mode:particles", "mode:itachi", "mode:goku"])


class AsyncAllModesTests(unittest.TestCase):
    def test_async_gestures_runs_cleanly_in_goku_and_snap(self):
        for mode in ("goku", "snap"):
            frame = np.full((60, 80, 3), 90, dtype=np.uint8)
            capture = Mock(read=Mock(return_value=(True, frame)))
            recognizer = Mock()
            recognizer.last_face_count = 0
            recognizer.last_hand_count = 0
            recognizer.recognize_pose.return_value = False
            recognizer.detect_snap.return_value = (False, False, (0, 0))
            segmenter = Mock()
            args = argparse.Namespace(
                camera=0, width=80, height=60, fps=30.0, fullscreen=False,
                no_mirror=True, virtual_camera=False, virtual_backend=None,
                virtual_device=None, gesture_debug=False, mode=mode,
                async_gestures=True, no_preview=True, reuse_bg=False,
                bg_delay=0.6, preview_hud=False, goku_delay=0.2, snap_text="BRB",
            )
            clock = [0.0]

            def tick():
                clock[0] += 0.3
                return clock[0]

            cmd_seq = [[], [], ["quit"]]
            with ExitStack() as stack:
                stack.enter_context(patch.object(app, "download_models"))
                stack.enter_context(patch.object(app, "open_camera", return_value=capture))
                stack.enter_context(patch.object(app, "create_tasks", return_value=(segmenter, recognizer)))
                stack.enter_context(patch.object(app, "open_virtual_camera", return_value=None))
                stack.enter_context(patch.object(app, "VanishSound", return_value=Mock()))
                stack.enter_context(patch.object(app, "save_background"))
                stack.enter_context(patch.object(app, "write_ipc_state"))
                stack.enter_context(patch.object(app, "poll_ipc_commands", side_effect=lambda: cmd_seq.pop(0) if cmd_seq else ["quit"]))
                stack.enter_context(patch.object(app.time, "perf_counter", side_effect=tick))
                for name in ("namedWindow", "resizeWindow", "destroyAllWindows", "imshow"):
                    stack.enter_context(patch.object(app.cv2, name))
                with ExitStack() as res:
                    self.assertEqual(app.run_camera(args, res, mode), 0)


class VirtualBackgroundTests(unittest.TestCase):
    def test_presets_and_custom_center_crop_image(self):
        for preset in virtual_bg.PRESET_IDS:
            img, label = virtual_bg.load_virtual_background(preset, 160, 90)
            self.assertIsNotNone(img)
            self.assertEqual(label, preset)
            self.assertEqual(img.shape, (90, 160, 3))
            blurred = virtual_bg.make_blurred_background(img)
            self.assertEqual(blurred.shape, (90, 160, 3))

        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "portrait.png"
            raw = np.full((300, 100, 3), (10, 200, 30), dtype=np.uint8)
            app.cv2.imwrite(str(p), raw)
            cropped, label = virtual_bg.load_virtual_background(str(p), 160, 90)
            self.assertIsNotNone(cropped)
            self.assertEqual(cropped.shape, (90, 160, 3))
            self.assertEqual(label, str(p))

        off_img, off_label = virtual_bg.load_virtual_background("off", 160, 90)
        self.assertIsNone(off_img)
        self.assertEqual(off_label, "")

    def test_run_camera_bg_image_skips_calibration_and_switches_live(self):
        frame = np.full((60, 80, 3), 240, dtype=np.uint8)
        capture = Mock(read=Mock(return_value=(True, frame)))
        recognizer = Mock()
        recognizer.last_hand_count = 0
        recognizer.detect_snap.return_value = (False, False, (0, 0))
        segmenter = Mock()
        fake_virtual = Mock(width=80, height=60)
        args = argparse.Namespace(
            camera=0, width=80, height=60, fps=30.0, fullscreen=False,
            no_mirror=True, virtual_camera=True, virtual_backend=None,
            virtual_device=None, gesture_debug=False, mode="snap",
            async_gestures=False, no_preview=True, reuse_bg=False,
            bg_delay=7.0, preview_hud=False, snap_text="BRB", bg_image="studio-dark",
        )
        clock = [0.0]

        def tick():
            clock[0] += 0.1
            return clock[0]

        cmd_seq = [[], ["bg-image:cyber-grid"], ["quit"]]
        with ExitStack() as stack:
            stack.enter_context(patch.object(app, "download_models"))
            stack.enter_context(patch.object(app, "open_camera", return_value=capture))
            stack.enter_context(patch.object(app, "create_tasks", return_value=(segmenter, recognizer)))
            stack.enter_context(patch.object(app, "open_virtual_camera", return_value=fake_virtual))
            stack.enter_context(patch.object(app, "VanishSound", return_value=Mock()))
            stack.enter_context(patch.object(app, "person_mask", return_value=np.zeros((60, 80), dtype=np.float32)))
            stack.enter_context(patch.object(app, "write_ipc_state"))
            stack.enter_context(patch.object(app, "poll_ipc_commands", side_effect=lambda: cmd_seq.pop(0) if cmd_seq else ["quit"]))
            stack.enter_context(patch.object(app.time, "perf_counter", side_effect=tick))
            for name in ("namedWindow", "resizeWindow", "destroyAllWindows", "imshow"):
                stack.enter_context(patch.object(app.cv2, name))
            with ExitStack() as res:
                self.assertEqual(app.run_camera(args, res, "snap"), 0)

        sent = [call.args[0] for call in fake_virtual.send.call_args_list]
        self.assertGreaterEqual(len(sent), 3)
        studio_expected, _ = virtual_bg.load_virtual_background("studio-dark", 80, 60)
        cyber_expected, _ = virtual_bg.load_virtual_background("cyber-grid", 80, 60)
        self.assertLessEqual(int(np.max(np.abs(sent[0].astype(int) - studio_expected.astype(int)))), 2)
        self.assertLessEqual(int(np.max(np.abs(sent[-1].astype(int) - cyber_expected.astype(int)))), 2)


class GokuReappearTests(unittest.TestCase):
    def test_fallback_cooldown_fits_within_tracking_grace(self):
        gate = goku_effect.GokuGestureGate(hold_seconds=1.0)
        self.assertLess(0.20, goku_effect.TRACKING_GRACE_SECONDS)
        # Alternating fallback-hit (every 300ms) and main-detector-miss must keep the hold alive.
        triggered = False
        for step in range(9):
            now = step * 0.15
            pose = (step % 2 == 0)
            if gate.update(pose, now):
                triggered = True
        self.assertTrue(triggered)

    def test_goku_vanished_reappears_via_gesture_under_real_capture_idle(self):
        live_frame = np.full((60, 80, 3), 210, dtype=np.uint8)
        person = np.zeros((60, 80), dtype=np.float32)
        person[15:50, 25:55] = 1.0

        capture = Mock(spec=app.cv2.VideoCapture)
        capture.isOpened.return_value = True
        capture.grab.return_value = True
        capture.retrieve.side_effect = lambda: (True, live_frame.copy())
        capture.read.side_effect = lambda: (True, live_frame.copy())
        segmenter = SimpleNamespace(close=lambda: None)
        recognizer = SimpleNamespace(
            last_face_count=1,
            last_hand_count=1,
            recognize_pose=Mock(side_effect=lambda *args, **kwargs: state_box["pose"]),
            close=lambda: None,
        )
        fake_virtual = Mock()
        fake_virtual.width = 80
        fake_virtual.height = 60
        state_box = {"pose": False}
        phases_seen = []
        clock = [0.0]

        def fake_perf():
            return clock[0]

        real_sleep = app.time.sleep

        def fake_sleep(dt):
            clock[0] += dt
            real_sleep(0.002)

        def fake_virtual_sleep():
            clock[0] += 0.035
            real_sleep(0.002)

        fake_virtual.sleep_until_next_frame = fake_virtual_sleep

        def fake_write_ipc(running, mode="snap", state=None, *args, **kwargs):
            if running and state is not None:
                phases_seen.append(state.phase)

        cmd_counter = [0]

        def poll_cmds():
            cmd_counter[0] += 1
            if cmd_counter[0] == 1:
                return ["vanish"]
            if "ready" in phases_seen[1:] and len([p for p in phases_seen if p == "ready"]) > 3:
                return ["quit"]
            if len(phases_seen) > 120:
                return ["quit"]
            if "vanished" in phases_seen:
                state_box["pose"] = True
            return []

        args = argparse.Namespace(
            camera=0, width=80, height=60, fps=30, no_mirror=True, no_virtual_camera=False,
            virtual_camera=True, virtual_backend="v4l2loopback", virtual_device="/dev/video0",
            async_gestures=True, no_preview=True, reuse_bg=False, goku_delay=0.35,
            fullscreen=False, bg_delay=7.0, preview_hud=True, snap_text="BRB",
            bg_image="studio-dark", gesture_debug=False,
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(app, "download_models"))
            stack.enter_context(patch.object(app, "open_camera", return_value=capture))
            stack.enter_context(patch.object(app, "create_tasks", return_value=(segmenter, recognizer)))
            stack.enter_context(patch.object(app, "open_virtual_camera", return_value=fake_virtual))
            stack.enter_context(patch.object(app, "VanishSound", return_value=Mock()))
            stack.enter_context(patch.object(app, "person_mask", return_value=person))
            stack.enter_context(patch.object(app, "write_ipc_state", side_effect=fake_write_ipc))
            stack.enter_context(patch.object(app, "poll_ipc_commands", side_effect=poll_cmds))
            stack.enter_context(patch.object(app.time, "perf_counter", side_effect=fake_perf))
            stack.enter_context(patch.object(app.time, "sleep", side_effect=fake_sleep))
            for name in ("namedWindow", "resizeWindow", "destroyAllWindows", "imshow"):
                stack.enter_context(patch.object(app.cv2, name))
            with ExitStack() as res:
                self.assertEqual(app.run_camera(args, res, "goku"), 0)

        self.assertIn("vanished", phases_seen)
        self.assertIn("goku_appearing", phases_seen)
        vanished_idx = phases_seen.index("vanished")
        self.assertIn("ready", phases_seen[vanished_idx + 1:])


class MirrorToggleTests(unittest.TestCase):
    def test_live_mirror_toggle_flips_live_frames_and_updates_ipc(self):
        raw_frame = np.zeros((60, 80, 3), dtype=np.uint8)
        raw_frame[:, :40] = 220  # Left half bright in raw camera space

        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.side_effect = lambda: (True, raw_frame.copy())
        segmenter = SimpleNamespace(close=lambda: None)
        recognizer = SimpleNamespace(detect_snap=Mock(return_value=(False, False, (0, 0))), close=lambda: None)
        fake_virtual = Mock()
        fake_virtual.width = 80
        fake_virtual.height = 60

        args = argparse.Namespace(
            camera=0, width=80, height=60, fps=30, no_mirror=False, no_virtual_camera=False,
            virtual_camera=True, virtual_backend="v4l2loopback", virtual_device="/dev/video0",
            async_gestures=False, no_preview=True, reuse_bg=False, fullscreen=False,
            bg_delay=0.6, preview_hud=True, snap_text="BRB", bg_image=None,
        )
        clock = [0.0]

        def tick():
            clock[0] += 0.35
            return clock[0]

        # Wait until calibration completes (frames 0..1), verify mirrored frame (right bright),
        # send mirror:off -> verify unmirrored frame (left bright), then vanish -> mirror:on flips room.
        ipc_states = []
        cmd_seq = [[], [], ["mirror:off"], [], ["quit"]]
        with ExitStack() as stack:
            stack.enter_context(patch.object(app, "download_models"))
            stack.enter_context(patch.object(app, "open_camera", return_value=capture))
            stack.enter_context(patch.object(app, "create_tasks", return_value=(segmenter, recognizer)))
            stack.enter_context(patch.object(app, "open_virtual_camera", return_value=fake_virtual))
            stack.enter_context(patch.object(app, "VanishSound", return_value=Mock()))
            stack.enter_context(patch.object(app, "save_background"))
            stack.enter_context(patch.object(app, "write_ipc_state", side_effect=lambda running, mode="", state=None, *a, **kw: ipc_states.append(bool(getattr(state, "mirror", True))) if running else None))
            stack.enter_context(patch.object(app, "poll_ipc_commands", side_effect=lambda: cmd_seq.pop(0) if cmd_seq else ["quit"]))
            stack.enter_context(patch.object(app.time, "perf_counter", side_effect=tick))
            for name in ("namedWindow", "resizeWindow", "destroyAllWindows", "imshow"):
                stack.enter_context(patch.object(app.cv2, name))
            with ExitStack() as res:
                self.assertEqual(app.run_camera(args, res, "snap"), 0)

        sent = [call.args[0] for call in fake_virtual.send.call_args_list]
        self.assertGreaterEqual(len(sent), 4)
        # Initial mirrored frames: right half bright (> 150), left half dark (< 50)
        self.assertGreater(int(sent[2][30, 60, 0]), 150)
        self.assertLess(int(sent[2][30, 20, 0]), 50)
        # After mirror:off: raw orientation (left half bright, right half dark)
        self.assertGreater(int(sent[-1][30, 20, 0]), 150)
        self.assertLess(int(sent[-1][30, 60, 0]), 50)
        self.assertIn(True, ipc_states)
        self.assertIn(False, ipc_states)


if __name__ == "__main__":
    unittest.main()
