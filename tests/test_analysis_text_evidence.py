import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    DEFAULT_WHISPER_MODEL_ID,
    DEFAULT_WHISPER_MODEL_REVISION,
    AnalysisSettings,
    TranscriptSegment,
)
from services.analysis.text_evidence import (
    FasterWhisperTranscriber,
    TextEvidenceService,
)


class _FakeFFmpegService:
    ffmpeg_path = Path("ffmpeg")


class _RecordingRunner:
    def __init__(self):
        self.commands = []

    def run(self, command, *, cancellation, check=True):
        cancellation.raise_if_cancelled()
        self.commands.append([str(item) for item in command])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


class _RecordingTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path, _settings, cancellation):
        cancellation.raise_if_cancelled()
        self.calls.append(Path(audio_path))
        return (
            [
                TranscriptSegment(
                    start_seconds=2.0,
                    end_seconds=3.0,
                    text="They are naked",
                    source="whisper",
                )
            ],
            [],
        )


class TextEvidenceServiceTests(unittest.TestCase):
    def make_mocked_service(self):
        runner = Mock()
        transcriber = Mock()
        transcriber.transcribe.return_value = ([], [])
        return TextEvidenceService(
            ffmpeg_service=_FakeFFmpegService(),
            process_runner=runner,
            transcriber=transcriber,
        ), runner, transcriber

    def test_no_audio_or_subtitles_is_not_applicable_without_extraction(self):
        service, runner, transcriber = self.make_mocked_service()
        progress = Mock()
        output = service.gather("synthetic.mp4", None, Path("synthetic-work"),
                                AnalysisSettings(), CancellationToken(), progress,
                                has_audio=False)
        runner.run.assert_not_called()
        transcriber.transcribe.assert_not_called()
        self.assertEqual(output.evidence, [])
        self.assertEqual(output.transcript_segments, [])
        self.assertEqual(len(output.warnings), 1)
        self.assertIn("not applicable", output.warnings[0])
        progress.assert_called_once_with(100, output.warnings[0])

    def test_existing_audio_is_extracted_and_transcribed(self):
        service, runner, transcriber = self.make_mocked_service()
        service.gather("synthetic.mp4", None, Path("synthetic-work"),
                       AnalysisSettings(), CancellationToken(), has_audio=True)
        runner.run.assert_called_once()
        command = runner.run.call_args.args[0]
        self.assertEqual(command[command.index("-map") + 1], "0:a:0")
        transcriber.transcribe.assert_called_once()

    def test_audio_extraction_failure_is_not_suppressed(self):
        service, runner, transcriber = self.make_mocked_service()
        runner.run.side_effect = RuntimeError("synthetic extraction failure")
        with self.assertRaisesRegex(RuntimeError, "extraction failure"):
            service.gather("synthetic.mp4", None, Path("synthetic-work"),
                           AnalysisSettings(), CancellationToken(), has_audio=True)
        transcriber.transcribe.assert_not_called()

    def test_transcription_failure_is_not_suppressed(self):
        service, runner, transcriber = self.make_mocked_service()
        transcriber.transcribe.side_effect = RuntimeError("synthetic transcription failure")
        with self.assertRaisesRegex(RuntimeError, "transcription failure"):
            service.gather("synthetic.mp4", None, Path("synthetic-work"),
                           AnalysisSettings(), CancellationToken(), has_audio=True)
        runner.run.assert_called_once()

    def test_silent_video_with_selected_embedded_subtitles_still_reads_them(self):
        service, runner, transcriber = self.make_mocked_service()
        with patch("services.analysis.text_evidence.load_subtitle_events",
                   return_value=[{"start_ms": 1000, "end_ms": 2000, "text": "naked"}]):
            output = service.gather("synthetic.mp4",
                {"source": "embedded", "stream_index": 2, "is_text_readable": True},
                Path("synthetic-work"), AnalysisSettings(), CancellationToken(), has_audio=False)
        command = runner.run.call_args.args[0]
        self.assertEqual(command[command.index("-map") + 1], "0:2")
        transcriber.transcribe.assert_not_called()
        self.assertEqual(len(output.evidence), 1)
        self.assertEqual(output.warnings, [])

    def test_empty_or_broken_selected_subtitle_without_audio_never_extracts_audio(self):
        for failure in (None, RuntimeError("synthetic unreadable subtitle")):
            with self.subTest(failure=failure):
                service, runner, transcriber = self.make_mocked_service()
                service._subtitle_segments = Mock(return_value=[], side_effect=failure)
                output = service.gather("synthetic.mp4", {"is_text_readable": True},
                    Path("synthetic-work"), AnalysisSettings(), CancellationToken(), has_audio=False)
                service._subtitle_segments.assert_called_once()
                runner.run.assert_not_called()
                transcriber.transcribe.assert_not_called()
                self.assertIn("not applicable", output.warnings[-1])
                self.assertEqual(len(output.warnings), 2 if failure else 1)

    def test_subtitle_cancellation_is_not_converted_to_not_applicable(self):
        service, runner, transcriber = self.make_mocked_service()
        service._subtitle_segments = Mock(side_effect=AnalysisCancelled("synthetic cancel"))
        with self.assertRaises(AnalysisCancelled):
            service.gather("synthetic.mp4", {"is_text_readable": True},
                Path("synthetic-work"), AnalysisSettings(), CancellationToken(), has_audio=False)
        runner.run.assert_not_called()
        transcriber.transcribe.assert_not_called()

    def test_selected_readable_external_subtitle_avoids_audio_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subtitle = root / "selected.srt"
            subtitle.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\nThey are naked\n",
                encoding="utf-8",
            )
            runner = _RecordingRunner()
            transcriber = _RecordingTranscriber()
            service = TextEvidenceService(
                ffmpeg_service=_FakeFFmpegService(),
                process_runner=runner,
                transcriber=transcriber,
            )

            output = service.gather(
                root / "video.mp4",
                {
                    "source": "external",
                    "file_path": str(subtitle),
                    "is_text_readable": True,
                },
                root,
                AnalysisSettings(use_gpu=False),
                CancellationToken(),
                has_audio=False,
            )

        self.assertEqual(runner.commands, [])
        self.assertEqual(transcriber.calls, [])
        self.assertEqual(len(output.transcript_segments), 1)
        self.assertEqual(len(output.evidence), 1)
        self.assertEqual(output.evidence[0].source, "subtitle")

    def test_broken_subtitle_falls_back_to_mono_16khz_audio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = _RecordingRunner()
            transcriber = _RecordingTranscriber()
            service = TextEvidenceService(
                ffmpeg_service=_FakeFFmpegService(),
                process_runner=runner,
                transcriber=transcriber,
            )

            output = service.gather(
                root / "video.mp4",
                {
                    "source": "external",
                    "file_path": str(root / "missing.srt"),
                    "is_text_readable": True,
                },
                root,
                AnalysisSettings(use_gpu=False),
                CancellationToken(),
            )

        command = runner.commands[0]
        self.assertIn("-ac", command)
        self.assertEqual(command[command.index("-ac") + 1], "1")
        self.assertIn("-ar", command)
        self.assertEqual(command[command.index("-ar") + 1], "16000")
        self.assertEqual(transcriber.calls[0].name, "speech_audio.wav")
        self.assertTrue(any("audio fallback" in warning for warning in output.warnings))

    def test_faster_whisper_enables_timestamped_silero_vad(self):
        constructor_calls = []
        transcribe_calls = []

        class FakeWhisperModel:
            def __init__(self, model_id, **kwargs):
                constructor_calls.append((model_id, kwargs))

            def transcribe(self, audio_path, **kwargs):
                transcribe_calls.append((audio_path, kwargs))
                segment = types.SimpleNamespace(start=0.5, end=1.5, text="intimate scene")
                return iter([segment]), types.SimpleNamespace()

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(sys.modules, {"faster_whisper": fake_module}),
            patch.dict(
                os.environ,
                {"NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD": "0"},
            ),
        ):
            segments, warnings = FasterWhisperTranscriber(temp_dir).transcribe(
                Path(temp_dir) / "audio.wav",
                AnalysisSettings(use_gpu=False),
                CancellationToken(),
            )

        self.assertEqual(constructor_calls[0][0], DEFAULT_WHISPER_MODEL_ID)
        self.assertTrue(constructor_calls[0][1]["local_files_only"])
        self.assertEqual(
            constructor_calls[0][1]["revision"], DEFAULT_WHISPER_MODEL_REVISION
        )
        self.assertIs(constructor_calls[0][1]["use_auth_token"], False)
        self.assertTrue(transcribe_calls[0][1]["vad_filter"])
        self.assertEqual(
            transcribe_calls[0][1]["vad_parameters"],
            {"min_silence_duration_ms": 500},
        )
        self.assertEqual(len(segments), 1)
        self.assertTrue(any("CPU" in warning for warning in warnings))

    def test_faster_whisper_retries_cpu_when_cuda_fails_during_iteration(self):
        constructor_calls = []

        class FakeWhisperModel:
            def __init__(self, model_id, **kwargs):
                self.device = kwargs["device"]
                constructor_calls.append((model_id, kwargs))

            def transcribe(self, _audio_path, **_kwargs):
                if self.device == "cuda":
                    def broken_segments():
                        raise RuntimeError("cublas64_12.dll could not be loaded")
                        yield None

                    return broken_segments(), types.SimpleNamespace()
                segment = types.SimpleNamespace(start=1.0, end=2.0, text="intimate")
                return iter([segment]), types.SimpleNamespace()

        fake_whisper = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        fake_ctranslate = types.SimpleNamespace(get_cuda_device_count=lambda: 1)
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(
                sys.modules,
                {
                    "faster_whisper": fake_whisper,
                    "ctranslate2": fake_ctranslate,
                },
            ),
        ):
            segments, warnings = FasterWhisperTranscriber(temp_dir).transcribe(
                Path(temp_dir) / "audio.wav",
                AnalysisSettings(use_gpu=True),
                CancellationToken(),
            )

        self.assertEqual(
            [kwargs["device"] for _model_id, kwargs in constructor_calls],
            ["cuda", "cpu"],
        )
        self.assertTrue(
            all(
                model_id == DEFAULT_WHISPER_MODEL_ID
                and kwargs["revision"] == DEFAULT_WHISPER_MODEL_REVISION
                for model_id, kwargs in constructor_calls
            )
        )
        self.assertEqual(len(segments), 1)
        self.assertTrue(any("CUDA Whisper inference failed" in warning for warning in warnings))

    def test_faster_whisper_cpu_initialization_retry_keeps_pinned_snapshot(self):
        constructor_calls = []

        class FakeWhisperModel:
            def __init__(self, model_id, **kwargs):
                constructor_calls.append((model_id, kwargs))
                if kwargs["device"] == "cuda":
                    raise RuntimeError("CUDA initialization failed")

            def transcribe(self, _audio_path, **_kwargs):
                segment = types.SimpleNamespace(start=1.0, end=2.0, text="intimate")
                return iter([segment]), types.SimpleNamespace()

        fake_whisper = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        fake_ctranslate = types.SimpleNamespace(get_cuda_device_count=lambda: 1)
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(
                sys.modules,
                {
                    "faster_whisper": fake_whisper,
                    "ctranslate2": fake_ctranslate,
                },
            ),
        ):
            segments, _warnings = FasterWhisperTranscriber(temp_dir).transcribe(
                Path(temp_dir) / "audio.wav",
                AnalysisSettings(use_gpu=True),
                CancellationToken(),
            )

        self.assertEqual(
            [kwargs["device"] for _model_id, kwargs in constructor_calls],
            ["cuda", "cpu"],
        )
        self.assertTrue(
            all(
                model_id == DEFAULT_WHISPER_MODEL_ID
                and kwargs["revision"] == DEFAULT_WHISPER_MODEL_REVISION
                for model_id, kwargs in constructor_calls
            )
        )
        self.assertEqual(len(segments), 1)


if __name__ == "__main__":
    unittest.main()
