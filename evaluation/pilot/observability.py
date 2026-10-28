"""Delegating observers: metadata only, no changes to returned service objects."""
from __future__ import annotations

import json
from time import perf_counter

from services.analysis.cache import AnalysisCache
from services.analysis.cancellation import AnalysisCancelled
from services.analysis.providers.base import VLMStructuredOutputError


class Journal:
    def __init__(self, path):
        self.stream = path.open("x", encoding="utf-8")
        self.started = perf_counter()
        self.planned = None
        self.finished = {}
        self.started_batches = set()

    def emit(self, kind, **data):
        entry = {"schema_version": 1, "kind": kind,
                 "elapsed_seconds": perf_counter() - self.started, **data}
        self.stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()

    def progress(self, event):
        # Messages may contain transcript/model text. Only structured counters.
        self.emit("progress", **event.model_dump(mode="json", exclude={"message", "elapsed_seconds"}))
        if event.stage.value == "vlm_review" and self.planned is None:
            self.planned = set() if event.total_units == 0 else None

    def reliability(self):
        return {"planned_batches": None if self.planned is None else len(self.planned),
                "started_batches": len(self.started_batches),
                "unprocessed_batches": None if self.planned is None else len(self.planned - self.started_batches),
                "unfinished_batches": len(self.started_batches - self.finished.keys()),
                "completed_batches": sum(x["status"] == "completed" for x in self.finished.values()),
                "failed_batches": sum(x["status"] == "failed" for x in self.finished.values()),
                "cancelled_batches": sum(x["status"] == "cancelled" for x in self.finished.values()),
                "invalid_responses": sum(x["invalid"] for x in self.finished.values()),
                "repaired_responses": sum(x["repaired"] for x in self.finished.values()),
                "response_observability": "invalid_responses is a lower bound; repair internals may be unavailable on timeout"}

    def close(self):
        self.stream.close()


def frame_metadata(frame):
    return {"timestamp_seconds": frame.timestamp_seconds,
            "origin": {"interval": "periodic", "scene": "scene", "refined": "refinement"}[frame.source]}


def invalid_output_observed(error):
    """Inspect typed exception causes, never their potentially sensitive text."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, VLMStructuredOutputError):
            return True
        error = error.__cause__ or error.__context__
    return False


class Delegate:
    def __init__(self, service, journal):
        self.service, self.journal = service, journal

    def __getattr__(self, name):
        return getattr(self.service, name)


class SamplingObserver(Delegate):
    def sample_coarse(self, *args, **kwargs):
        frames = self.service.sample_coarse(*args, **kwargs)
        self.journal.emit("coarse_frames", frames=[frame_metadata(f) for f in frames])
        return frames

    def refine_candidates(self, video_path, workspace, duration_seconds, settings,
                          candidates, coarse_frames, cancellation, progress_callback=None):
        self.journal.emit("candidate_windows", windows=[c.model_dump(mode="json") for c in candidates])
        frames, batches = self.service.refine_candidates(
            video_path, workspace, duration_seconds, settings, candidates, coarse_frames,
            cancellation, progress_callback)
        self.journal.planned = {b.batch_id for b in batches}
        self.journal.emit("refined_frames", frames=[frame_metadata(f) for f in frames])
        self.journal.emit("batch_plan", batches=[{
            "batch_id": b.batch_id, "candidate_window_id": b.candidate_window_id,
            "start_seconds": b.start_seconds, "end_seconds": b.end_seconds,
            "frames": [frame_metadata(f) for f in b.frames]} for b in batches])
        return frames, batches


class PrefilterObserver(Delegate):
    def score_frames(self, frames, settings, cancellation, progress_callback=None):
        scores = self.service.score_frames(frames, settings, cancellation, progress_callback)
        diagnostics = getattr(self.service, "diagnostics", None)
        if diagnostics is not None:
            self.journal.emit("marqo_diagnostics", diagnostics=diagnostics.model_dump(mode="json"))
        self.journal.emit("marqo_scores", threshold=settings.resolved_prefilter_threshold,
                          scores=[{**frame_metadata(s.frame),
                                   "model_probability": None if s.conservatively_included else s.nsfw_probability,
                                   "decision_score": s.nsfw_probability,
                                   "conservatively_included": s.conservatively_included,
                                   "passes_gate": s.conservatively_included or
                                   s.nsfw_probability >= settings.resolved_prefilter_threshold}
                                  for s in scores])
        return scores


class ProviderObserver(Delegate):
    def review_batch(self, batch, settings, cancellation):
        self.journal.started_batches.add(batch.batch_id)
        self.journal.emit("batch_started", batch_id=batch.batch_id,
                          timestamps=[f.timestamp_seconds for f in batch.frames])
        started = perf_counter()
        status, error_type, invalid, repaired = "failed", None, False, False
        stop_reason = None
        try:
            result = self.service.review_batch(batch, settings, cancellation)
            status = "completed"
            repaired = bool(getattr(result, "repaired", False))
            stop_reason = getattr(result, "stop_reason", None)
            invalid = repaired  # first response needed repair; no raw text retained
            return result
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, (AnalysisCancelled, KeyboardInterrupt)) else "failed"
            error_type = type(exc).__name__
            stop_reason = getattr(exc, "stop_reason", None)
            invalid = invalid_output_observed(exc) or bool(getattr(exc, "repaired_output", ""))
            raise
        finally:
            detail = {"status": status, "error_type": error_type, "invalid": invalid,
                      "repaired": repaired, "stop_reason": stop_reason}
            self.journal.finished[batch.batch_id] = detail
            self.journal.emit("batch_finished", batch_id=batch.batch_id,
                              duration_seconds=perf_counter() - started, **detail)


class PrivateEvaluationCache(AnalysisCache):
    """Keep reusable contracts, but don't duplicate raw outputs in checkpoints.

    Evaluation always uses a fresh cache and force_reanalysis; redaction affects
    persistence ONLY, never the responses/records returned to the pipeline.
    """
    def save_batch_checkpoint(self, checkpoint):
        response = checkpoint.response
        if response is not None:
            response = response.model_copy(update={"suggestions": [
                item.model_copy(update={"reason": "[omitted]"}) for item in response.suggestions]})
        safe = checkpoint.model_copy(update={
            "raw_output": None, "repaired_output": None, "response": response,
            "error": "[omitted; see observer error_type]" if checkpoint.error else None})
        return super().save_batch_checkpoint(safe)

    def save(self, cache_key, record):
        safe = record.model_copy(update={
            "text_evidence": [e.model_copy(update={"excerpt": ""}) for e in record.text_evidence],
            "visual_evidence": [e.model_copy(update={"reason": ""}) for e in record.visual_evidence],
            "suggestions": [s.model_copy(update={"reason": ""}) for s in record.suggestions],
            "warnings": ["[omitted]"] * len(record.warnings),
            "errors": ["[omitted]"] * len(record.errors)})
        return super().save(cache_key, safe)


def attach_observers(services, journal):
    """Wrap an already constructed production service set, preserving Marqo."""
    if services.prefilter is None:
        raise ValueError("Evaluation requires the production Marqo prefilter")
    services.visual_sampling = SamplingObserver(services.visual_sampling, journal)
    services.prefilter = PrefilterObserver(services.prefilter, journal)
    services.provider = ProviderObserver(services.provider, journal)
    return services
