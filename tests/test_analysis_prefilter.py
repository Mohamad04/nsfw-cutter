import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    AnalysisMode,
    AnalysisSettings,
    CandidateWindow,
    PrefilterFrameScore,
    SampledFrame,
)
from services.analysis.prefilter import (
    LocalNSFWPrefilter,
    _resolve_nsfw_label_index,
    group_candidate_windows,
)
from services.analysis.providers.prefilter_base import (
    PrefilterProviderUnavailableError,
)


def _frame(timestamp: float, path: Path | None = None) -> SampledFrame:
    return SampledFrame(
        timestamp_seconds=timestamp,
        path=path or Path(f"frame-{timestamp}.jpg"),
        source="interval",
    )


class CandidateWindowGroupingTests(unittest.TestCase):
    def test_visual_and_text_candidates_merge_with_padding_deterministically(self):
        settings = AnalysisSettings(
            use_gpu=False,
            candidate_gap_seconds=5.0,
            candidate_padding_seconds=2.0,
            max_candidate_window_seconds=30.0,
        )
        scores = [
            PrefilterFrameScore(frame=_frame(10.0), nsfw_probability=0.2),
            PrefilterFrameScore(frame=_frame(14.0), nsfw_probability=0.8),
            PrefilterFrameScore(frame=_frame(50.0), nsfw_probability=0.1),
        ]
        text_window = CandidateWindow(
            window_id="source-text-id-is-not-reused",
            start_seconds=15.0,
            end_seconds=18.0,
            peak_probability=0.0,
            evidence_timestamps=[16.0],
            trigger="text",
        )

        forward = group_candidate_windows(
            scores,
            duration_seconds=100.0,
            settings=settings,
            text_windows=[text_window],
        )
        reversed_input = group_candidate_windows(
            list(reversed(scores)),
            duration_seconds=100.0,
            settings=settings,
            text_windows=[text_window],
        )

        self.assertEqual(
            [window.model_dump() for window in forward],
            [window.model_dump() for window in reversed_input],
        )
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0].window_id, "candidate-00000")
        self.assertEqual(forward[0].start_seconds, 8.0)
        self.assertEqual(forward[0].end_seconds, 20.0)
        self.assertEqual(forward[0].peak_probability, 0.8)
        self.assertEqual(forward[0].evidence_timestamps, [10.0, 14.0, 16.0])
        self.assertEqual(forward[0].trigger, "visual_and_text")

    def test_conservative_score_is_included_below_threshold(self):
        settings = AnalysisSettings(
            use_gpu=False,
            candidate_padding_seconds=0.0,
        )
        scores = [
            PrefilterFrameScore(
                frame=_frame(20.0),
                nsfw_probability=0.0,
                conservatively_included=True,
            )
        ]

        windows = group_candidate_windows(
            scores,
            duration_seconds=60.0,
            settings=settings,
        )

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].start_seconds, 20.0)
        self.assertGreater(windows[0].end_seconds, windows[0].start_seconds)
        self.assertEqual(windows[0].trigger, "visual")

    def test_long_text_candidate_is_split_into_bounded_windows(self):
        settings = AnalysisSettings(
            use_gpu=False,
            candidate_gap_seconds=0.0,
            candidate_padding_seconds=0.0,
            max_candidate_window_seconds=10.0,
        )
        text_window = CandidateWindow(
            window_id="text",
            start_seconds=0.0,
            end_seconds=25.0,
            peak_probability=0.0,
            trigger="text",
        )

        windows = group_candidate_windows(
            [],
            duration_seconds=25.0,
            settings=settings,
            text_windows=[text_window],
        )

        self.assertEqual(
            [(window.start_seconds, window.end_seconds) for window in windows],
            [(0.0, 10.0), (10.0, 20.0), (20.0, 25.0)],
        )
        self.assertEqual(
            [window.window_id for window in windows],
            ["candidate-00000", "candidate-00001", "candidate-00002"],
        )
        self.assertTrue(all(window.trigger == "text" for window in windows))

    def test_fast_mode_uses_the_strong_threshold(self):
        settings = AnalysisSettings(
            analysis_mode=AnalysisMode.FAST,
            use_gpu=False,
            candidate_padding_seconds=1.0,
        )

        windows = group_candidate_windows(
            [PrefilterFrameScore(frame=_frame(5.0), nsfw_probability=0.44)],
            duration_seconds=10.0,
            settings=settings,
        )

        self.assertEqual(windows, [])

    def test_invalid_duration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive duration"):
            group_candidate_windows(
                [],
                duration_seconds=float("nan"),
                settings=AnalysisSettings(use_gpu=False),
            )


class _FakeProcessor:
    def __init__(self, torch_module, callback=None):
        self._torch = torch_module
        self._callback = callback
        self.calls = 0

    def __call__(self, *, images, return_tensors):
        self.calls += 1
        if self._callback is not None:
            self._callback(self.calls)
        if return_tensors != "pt":
            raise AssertionError("prefilter must request PyTorch tensors")
        return {"pixel_values": self._torch.zeros((len(images), 1))}


class _FakeModel:
    def __init__(self, torch_module, responses):
        self._torch = torch_module
        self._responses = list(responses)
        self.calls = 0
        self.to_calls = []

    def __call__(self, **_inputs):
        response = self._responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(logits=self._torch.tensor(response, dtype=self._torch.float32))

    def to(self, *args, **kwargs):
        self.to_calls.append((args, kwargs))
        return self


class _LoadedTestPrefilter(LocalNSFWPrefilter):
    def __init__(self, root, torch_module, processor, model):
        super().__init__(root)
        self.test_torch = torch_module
        self.test_processor = processor
        self.test_model = model

    def _ensure_loaded(self, settings, cancellation):
        cancellation.raise_if_cancelled()
        self._processor = self.test_processor
        self._model = self.test_model
        self._torch = self.test_torch
        self._device = "cpu"
        self._precision = "float32"
        self._nsfw_label_index = 1
        self._loaded_key = (
            settings.prefilter_model_id,
            settings.prefilter_model_revision,
            settings.use_gpu,
        )
        self._diagnostics = self._diagnostics.model_copy(
            update={"device_mode": "cpu", "precision": "float32"}
        )


class LocalPrefilterInferenceTests(unittest.TestCase):
    def setUp(self):
        import torch

        self.torch = torch
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = []
        for index in range(3):
            path = self.root / f"frame-{index}.jpg"
            Image.new("RGB", (8, 8), color=(index, index, index)).save(path)
            self.paths.append(path)
        self.frames = [
            _frame(float(index), path)
            for index, path in enumerate(self.paths)
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_failed_chunk_is_scored_conservatively_and_reported(self):
        processor = _FakeProcessor(self.torch)
        model = _FakeModel(
            self.torch,
            responses=[
                [[0.0, 2.0], [2.0, 0.0]],
                RuntimeError("synthetic inference failure"),
            ],
        )
        provider = _LoadedTestPrefilter(self.root, self.torch, processor, model)
        progress = []

        scores = provider.score_frames(
            self.frames,
            AnalysisSettings(use_gpu=False, prefilter_batch_size=2),
            CancellationToken(),
            lambda percent, message: progress.append((percent, message)),
        )

        self.assertEqual([score.frame for score in scores], self.frames)
        self.assertGreater(scores[0].nsfw_probability, 0.8)
        self.assertLess(scores[1].nsfw_probability, 0.2)
        self.assertEqual(scores[2].nsfw_probability, 1.0)
        self.assertTrue(scores[2].conservatively_included)
        self.assertEqual(provider.diagnostics.frame_count, 3)
        self.assertEqual(provider.diagnostics.successful_frame_count, 2)
        self.assertEqual(provider.diagnostics.failed_chunk_count, 1)
        self.assertEqual(provider.diagnostics.conservatively_included_count, 1)
        self.assertEqual(progress[-1][0], 100)
        self.assertIn("1 frames were included conservatively", provider.warnings[0])
        self.assertNotIn(str(self.root), provider.warnings[0])

    def test_cancellation_is_observed_between_chunks(self):
        token = CancellationToken()
        processor = _FakeProcessor(
            self.torch,
            callback=lambda call: token.cancel() if call == 1 else None,
        )
        model = _FakeModel(
            self.torch,
            responses=[[[0.0, 1.0], [0.0, 1.0]], [[0.0, 1.0]]],
        )
        provider = _LoadedTestPrefilter(self.root, self.torch, processor, model)

        with self.assertRaises(AnalysisCancelled):
            provider.score_frames(
                self.frames,
                AnalysisSettings(use_gpu=False, prefilter_batch_size=2),
                token,
            )

        self.assertEqual(model.calls, 1)

    def test_release_is_idempotent_and_drops_loaded_references(self):
        processor = _FakeProcessor(self.torch)
        model = _FakeModel(self.torch, responses=[])
        provider = _LoadedTestPrefilter(self.root, self.torch, processor, model)
        provider._ensure_loaded(AnalysisSettings(use_gpu=False), CancellationToken())

        provider.release()
        provider.release()

        self.assertIsNone(provider._model)
        self.assertIsNone(provider._processor)
        self.assertIsNone(provider._loaded_key)
        self.assertEqual(model.to_calls[0][0], ("cpu",))


class LocalPrefilterReadinessTests(unittest.TestCase):
    def test_offline_readiness_requires_both_files_at_the_pinned_revision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            weights_path = root / "model.safetensors"
            config_path.write_text("{}", encoding="utf-8")
            weights_path.write_bytes(b"safe placeholder")
            calls = []

            def lookup(model_id, filename, **kwargs):
                calls.append((model_id, filename, kwargs))
                return str(config_path if filename == "config.json" else weights_path)

            provider = LocalNSFWPrefilter(root)
            settings = AnalysisSettings(use_gpu=False)
            with (
                patch("services.analysis.prefilter.find_spec", return_value=object()),
                patch(
                    "huggingface_hub.try_to_load_from_cache",
                    side_effect=lookup,
                ),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD", None)
                provider.check_ready(settings, CancellationToken())

        self.assertEqual(
            [filename for _model_id, filename, _kwargs in calls],
            ["config.json", "model.safetensors"],
        )
        self.assertTrue(
            all(
                kwargs["revision"] == settings.prefilter_model_revision
                for _model_id, _filename, kwargs in calls
            )
        )
        self.assertTrue(
            all(
                model_id == settings.prefilter_model_id
                for model_id, _filename, _kwargs in calls
            )
        )

    def test_missing_offline_weights_produce_actionable_diagnostic(self):
        provider = LocalNSFWPrefilter("model-cache")
        with (
            patch("services.analysis.prefilter.find_spec", return_value=object()),
            patch("huggingface_hub.try_to_load_from_cache", return_value=None),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD", None)
            with self.assertRaisesRegex(
                PrefilterProviderUnavailableError,
                "NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD=1",
            ):
                provider.check_ready(
                    AnalysisSettings(use_gpu=False),
                    CancellationToken(),
                )

    def test_explicit_download_opt_in_skips_offline_cache_requirement(self):
        provider = LocalNSFWPrefilter("model-cache")
        with (
            patch("services.analysis.prefilter.find_spec", return_value=object()),
            patch("huggingface_hub.try_to_load_from_cache") as cache_lookup,
            patch.dict(
                os.environ,
                {"NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD": "1"},
            ),
        ):
            provider.check_ready(
                AnalysisSettings(use_gpu=False),
                CancellationToken(),
            )

        cache_lookup.assert_not_called()

    def test_nsfw_label_index_is_resolved_from_metadata_not_hard_coded(self):
        config = SimpleNamespace(
            id2label={0: "SFW", 1: "Something Else", 2: "NsFw"},
            label2id={},
        )

        self.assertEqual(_resolve_nsfw_label_index(config), 2)

        with self.assertRaisesRegex(PrefilterProviderUnavailableError, "NSFW"):
            _resolve_nsfw_label_index(
                SimpleNamespace(id2label={0: "safe", 1: "unsafe"}, label2id={})
            )


if __name__ == "__main__":
    unittest.main()
