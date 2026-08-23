import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import AnalysisSettings, TranscriptSegment
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

        self.assertEqual(constructor_calls[0][0], "small")
        self.assertTrue(constructor_calls[0][1]["local_files_only"])
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
            def __init__(self, _model_id, **kwargs):
                self.device = kwargs["device"]
                constructor_calls.append(kwargs)

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

        self.assertEqual([call["device"] for call in constructor_calls], ["cuda", "cpu"])
        self.assertEqual(len(segments), 1)
        self.assertTrue(any("CUDA Whisper inference failed" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
