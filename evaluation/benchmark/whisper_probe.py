"""Evaluation-only Whisper observability, installed in a benchmark worker process only.

The frozen pipeline imports faster_whisper.WhisperModel at call time. This module swaps that name, in
the worker process, for a subclass that calls exactly the same constructor and transcribe() with the
same arguments and returns the same objects, while timing them. It records the device, compute type,
detected language and probability, segment count and durations. It never reads segment text, audio or
any speech content.
"""
from __future__ import annotations

from time import perf_counter


def install(journal):
    """Returns True when installed; False (and nothing patched) when faster_whisper is unavailable."""
    try:
        import faster_whisper
    except ImportError:
        journal.emit("whisper_probe", available=False, reason="faster_whisper_not_importable")
        return False
    original = faster_whisper.WhisperModel
    if getattr(original, "_benchmark_probe", False):
        return True

    class ObservedWhisperModel(original):
        _benchmark_probe = True

        def __init__(self, *args, **kwargs):
            started = perf_counter()
            try:
                super().__init__(*args, **kwargs)
            except BaseException as exc:
                journal.emit("whisper_model_load", ok=False, error_type=type(exc).__name__,
                             requested_device=kwargs.get("device"), seconds=perf_counter() - started)
                raise
            model = getattr(self, "model", None)
            journal.emit("whisper_model_load", ok=True, requested_device=kwargs.get("device"),
                         requested_compute_type=kwargs.get("compute_type"),
                         device=getattr(model, "device", None), compute_type=getattr(model, "compute_type", None),
                         seconds=perf_counter() - started)

        def transcribe(self, *args, **kwargs):
            started = perf_counter()
            device = getattr(getattr(self, "model", None), "device", None)
            try:
                segments, info = super().transcribe(*args, **kwargs)
            except BaseException as exc:
                journal.emit("whisper_transcription", ok=False, error_type=type(exc).__name__, device=device,
                             seconds=perf_counter() - started)
                raise
            setup = perf_counter() - started

            def observed():
                count, complete, error = 0, False, None
                try:
                    for segment in segments:
                        count += 1
                        yield segment
                    complete = True
                except BaseException as exc:
                    error = type(exc).__name__
                    raise
                finally:
                    probability = getattr(info, "language_probability", None)
                    journal.emit("whisper_transcription", ok=error is None and complete, complete=complete,
                                 error_type=error, device=device, language=getattr(info, "language", None),
                                 language_probability=None if probability is None else float(probability),
                                 segments=count, setup_seconds=setup, seconds=perf_counter() - started)

            return observed(), info

    faster_whisper.WhisperModel = ObservedWhisperModel
    journal.emit("whisper_probe", available=True)
    return True


def summarize(entries):
    """Aggregate probe events from a journal (list of dicts); None when the probe recorded nothing."""
    loads = [e for e in entries if e.get("kind") == "whisper_model_load"]
    runs = [e for e in entries if e.get("kind") == "whisper_transcription"]
    probe = next((e for e in entries if e.get("kind") == "whisper_probe"), None)
    if probe is None:
        return None
    keep = ("ok", "device", "compute_type", "requested_device", "requested_compute_type", "seconds", "error_type")
    return {"probe_available": probe.get("available", False),
            "model_loads": [{k: e.get(k) for k in keep} for e in loads],
            "transcriptions": [_transcription(e) for e in runs]}


def _transcription(event):
    """Whisper reports a language even for silence: without a segment it is not a speech-language observation."""
    row = {k: event.get(k) for k in ("ok", "complete", "device", "segments", "setup_seconds", "seconds", "error_type")}
    speech = bool(event.get("segments"))
    row.update(speech_segments_present=speech,
               language=event.get("language") if speech else None,
               language_probability=event.get("language_probability") if speech else None,
               language_basis="speech_segments" if speech else "no_speech_segments_unreliable",
               detected_language_without_speech=None if speech else event.get("language"))
    return row
