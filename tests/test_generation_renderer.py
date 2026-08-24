import json
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from generation_policy import (
    GenerationRequest,
    LayerCandidate,
    plan_with_alternate_key,
    plan_with_manual_pitch,
    plan_with_normalization,
    plan_with_source_key_rank,
    select_generation,
)
from generation_renderer import (
    BungeePCMBackend,
    FFmpegMP3Encoder,
    GenerationRenderError,
    LAYER_NORMALIZATION_MAX_BOOST_DB,
    RenderRequest,
    TimelinePlan,
    _peak_normalize,
    render_generation,
    rerender_alternate_key,
    rerender_selected_layer,
)


def layer(
    identity,
    category,
    *,
    loop,
    key="A minor",
    key_sensitive=True,
):
    return LayerCandidate(
        identity=identity,
        path=Path(f"/synthetic/{identity}.wav"),
        source_loop_id=loop,
        source_bpm=120,
        source_key=key,
        bars=8,
        manual_label=category,
        key_sensitive=key_sensitive,
    )


class SyntheticBackend:
    def __init__(self, audio_by_identity):
        self.audio_by_identity = audio_by_identity
        self.calls = []

    def transform(self, selection, *, target_bpm, sample_rate, channels):
        self.calls.append(
            {
                "identity": selection.candidate.identity,
                "semitones": selection.semitones,
                "speed_ratio": selection.speed_ratio,
                "target_bpm": target_bpm,
                "sample_rate": sample_rate,
                "channels": channels,
            }
        )
        return self.audio_by_identity[selection.candidate.identity]


class CapturingEncoder:
    def __init__(self):
        self.calls = []

    def encode(self, destination, audio, *, sample_rate, bitrate_bps):
        destination.write_bytes(b"synthetic mp3")
        self.calls.append(
            {
                "destination": destination,
                "audio": np.asarray(audio, dtype=np.float32).copy(),
                "sample_rate": sample_rate,
                "bitrate_bps": bitrate_bps,
            }
        )

    def audio_for(self, destination):
        return next(
            item["audio"]
            for item in self.calls
            if item["destination"] == destination
        )


class ExternalPayloadTests(unittest.TestCase):
    def test_missing_ffmpeg_reports_a_clear_generate_error(self):
        backend = BungeePCMBackend()
        with patch("engine.find_ffmpeg", return_value=None), self.assertRaisesRegex(
            GenerationRenderError,
            "FFmpeg was not found",
        ):
            backend._executables()


class TimelineTests(unittest.TestCase):
    def test_four_four_timeline_is_rounded_once_to_exact_frames(self):
        timeline = TimelinePlan.create(
            sample_rate=48_000,
            target_bpm=137,
            loop_bars=8,
            gap_bars=2,
        )
        self.assertEqual(timeline.loop_frames, round(48_000 * 60 * 4 * 8 / 137))
        self.assertEqual(timeline.gap_frames, round(48_000 * 60 * 4 * 2 / 137))
        self.assertEqual(
            timeline.presentation_frames(3),
            timeline.loop_frames * 4 + timeline.gap_frames * 3,
        )

    def test_layer_peak_normalization_has_safe_boost_and_silence_guards(self):
        quiet = np.full((100, 1), 0.01, dtype=np.float32)
        normalized, source_peak, rendered_peak, gain_db = _peak_normalize(quiet)
        self.assertAlmostEqual(source_peak, 0.01, places=6)
        self.assertAlmostEqual(gain_db, LAYER_NORMALIZATION_MAX_BOOST_DB, places=5)
        self.assertAlmostEqual(
            rendered_peak,
            0.01 * 10 ** (LAYER_NORMALIZATION_MAX_BOOST_DB / 20.0),
            places=6,
        )
        self.assertTrue(np.isfinite(normalized).all())

        near_silence = np.full((100, 1), 0.0005, dtype=np.float32)
        unchanged, _source, _rendered, silence_gain_db = _peak_normalize(
            near_silence
        )
        self.assertEqual(silence_gain_db, 0.0)
        self.assertTrue(np.array_equal(unchanged, near_silence))


class FinalEncoderTests(unittest.TestCase):
    def test_ffmpeg_encoder_requests_libmp3lame_cbr_320_once(self):
        audio = np.zeros((480, 2), dtype=np.float32)
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "output.mp3"
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(list(command))
                Path(command[-1]).write_bytes(b"encoded mp3")
                return SimpleNamespace(returncode=0, stderr=b"")

            with patch("generation_renderer.subprocess.run", side_effect=fake_run):
                FFmpegMP3Encoder(ffmpeg="/fake/ffmpeg").encode(
                    destination,
                    audio,
                    sample_rate=48_000,
                    bitrate_bps=320_000,
                )

            self.assertTrue(destination.is_file())
            self.assertEqual(len(commands), 1)
            command = commands[0]
            self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
            self.assertEqual(command[command.index("-b:a") + 1], "320k")
            self.assertEqual(command[command.index("-write_xing") + 1], "1")
            self.assertFalse(any(path.suffix == ".wav" for path in Path(root).rglob("*")))


class RendererTests(unittest.TestCase):
    def _plan(self):
        layers = [
            layer("bass", "Bass", loop="loop-a"),
            layer(
                "perc",
                "Percussion",
                loop="loop-b",
                key=None,
                key_sensitive=False,
            ),
        ]
        request = GenerationRequest(
            ("Bass", "Percussion"),
            120,
            "D minor",
            bars=8,
            seed=7,
        )
        return select_generation(layers, request)

    def test_renderer_writes_one_sequence_master_stems_and_manifest(self):
        plan = self._plan()
        sample_rate = 100
        loop_frames = 1_600
        # The first non-zero sample deliberately occurs after source time zero.
        bass = np.zeros((loop_frames + 50, 2), dtype=np.float32)
        bass[25:, :] = 0.8
        percussion = np.full((loop_frames - 100, 1), 0.8, dtype=np.float32)
        backend = SyntheticBackend({"bass": bass, "perc": percussion})
        encoder = CapturingEncoder()

        with tempfile.TemporaryDirectory() as root:
            result = render_generation(
                RenderRequest(
                    plan=plan,
                    output_root=Path(root),
                    generation_name="Test Loop",
                    sample_rate=sample_rate,
                    channels=2,
                    headroom_db=-6.0,
                ),
                backend=backend,
                encoder=encoder,
            )

            self.assertTrue(result.master_path.is_file())
            self.assertEqual(result.master_path.suffix, ".mp3")
            self.assertEqual(len(result.stem_paths), 2)
            self.assertTrue(all(path.suffix == ".mp3" for path in result.stem_paths))
            self.assertTrue(result.presentation_path.is_file())
            self.assertEqual(result.presentation_path.suffix, ".mp3")
            self.assertEqual(result.presentation_path, result.master_path)
            self.assertTrue(result.manifest_path.is_file())
            self.assertFalse(
                any(
                    path.suffix.casefold() == ".wav"
                    for path in result.output_directory.rglob("*")
                    if path.is_file()
                )
            )
            # One complete sequence master plus one encode per individual stem.
            self.assertEqual(len(encoder.calls), 3)
            self.assertTrue(
                all(item["bitrate_bps"] == 320_000 for item in encoder.calls)
            )
            self.assertEqual(
                len({item["destination"] for item in encoder.calls}),
                3,
            )

            rendered_bass = encoder.audio_for(result.stem_paths[0])
            self.assertTrue(np.all(rendered_bass[:25] == 0))
            self.assertGreater(np.max(np.abs(rendered_bass[25:])), 0)
            self.assertEqual(rendered_bass.shape[0], loop_frames)

            rendered_percussion = encoder.audio_for(result.stem_paths[1])
            self.assertEqual(rendered_percussion.shape, (loop_frames, 2))
            self.assertTrue(np.all(rendered_percussion[-100:] == 0))

            master = encoder.audio_for(result.master_path)
            self.assertEqual(
                master.shape[0],
                result.timeline.presentation_frames(2),
            )
            self.assertEqual(
                result.timeline.presentation_frames(2),
                loop_frames * 3 + 400 * 2,
            )
            # Headroom applies to the mixed-loop segment. Individual stem
            # segments retain their own peak-protected level.
            self.assertLessEqual(
                float(np.max(np.abs(master[:loop_frames]))),
                10 ** (-6 / 20) + 1e-4,
            )
            self.assertLess(result.master_gain_db, 0)
            self.assertTrue(np.all(master[loop_frames : loop_frames + 400] == 0))
            self.assertTrue(
                np.array_equal(
                    master[loop_frames + 400 : loop_frames * 2 + 400],
                    rendered_bass,
                )
            )

            presentation = encoder.audio_for(result.presentation_path)
            self.assertTrue(np.array_equal(presentation, master))
            self.assertTrue(result.master_waveform_peaks)
            self.assertTrue(result.presentation_waveform_peaks)
            self.assertEqual(
                result.master_waveform_peaks,
                result.presentation_waveform_peaks,
            )
            self.assertTrue(all(item.waveform_peaks for item in result.stem_results))

            payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 3)
            self.assertEqual(payload["render"]["format"], "MP3")
            self.assertEqual(payload["render"]["codec"], "libmp3lame")
            self.assertEqual(payload["render"]["bitrate_bps"], 320_000)
            self.assertEqual(payload["render"]["bitrate_mode"], "CBR")
            self.assertTrue(payload["render"]["no_intermediate_lossy_encode"])
            self.assertEqual(payload["render"]["lossy_encodes_per_output"], 1)
            self.assertEqual(
                payload["render"]["timeline_frame_domain"],
                "pre-encode PCM",
            )
            self.assertEqual(
                payload["render"]["primary_master_content"],
                "loop_mix_then_gap_and_each_stem",
            )
            self.assertFalse(payload["render"]["loop_only_output"])
            self.assertTrue(payload["render"]["presentation_is_master"])
            self.assertTrue(payload["outputs"]["master"].endswith(".mp3"))
            self.assertTrue(payload["outputs"]["presentation"].endswith(".mp3"))
            self.assertEqual(
                payload["outputs"]["presentation"],
                payload["outputs"]["master"],
            )
            self.assertTrue(
                all(path.endswith(".mp3") for path in payload["outputs"]["stems"])
            )
            self.assertEqual(
                payload["render"]["presentation_order"],
                [
                    "master",
                    "silence_2_bars",
                    "stem_1",
                    "silence_2_bars",
                    "stem_2",
                ],
            )
            self.assertEqual(payload["target"]["key"], "D minor")
            self.assertEqual(len(payload["layers"]), 2)

        self.assertEqual(len(backend.calls), 2)
        percussion_call = next(item for item in backend.calls if item["identity"] == "perc")
        self.assertEqual(percussion_call["semitones"], 0)

    def test_existing_run_directory_is_never_overwritten(self):
        plan = self._plan()
        frames = 1_600
        backend = SyntheticBackend(
            {
                "bass": np.zeros((frames, 2), dtype=np.float32),
                "perc": np.zeros((frames, 2), dtype=np.float32),
            }
        )
        with tempfile.TemporaryDirectory() as root:
            encoder = CapturingEncoder()
            first = render_generation(
                RenderRequest(plan, Path(root), sample_rate=100),
                backend=backend,
                encoder=encoder,
            )
            second = render_generation(
                RenderRequest(plan, Path(root), sample_rate=100),
                backend=backend,
                encoder=encoder,
            )
            self.assertNotEqual(first.output_directory, second.output_directory)
            self.assertTrue(first.master_path.is_file())
            self.assertTrue(second.master_path.is_file())

    def test_alternate_key_renders_one_stem_and_rebuilds_only_the_master(self):
        bass = replace(
            layer("bass", "Bass", loop="loop-a", key="A minor"),
            scanned_key="A",
            scanned_mode="minor",
            alternate_scanned_key="D",
            alternate_scanned_mode="minor",
        )
        percussion = layer(
            "perc",
            "Percussion",
            loop="loop-b",
            key=None,
            key_sensitive=False,
        )
        plan = select_generation(
            [bass, percussion],
            GenerationRequest(("Bass", "Percussion"), 120, "D minor", seed=4),
        )
        frames = 1_600
        backend = SyntheticBackend(
            {
                "bass": np.full((frames, 2), 0.1, dtype=np.float32),
                "perc": np.full((frames, 2), 0.2, dtype=np.float32),
            }
        )
        encoder = CapturingEncoder()
        with tempfile.TemporaryDirectory() as root:
            request = RenderRequest(plan, Path(root), sample_rate=100)
            initial = render_generation(
                request,
                backend=backend,
                encoder=encoder,
            )
            untouched_path = initial.stem_results[1].output_path
            untouched_stat = untouched_path.stat()
            alternate_plan = plan_with_alternate_key(
                plan,
                slot_index=0,
                identity="bass",
            )
            updated = rerender_alternate_key(
                replace(request, plan=alternate_plan),
                initial,
                slot_index=0,
                backend=backend,
                encoder=encoder,
            )

            self.assertEqual(len(backend.calls), 3)
            self.assertEqual(len(encoder.calls), 5)
            self.assertEqual(untouched_path.stat(), untouched_stat)
            self.assertEqual(updated.stem_results[0].selection.source_key_rank, 2)
            self.assertEqual(updated.stem_results[0].selection.semitones, 0)
            payload = json.loads(updated.manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["layers"][0]["alternate_key_used"])
            self.assertEqual(payload["layers"][0]["source_key_rank"], 2)

            original_plan = plan_with_source_key_rank(
                alternate_plan,
                slot_index=0,
                identity="bass",
                source_key_rank=1,
            )
            restored = rerender_selected_layer(
                replace(request, plan=original_plan),
                updated,
                slot_index=0,
                backend=backend,
                encoder=encoder,
            )
            self.assertEqual(len(backend.calls), 4)
            self.assertEqual(len(encoder.calls), 7)
            self.assertEqual(untouched_path.stat(), untouched_stat)
            self.assertEqual(restored.stem_results[0].selection.source_key_rank, 1)
            self.assertEqual(restored.stem_results[0].selection.semitones, 5)
            payload = json.loads(restored.manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["layers"][0]["alternate_key_used"])
            self.assertEqual(payload["layers"][0]["source_key_rank"], 1)
            self.assertEqual(payload["layers"][0]["source_key"], "A")

    def test_pitch_and_normalization_rerender_only_the_targeted_card(self):
        plan = select_generation(
            [layer("lead", "Lead", loop="loop-a", key="A minor")],
            GenerationRequest(("Lead",), 120, "A minor", seed=5),
        )
        frames = 1_600
        backend = SyntheticBackend(
            {"lead": np.full((frames, 2), 0.2, dtype=np.float32)}
        )
        encoder = CapturingEncoder()
        with tempfile.TemporaryDirectory() as root:
            request = RenderRequest(plan, Path(root), sample_rate=100)
            initial = render_generation(request, backend=backend, encoder=encoder)

            pitched_plan = plan_with_manual_pitch(
                plan,
                slot_index=0,
                identity="lead",
                semitones=12,
            )
            pitched = rerender_selected_layer(
                replace(request, plan=pitched_plan),
                initial,
                slot_index=0,
                backend=backend,
                encoder=encoder,
            )
            self.assertEqual(backend.calls[-1]["semitones"], 12)
            self.assertEqual(
                pitched.stem_results[0].selection.manual_pitch_semitones,
                12,
            )

            normalized_plan = plan_with_normalization(
                pitched_plan,
                slot_index=0,
                identity="lead",
                enabled=True,
            )
            normalized = rerender_selected_layer(
                replace(request, plan=normalized_plan),
                pitched,
                slot_index=0,
                backend=backend,
                encoder=encoder,
            )
            self.assertAlmostEqual(
                float(np.max(np.abs(normalized.stem_audio_pcm[0]))),
                10 ** (-1.0 / 20.0),
                places=5,
            )
            self.assertTrue(
                normalized.stem_results[0].selection.normalization_enabled
            )
            self.assertLessEqual(normalized.master_peak, 10 ** (-1.0 / 20.0) + 1e-6)

            original_plan = plan_with_normalization(
                normalized_plan,
                slot_index=0,
                identity="lead",
                enabled=False,
            )
            original_plan = plan_with_manual_pitch(
                original_plan,
                slot_index=0,
                identity="lead",
                semitones=0,
            )
            restored = rerender_selected_layer(
                replace(request, plan=original_plan),
                normalized,
                slot_index=0,
                backend=backend,
                encoder=encoder,
            )
            self.assertAlmostEqual(
                float(np.max(np.abs(restored.stem_audio_pcm[0]))),
                0.2,
                places=6,
            )
            self.assertEqual(restored.stem_results[0].selection.semitones, 0)
            self.assertFalse(
                restored.stem_results[0].selection.normalization_enabled
            )
            payload = json.loads(restored.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["layers"][0]["manual_pitch_semitones"], 0)
            self.assertFalse(payload["layers"][0]["normalization_enabled"])


if __name__ == "__main__":
    unittest.main()
