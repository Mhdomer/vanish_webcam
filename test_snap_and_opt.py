import argparse
import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from local_app import hud, ipc
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


if __name__ == "__main__":
    unittest.main()
