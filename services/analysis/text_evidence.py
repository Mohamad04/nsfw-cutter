from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

from core.paths import get_model_cache_dir
from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    AnalysisSettings,
    NSFWCategory,
    TextEvidence,
    TextEvidenceOutput,
    TranscriptSegment,
)
from services.analysis.process import CancellableProcessRunner
from services.infrastructure.ffmpeg.runner import FFmpegService
from services.subtitles.subtitle_loader_service import load_subtitle_events

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, str], None]

_TEXT_PATTERNS: tuple[tuple[NSFWCategory, float, re.Pattern], ...] = (
    (
        NSFWCategory.SEXUAL_ACTIVITY,
        0.65,
        re.compile(
            r"\b(?:having sex|make love|oral sex|sexual intercourse|climax|orgasm)\b",
            re.IGNORECASE,
        ),
    ),
    (
        NSFWCategory.NUDITY,
        0.56,
        re.compile(
            r"\b(?:naked|nude|undress(?:ed|ing)?|take (?:your|my|his|her) clothes off)\b",
            re.IGNORECASE,
        ),
    ),
    (
        NSFWCategory.SEXUAL_CONTEXT,
        0.44,
        re.compile(
            r"\b(?:bedroom|seduc(?:e|ing|tion)|intimate|sexual|strip(?:ping)?)\b",
            re.IGNORECASE,
        ),
    ),
)


class FasterWhisperTranscriber:
    """Timestamped transcription using faster-whisper's built-in Silero VAD."""

    def __init__(self, model_cache_dir: str | Path | None = None) -> None:
        self.model_cache_dir = (
            Path(model_cache_dir) if model_cache_dir is not None else get_model_cache_dir()
        )

    def transcribe(
        self,
        audio_path: str | Path,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> tuple[list[TranscriptSegment], list[str]]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is unavailable. Install requirements-ai.txt to enable "
                "audio transcription."
            ) from exc

        allow_download = _environment_flag("NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD")
        device, compute_type, warnings = _whisper_device(settings.use_gpu)
        model_kwargs = {
            "device": device,
            "compute_type": compute_type,
            "download_root": str(self.model_cache_dir),
            "local_files_only": not allow_download,
        }
        try:
            model = WhisperModel(settings.whisper_model_id, **model_kwargs)
        except Exception as exc:
            if device != "cuda":
                raise _whisper_load_error(settings.whisper_model_id, allow_download, exc) from exc
            warnings.append("CUDA Whisper initialization failed; using slow CPU fallback.")
            model_kwargs.update(device="cpu", compute_type="int8")
            try:
                model = WhisperModel(settings.whisper_model_id, **model_kwargs)
            except Exception as cpu_exc:
                raise _whisper_load_error(
                    settings.whisper_model_id,
                    allow_download,
                    cpu_exc,
                ) from cpu_exc

        try:
            return _transcribe_with_model(model, audio_path, cancellation), warnings
        except AnalysisCancelled:
            raise
        except Exception as exc:
            if device != "cuda":
                raise _whisper_load_error(settings.whisper_model_id, allow_download, exc) from exc

            # CTranslate2 can defer CUDA library loading until iteration begins. Retry
            # the whole transcription on CPU so a missing cuBLAS/cuDNN DLL does not
            # discard text evidence on otherwise CPU-capable machines.
            warnings.append(
                "CUDA Whisper inference failed; using the slow CPU fallback."
            )
            try:
                cpu_model = WhisperModel(
                    settings.whisper_model_id,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(self.model_cache_dir),
                    local_files_only=not allow_download,
                )
                return _transcribe_with_model(cpu_model, audio_path, cancellation), warnings
            except AnalysisCancelled:
                raise
            except Exception as cpu_exc:
                raise _whisper_load_error(
                    settings.whisper_model_id,
                    allow_download,
                    cpu_exc,
                ) from cpu_exc


def _transcribe_with_model(
    model,
    audio_path: str | Path,
    cancellation: CancellationToken,
) -> list[TranscriptSegment]:
    cancellation.raise_if_cancelled()
    segments, _info = model.transcribe(
        str(audio_path),
        beam_size=1,
        word_timestamps=False,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    results = []
    for segment in segments:
        cancellation.raise_if_cancelled()
        text = str(segment.text or "").strip()
        if not text or float(segment.end) <= float(segment.start):
            continue
        results.append(
            TranscriptSegment(
                start_seconds=max(0.0, float(segment.start)),
                end_seconds=float(segment.end),
                text=text,
                source="whisper",
            )
        )
    return results


class TextEvidenceService:
    def __init__(
        self,
        *,
        ffmpeg_service: FFmpegService | None = None,
        process_runner: CancellableProcessRunner | None = None,
        transcriber: FasterWhisperTranscriber | None = None,
    ) -> None:
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.process_runner = process_runner or CancellableProcessRunner()
        self.transcriber = transcriber or FasterWhisperTranscriber()

    def gather(
        self,
        video_path: str | Path,
        selected_subtitle: dict | None,
        workspace: str | Path,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
        progress_callback: ProgressCallback | None = None,
    ) -> TextEvidenceOutput:
        warnings: list[str] = []
        transcript_segments: list[TranscriptSegment] = []
        cancellation.raise_if_cancelled()
        if _is_readable_subtitle(selected_subtitle):
            if progress_callback is not None:
                progress_callback(10, "Reading selected subtitle track")
            try:
                transcript_segments = self._subtitle_segments(
                    video_path,
                    selected_subtitle or {},
                    workspace,
                    cancellation,
                )
            except Exception as exc:  # noqa: BLE001 - a broken subtitle must fall back to audio
                logger.warning("Selected subtitle could not be read; falling back to audio: %s", exc)
                warnings.append("Selected subtitle could not be read; audio fallback was used.")

        if not transcript_segments:
            if progress_callback is not None:
                progress_callback(10, "Extracting speech audio")
            audio_path = self._extract_audio(video_path, workspace, cancellation)
            if progress_callback is not None:
                progress_callback(50, "Transcribing speech with Silero VAD")
            transcribed, transcription_warnings = self.transcriber.transcribe(
                audio_path,
                settings,
                cancellation,
            )
            transcript_segments = transcribed
            warnings.extend(transcription_warnings)

        cancellation.raise_if_cancelled()
        evidence = classify_text_evidence(
            transcript_segments,
            settings.text_confidence_threshold,
        )
        if progress_callback is not None:
            progress_callback(100, "Text and audio evidence ready")
        return TextEvidenceOutput(
            transcript_segments=transcript_segments,
            evidence=evidence,
            warnings=warnings,
        )

    def _subtitle_segments(
        self,
        video_path: str | Path,
        selected_subtitle: dict,
        workspace: str | Path,
        cancellation: CancellationToken,
    ) -> list[TranscriptSegment]:
        source = selected_subtitle.get("source")
        if source == "external":
            subtitle_path = selected_subtitle.get("file_path") or selected_subtitle.get("path")
            if not subtitle_path:
                raise RuntimeError("Selected external subtitle has no readable path")
        elif source == "embedded":
            stream_index = selected_subtitle.get("stream_index", selected_subtitle.get("index"))
            if stream_index is None:
                raise RuntimeError("Selected embedded subtitle has no stream index")
            subtitle_path = Path(workspace) / "selected_subtitle.srt"
            command = [
                self.ffmpeg_service.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                video_path,
                "-map",
                f"0:{int(stream_index)}",
                "-c:s",
                "srt",
                subtitle_path,
            ]
            self.process_runner.run(command, cancellation=cancellation)
        else:
            raise RuntimeError("Selected subtitle source is unsupported")

        cancellation.raise_if_cancelled()
        cues = load_subtitle_events(subtitle_path)
        return [
            TranscriptSegment(
                start_seconds=cue["start_ms"] / 1000.0,
                end_seconds=cue["end_ms"] / 1000.0,
                text=cue["text"],
                source="subtitle",
            )
            for cue in cues
        ]

    def _extract_audio(
        self,
        video_path: str | Path,
        workspace: str | Path,
        cancellation: CancellationToken,
    ) -> Path:
        audio_path = Path(workspace) / "speech_audio.wav"
        command = [
            self.ffmpeg_service.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            video_path,
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            audio_path,
        ]
        self.process_runner.run(command, cancellation=cancellation)
        return audio_path


def classify_text_evidence(
    segments: list[TranscriptSegment],
    minimum_confidence: float = 0.35,
) -> list[TextEvidence]:
    evidence = []
    for segment in segments:
        best_match: tuple[NSFWCategory, float] | None = None
        for category, confidence, pattern in _TEXT_PATTERNS:
            if pattern.search(segment.text) and (
                best_match is None or confidence > best_match[1]
            ):
                best_match = (category, confidence)
        if best_match is None or best_match[1] < minimum_confidence:
            continue
        evidence.append(
            TextEvidence(
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                category=best_match[0],
                confidence=best_match[1],
                excerpt=_short_excerpt(segment.text),
                source=segment.source,
            )
        )
    return evidence


def _is_readable_subtitle(candidate: dict | None) -> bool:
    return bool(candidate and candidate.get("is_text_readable"))


def _short_excerpt(value: str, limit: int = 200) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _environment_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _whisper_device(use_gpu: bool) -> tuple[str, str, list[str]]:
    if not use_gpu:
        return "cpu", "int8", ["Whisper is using the slow CPU backend."]
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16", []
    except (ImportError, RuntimeError):
        pass
    return "cpu", "int8", ["CUDA is unavailable; Whisper is using the slow CPU fallback."]


def _whisper_load_error(model_id: str, allow_download: bool, error: Exception) -> RuntimeError:
    if allow_download:
        return RuntimeError(
            f"Unable to load faster-whisper model '{model_id}' "
            f"({type(error).__name__})."
        )
    return RuntimeError(
        f"Whisper model '{model_id}' is not available in the user model cache. "
        "Download it during setup or set NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD=1 "
        "for an explicit first-run download."
    )
