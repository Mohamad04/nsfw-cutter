from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TypedDict

from services.analysis.cache import (
    AnalysisCache,
    BatchCheckpoint,
    BatchCheckpointStatus,
    PrefilterCheckpoint,
    PrefilterScoreItem,
)
from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    AnalysisProgressEvent,
    AnalysisRecord,
    AnalysisRunRequest,
    AnalysisStage,
    AnalysisStatus,
    CandidateWindow,
    FinalSuggestion,
    PrefilterFrameScore,
    PreflightResult,
    ProviderDiagnostics,
    SampledFrame,
    TextEvidenceOutput,
    VisualBatch,
    VisualEvidence,
    VLMReviewResponse,
    VLMReviewResult,
)
from services.analysis.fusion import fuse_evidence
from services.analysis.preflight import PreflightService
from services.analysis.prefilter import LocalNSFWPrefilter, group_candidate_windows
from services.analysis.providers.base import VLMProvider, VLMProviderUnavailableError
from services.analysis.providers.qwen import LocalQwenVLProvider
from services.analysis.text_evidence import TextEvidenceService
from services.analysis.tracing import (
    FrameworkTracingControlUnavailable,
    OptionalLangSmithTracer,
    redact_sensitive_text,
    suppress_framework_tracing,
)
from services.analysis.visual_sampling import VisualSamplingService

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, str], None]
EventCallback = Callable[[AnalysisProgressEvent], None]


class AnalysisState(TypedDict, total=False):
    job_id: str
    request: AnalysisRunRequest
    cancellation: CancellationToken
    progress_callback: ProgressCallback | None
    event_callback: EventCallback | None
    started_at: datetime
    started_monotonic: float
    resolved_video_path: Path
    preflight: PreflightResult
    cached_record: AnalysisRecord
    provider_ready: bool
    workspace: Path
    text_output: TextEvidenceOutput
    coarse_frames: list[SampledFrame]
    sampled_frames: list[SampledFrame]
    prefilter_scores: list[PrefilterFrameScore]
    candidate_windows: list[CandidateWindow]
    visual_batches: list[VisualBatch]
    visual_evidence: list[VisualEvidence]
    suggestions: list[FinalSuggestion]
    warnings: list[str]
    errors: list[str]
    status: AnalysisStatus
    record: AnalysisRecord
    metrics: dict
    provider_diagnostics: ProviderDiagnostics


class AnalysisServices:
    def __init__(
        self,
        *,
        cache: AnalysisCache | None = None,
        preflight: PreflightService | None = None,
        text_evidence: TextEvidenceService | None = None,
        visual_sampling: VisualSamplingService | None = None,
        prefilter=None,
        provider: VLMProvider | None = None,
        tracer: OptionalLangSmithTracer | None = None,
    ) -> None:
        self.cache = cache or AnalysisCache()
        self.preflight = preflight or PreflightService(cache=self.cache)
        self.text_evidence = text_evidence or TextEvidenceService()
        self.visual_sampling = visual_sampling or VisualSamplingService()
        self.provider = provider or LocalQwenVLProvider()
        # A caller which injects a model provider is usually a deterministic test or
        # an alternate backend. Preserve that seam; the production default always
        # receives the mandatory fast prefilter.
        self.prefilter = (
            prefilter
            if prefilter is not None
            else (LocalNSFWPrefilter() if provider is None else None)
        )
        self.tracer = tracer or OptionalLangSmithTracer()


def preflight_node(state: AnalysisState, services: AnalysisServices) -> dict:
    run_id = _start_trace(state, services, "preflight")
    try:
        _emit(state, 0, "Starting video analysis", stage=AnalysisStage.PREFLIGHT)
        request = state["request"]
        resolved_path, result = services.preflight.run(
            request.video_path,
            request.settings,
            state["cancellation"],
            _stage_progress(state, AnalysisStage.PREFLIGHT),
            selected_subtitle=request.selected_subtitle,
        )
        cached_record = None
        if not request.force_reanalysis:
            cached_record = services.cache.load(result.cache_key)
        update = {
            "resolved_video_path": resolved_path,
            "preflight": result,
        }
        if cached_record is not None:
            update.update(
                cached_record=cached_record,
                record=cached_record,
                status=cached_record.status,
            )
            _emit(
                state,
                100,
                "Loaded cached video analysis",
                stage=AnalysisStage.PERSISTENCE,
                cache_hits=1,
            )
        else:
            provider_ready = True
            errors = list(state.get("errors", []))
            readiness_check = getattr(services.provider, "check_ready", None)
            if callable(readiness_check):
                try:
                    readiness_check(request.settings, state["cancellation"])
                except AnalysisCancelled:
                    raise
                except VLMProviderUnavailableError as exc:
                    provider_ready = False
                    errors.append(_diagnostic("Visual model unavailable", exc))
            if provider_ready and services.prefilter is not None:
                readiness_check = getattr(services.prefilter, "check_ready", None)
                if callable(readiness_check):
                    try:
                        readiness_check(request.settings, state["cancellation"])
                    except AnalysisCancelled:
                        raise
                    except Exception as exc:
                        provider_ready = False
                        errors.append(_diagnostic("Fast visual prefilter unavailable", exc))
            update["provider_ready"] = provider_ready
            update["errors"] = errors
            if provider_ready:
                update["workspace"] = services.cache.create_workspace(state["job_id"])
        _finish_trace(
            run_id,
            services,
            state,
            {
                "video_fingerprint": result.video_fingerprint,
                "duration_seconds": result.media.duration_seconds,
                "fps": result.media.fps,
                "status": (
                    "cache_hit"
                    if cached_record is not None
                    else ("completed" if update.get("provider_ready", True) else "partial")
                ),
            },
        )
        return update
    except Exception as exc:
        _finish_trace(run_id, services, state, {}, error=exc)
        raise


def gather_text_evidence_node(state: AnalysisState, services: AnalysisServices) -> dict:
    if state.get("cached_record") is not None or state.get("provider_ready") is False:
        return {}
    run_id = _start_trace(state, services, "gather_text_evidence")
    try:
        output = services.text_evidence.gather(
            state["resolved_video_path"],
            state["request"].selected_subtitle,
            state["workspace"],
            state["request"].settings,
            state["cancellation"],
            _stage_progress(state, AnalysisStage.TEXT_EVIDENCE),
        )
        warnings = [*state.get("warnings", []), *output.warnings]
        _finish_trace(
            run_id,
            services,
            state,
            {
                "status": "completed",
                "suggestion_count": len(output.evidence),
            },
        )
        return {"text_output": output, "warnings": warnings}
    except AnalysisCancelled as exc:
        _finish_trace(run_id, services, state, {}, error=exc)
        raise
    except Exception as exc:
        logger.warning("Text/audio evidence is unavailable", exc_info=True)
        message = _diagnostic("Text/audio evidence unavailable", exc)
        output = TextEvidenceOutput(warnings=[message])
        _finish_trace(run_id, services, state, {"status": "partial"}, error=exc)
        return {
            "text_output": output,
            "errors": [*state.get("errors", []), message],
        }


def sample_visual_evidence_node(state: AnalysisState, services: AnalysisServices) -> dict:
    if state.get("cached_record") is not None or state.get("provider_ready") is False:
        return {}
    run_id = _start_trace(state, services, "sample_visual_evidence")
    try:
        sample_coarse = getattr(services.visual_sampling, "sample_coarse", None)
        if services.prefilter is not None and callable(sample_coarse):
            frames = sample_coarse(
                state["resolved_video_path"],
                state["workspace"],
                state["preflight"].media.duration_seconds,
                state["request"].settings,
                state["cancellation"],
                _stage_progress(state, AnalysisStage.COARSE_SAMPLING),
            )
            batches = []
        else:
            frames, batches = services.visual_sampling.sample(
                state["resolved_video_path"],
                state["workspace"],
                state["preflight"].media.duration_seconds,
                state["request"].settings,
                state["cancellation"],
                _stage_progress(state, AnalysisStage.COARSE_SAMPLING),
            )
        _finish_trace(
            run_id,
            services,
            state,
            {
                "status": "completed",
                "frame_count": len(frames),
                "batch_count": len(batches),
            },
        )
        return {
            "coarse_frames": frames,
            "sampled_frames": frames,
            "visual_batches": batches,
            "metrics": {
                **state.get("metrics", {}),
                "coarse_frame_count": len(frames),
            },
        }
    except AnalysisCancelled as exc:
        _finish_trace(run_id, services, state, {}, error=exc)
        raise
    except Exception as exc:
        logger.warning("Visual sampling is unavailable", exc_info=True)
        message = _diagnostic("Visual sampling unavailable", exc)
        _finish_trace(run_id, services, state, {"status": "partial"}, error=exc)
        return {
            "coarse_frames": [],
            "sampled_frames": [],
            "visual_batches": [],
            "errors": [*state.get("errors", []), message],
        }


def prefilter_visual_evidence_node(state: AnalysisState, services: AnalysisServices) -> dict:
    if state.get("cached_record") is not None or state.get("provider_ready") is False:
        return {}
    if services.prefilter is None:
        # Explicitly injected providers retain the independently testable direct
        # batching seam. The production AnalysisServices always has a prefilter.
        return {
            "candidate_windows": [],
            "metrics": {
                **state.get("metrics", {}),
                "candidate_count": len(state.get("visual_batches", [])),
                "total_batches": len(state.get("visual_batches", [])),
            },
        }

    run_id = _start_trace(state, services, "prefilter_visual_evidence")
    scores: list[PrefilterFrameScore] = []
    try:
        coarse_frames = sorted(
            state.get("coarse_frames", []),
            key=lambda frame: frame.timestamp_seconds,
        )
        _emit(
            state,
            25,
            f"Classifying {len(coarse_frames)} coarse frames",
            stage=AnalysisStage.PREFILTER,
            total_units=len(coarse_frames),
        )
        settings = state["request"].settings
        score_key = services.cache.make_prefilter_key(
            state["preflight"].cache_key,
            coarse_frames,
            settings,
        )
        cached_scores = None
        if not state["request"].force_reanalysis:
            cached_scores = services.cache.load_prefilter_checkpoint(
                state["preflight"].cache_key,
                score_key,
            )
        if cached_scores is not None and [
            item.timestamp_seconds for item in cached_scores.scores
        ] != [frame.timestamp_seconds for frame in coarse_frames]:
            cached_scores = None
        prefilter_cache_hit = int(cached_scores is not None)
        if cached_scores is not None:
            scores = [
                PrefilterFrameScore(
                    frame=frame,
                    nsfw_probability=item.nsfw_probability,
                    conservatively_included=item.conservatively_included,
                )
                for frame, item in zip(
                    coarse_frames,
                    cached_scores.scores,
                    strict=True,
                )
            ]
            _emit(
                state,
                45,
                f"Reused {len(scores)} cached prefilter score(s)",
                stage=AnalysisStage.PREFILTER,
                stage_percent=100,
                completed_units=len(scores),
                total_units=len(scores),
                cache_hits=1,
                resumed_units=1,
            )
        else:
            scores = services.prefilter.score_frames(
                coarse_frames,
                settings,
                state["cancellation"],
                _stage_progress(state, AnalysisStage.PREFILTER),
            )
            if scores and not any(score.conservatively_included for score in scores):
                services.cache.save_prefilter_checkpoint(
                    PrefilterCheckpoint(
                        analysis_cache_key=state["preflight"].cache_key,
                        score_key=score_key,
                        model_id=settings.prefilter_model_id,
                        model_revision=settings.prefilter_model_revision,
                        scores=[
                            PrefilterScoreItem(
                                timestamp_seconds=score.frame.timestamp_seconds,
                                nsfw_probability=score.nsfw_probability,
                                conservatively_included=score.conservatively_included,
                            )
                            for score in scores
                        ],
                    )
                )
        state["cancellation"].raise_if_cancelled()
        text_windows = _text_candidate_windows(
            (state.get("text_output") or TextEvidenceOutput()).evidence
        )
        candidates = group_candidate_windows(
            scores,
            duration_seconds=state["preflight"].media.duration_seconds,
            settings=settings,
            text_windows=text_windows,
        )
        _emit(
            state,
            46,
            f"Found {len(candidates)} candidate window(s)",
            stage=AnalysisStage.CANDIDATE_PLANNING,
            stage_percent=100,
            candidate_count=len(candidates),
        )

        refine = getattr(services.visual_sampling, "refine_candidates", None)
        if candidates and callable(refine):
            sampled_frames, batches = refine(
                state["resolved_video_path"],
                state["workspace"],
                state["preflight"].media.duration_seconds,
                settings,
                candidates,
                coarse_frames,
                state["cancellation"],
                _stage_progress(state, AnalysisStage.CANDIDATE_PLANNING),
            )
        elif candidates:
            sampled_frames = coarse_frames
            batches = _candidate_batches(state.get("visual_batches", []), candidates)
        else:
            sampled_frames, batches = [], []

        warnings = list(
            dict.fromkeys(
                [
                    *state.get("warnings", []),
                    *[
                        str(item)
                        for item in getattr(services.prefilter, "warnings", [])
                        if str(item).strip()
                    ],
                ]
            )
        )
        metrics = {
            **state.get("metrics", {}),
            "prefilter_frame_count": len(scores),
            "prefilter_cache_hits": prefilter_cache_hit,
            "candidate_count": len(candidates),
            "total_batches": len(batches),
        }
        _finish_trace(
            run_id,
            services,
            state,
            {
                "status": "completed",
                "frame_count": len(scores),
                "candidate_count": len(candidates),
                "batch_count": len(batches),
            },
        )
        return {
            "prefilter_scores": scores,
            "candidate_windows": candidates,
            "sampled_frames": sampled_frames,
            "visual_batches": batches,
            "warnings": warnings,
            "metrics": metrics,
        }
    except AnalysisCancelled as exc:
        _finish_trace(run_id, services, state, {}, error=exc)
        raise
    except Exception as exc:
        logger.warning("Fast visual prefilter is unavailable", exc_info=True)
        message = _diagnostic("Fast visual prefilter unavailable", exc)
        _finish_trace(run_id, services, state, {"status": "partial"}, error=exc)
        return {
            "prefilter_scores": scores,
            "candidate_windows": [],
            "visual_batches": [],
            "errors": [*state.get("errors", []), message],
        }
    finally:
        try:
            services.prefilter.release()
        except Exception:
            logger.warning("Unable to release prefilter resources", exc_info=True)


def review_visual_batches_node(state: AnalysisState, services: AnalysisServices) -> dict:
    if state.get("cached_record") is not None or state.get("provider_ready") is False:
        return {}
    run_id = _start_trace(state, services, "review_visual_batches")
    batches = state.get("visual_batches", [])
    visual_evidence: list[VisualEvidence] = []
    errors = list(state.get("errors", []))
    settings = state["request"].settings
    analysis_cache_key = state["preflight"].cache_key
    completed_count = 0
    failed_count = 0
    repaired_count = 0
    resumed_count = 0
    durations: list[float] = []
    provider_diagnostics = state.get("provider_diagnostics")
    try:
        for index, batch in enumerate(batches):
            state["cancellation"].raise_if_cancelled()
            batch_key = services.cache.make_batch_key(
                analysis_cache_key,
                batch,
                settings,
                prompt_schema_version=str(settings.prompt_schema_revision),
            )
            previous = services.cache.load_batch_checkpoint(analysis_cache_key, batch_key)
            response: VLMReviewResponse | None = None
            review_result: VLMReviewResult | None = None
            if (
                not state["request"].force_reanalysis
                and previous is not None
                and previous.status == BatchCheckpointStatus.COMPLETED
                and previous.response is not None
            ):
                response = previous.response
                resumed_count += 1
                completed_count += 1

            percent = 48 + int(47 * index / max(1, len(batches)))
            device_text = _provider_device_text(provider_diagnostics, services.provider)
            remaining = max(0, len(batches) - index)
            eta = (sum(durations[-5:]) / len(durations[-5:]) * remaining) if durations else None
            _emit(
                state,
                percent,
                (
                    f"Reviewing candidate batch {index + 1} of {len(batches)}"
                    + (f" on {device_text}" if device_text else "")
                ),
                stage=AnalysisStage.VLM_REVIEW,
                stage_percent=int(100 * index / max(1, len(batches))),
                completed_units=index,
                total_units=len(batches),
                candidate_count=len(state.get("candidate_windows", [])),
                failed_units=failed_count,
                repaired_units=repaired_count,
                cache_hits=resumed_count,
                resumed_units=resumed_count,
                eta_seconds=eta,
                device=device_text,
            )
            if response is not None:
                visual_evidence.extend(_visual_evidence_from_response(response, batch))
                continue

            attempt_count = (previous.attempt_count + 1) if previous is not None else 1
            inference_started = perf_counter()
            try:
                reviewed = services.provider.review_batch(
                    batch,
                    settings,
                    state["cancellation"],
                )
                elapsed = perf_counter() - inference_started
                if isinstance(reviewed, VLMReviewResult):
                    review_result = reviewed
                    response = reviewed.response
                    repaired_count += int(reviewed.repaired)
                    provider_diagnostics = reviewed.diagnostics or provider_diagnostics
                elif isinstance(reviewed, VLMReviewResponse):
                    response = reviewed
                else:
                    response = VLMReviewResponse.model_validate(reviewed)

                durations.append(
                    review_result.elapsed_seconds
                    if review_result is not None and review_result.elapsed_seconds > 0
                    else elapsed
                )
                services.cache.save_batch_checkpoint(
                    BatchCheckpoint(
                        analysis_cache_key=analysis_cache_key,
                        batch_key=batch_key,
                        batch_id=batch.batch_id,
                        start_seconds=batch.start_seconds,
                        end_seconds=batch.end_seconds,
                        frame_timestamps=[
                            frame.timestamp_seconds for frame in batch.frames
                        ],
                        prompt_schema_version=str(settings.prompt_schema_revision),
                        model_id=settings.model_id,
                        model_revision=settings.model_revision,
                        status=BatchCheckpointStatus.COMPLETED,
                        response=response,
                        raw_output=(review_result.raw_output if review_result else None),
                        repaired_output=(
                            review_result.repaired_output if review_result else None
                        ),
                        repaired=bool(review_result and review_result.repaired),
                        stop_reason=(review_result.stop_reason if review_result else "completed"),
                        attempt_count=attempt_count,
                        inference_seconds=durations[-1],
                    )
                )
                completed_count += 1
            except AnalysisCancelled:
                raise
            except VLMProviderUnavailableError as exc:
                logger.warning("Visual model is unavailable", exc_info=True)
                errors.append(_diagnostic("Visual model unavailable", exc))
                failed_count += 1
                _save_failed_batch_checkpoint(
                    services.cache,
                    analysis_cache_key,
                    batch_key,
                    batch,
                    settings,
                    exc,
                    attempt_count,
                    perf_counter() - inference_started,
                )
                break
            except Exception as exc:
                logger.warning("Visual batch %s failed", batch.batch_id, exc_info=True)
                errors.append(_diagnostic(f"Visual batch {index + 1} failed", exc))
                failed_count += 1
                _save_failed_batch_checkpoint(
                    services.cache,
                    analysis_cache_key,
                    batch_key,
                    batch,
                    settings,
                    exc,
                    attempt_count,
                    perf_counter() - inference_started,
                )
                continue
            visual_evidence.extend(_visual_evidence_from_response(response, batch))
        provider_warnings = [
            str(warning)
            for warning in getattr(services.provider, "warnings", [])
            if str(warning).strip()
        ]
        warnings = list(dict.fromkeys([*state.get("warnings", []), *provider_warnings]))
        device_text = _provider_device_text(provider_diagnostics, services.provider)
        _emit(
            state,
            95,
            (
                f"Visual review complete: {completed_count} completed, "
                f"{failed_count} failed, {repaired_count} repaired"
            ),
            stage=AnalysisStage.VLM_REVIEW,
            stage_percent=100,
            completed_units=completed_count + failed_count,
            total_units=len(batches),
            candidate_count=len(state.get("candidate_windows", [])),
            failed_units=failed_count,
            repaired_units=repaired_count,
            cache_hits=resumed_count,
            resumed_units=resumed_count,
            eta_seconds=0.0,
            device=device_text,
        )
        _finish_trace(
            run_id,
            services,
            state,
            {
                "status": "partial" if errors else "completed",
                "batch_count": len(batches),
                "suggestion_count": len(visual_evidence),
            },
        )
        return {
            "visual_evidence": visual_evidence,
            "warnings": warnings,
            "errors": errors,
            "provider_diagnostics": provider_diagnostics,
            "metrics": {
                **state.get("metrics", {}),
                "completed_batches": completed_count,
                "failed_batches": failed_count,
                "repaired_batches": repaired_count,
                "resumed_batches": resumed_count,
                "total_batches": len(batches),
            },
        }
    except Exception as exc:
        _finish_trace(run_id, services, state, {}, error=exc)
        raise


def fuse_evidence_node(state: AnalysisState, services: AnalysisServices) -> dict:
    if state.get("cached_record") is not None:
        return {}
    run_id = _start_trace(state, services, "fuse_evidence")
    try:
        state["cancellation"].raise_if_cancelled()
        text_output = state.get("text_output") or TextEvidenceOutput()
        suggestions = fuse_evidence(
            state.get("visual_evidence", []),
            text_output.evidence,
            state["request"].settings,
            state["preflight"].media.duration_seconds,
            state["preflight"].video_fingerprint,
        )
        status = AnalysisStatus.PARTIAL if state.get("errors") else AnalysisStatus.COMPLETED
        _emit(
            state,
            98,
            "Fused visual and text evidence",
            stage=AnalysisStage.FUSION,
            stage_percent=100,
            candidate_count=len(state.get("candidate_windows", [])),
        )
        _finish_trace(
            run_id,
            services,
            state,
            {"status": status.value, "suggestion_count": len(suggestions)},
        )
        return {"suggestions": suggestions, "status": status}
    except Exception as exc:
        _finish_trace(run_id, services, state, {}, error=exc)
        raise


def persist_and_publish_node(state: AnalysisState, services: AnalysisServices) -> dict:
    if state.get("cached_record") is not None:
        return {"record": state["cached_record"]}
    run_id = _start_trace(state, services, "persist_and_publish")
    try:
        state["cancellation"].raise_if_cancelled()
        text_output = state.get("text_output") or TextEvidenceOutput()
        settings = state["request"].settings
        record = AnalysisRecord(
            video_fingerprint=state["preflight"].video_fingerprint,
            text_source_fingerprint=state["preflight"].text_source_fingerprint,
            model_id=settings.model_id,
            model_revision=settings.model_revision,
            settings_version=settings.settings_version,
            settings=settings.model_dump(mode="json"),
            status=state.get("status", AnalysisStatus.COMPLETED),
            media=state["preflight"].media,
            text_evidence=text_output.evidence,
            visual_evidence=state.get("visual_evidence", []),
            candidate_windows=state.get("candidate_windows", []),
            suggestions=state.get("suggestions", []),
            metrics=state.get("metrics", {}),
            provider_diagnostics=state.get("provider_diagnostics"),
            warnings=state.get("warnings", []),
            errors=state.get("errors", []),
            started_at=state["started_at"],
            completed_at=datetime.now(UTC),
        )
        services.cache.save_preserving_completed(state["preflight"].cache_key, record)
        _emit(
            state,
            100,
            _completion_message(record),
            stage=AnalysisStage.PERSISTENCE,
            stage_percent=100,
            candidate_count=len(state.get("candidate_windows", [])),
            completed_units=int(state.get("metrics", {}).get("completed_batches", 0)),
            total_units=int(state.get("metrics", {}).get("total_batches", 0)),
            failed_units=int(state.get("metrics", {}).get("failed_batches", 0)),
            repaired_units=int(state.get("metrics", {}).get("repaired_batches", 0)),
            resumed_units=int(state.get("metrics", {}).get("resumed_batches", 0)),
            device=_provider_device_text(state.get("provider_diagnostics"), services.provider),
        )
        _finish_trace(
            run_id,
            services,
            state,
            {"status": record.status.value, "suggestion_count": len(record.suggestions)},
        )
        return {"record": record}
    except Exception as exc:
        _finish_trace(run_id, services, state, {}, error=exc)
        raise


class AnalysisPipeline:
    def __init__(self, services: AnalysisServices | None = None) -> None:
        self.services = services or AnalysisServices()

    def run(
        self,
        request: AnalysisRunRequest,
        cancellation: CancellationToken | None = None,
        progress_callback: ProgressCallback | None = None,
        *,
        event_callback: EventCallback | None = None,
        job_id: str | None = None,
    ) -> AnalysisRecord:
        cancellation_token = cancellation or CancellationToken()
        state: AnalysisState = {
            "job_id": job_id or uuid.uuid4().hex,
            "request": request,
            "cancellation": cancellation_token,
            "progress_callback": progress_callback,
            "event_callback": event_callback,
            "started_at": datetime.now(UTC),
            "started_monotonic": perf_counter(),
            "warnings": [],
            "errors": [],
            "metrics": {},
        }
        final_state: AnalysisState = state
        try:
            final_state = self._invoke_graph(state)
            return final_state["record"]
        except AnalysisCancelled:
            record = self._terminal_record(final_state, AnalysisStatus.CANCELLED, [])
            self._save_terminal_record(final_state, record)
            _emit(
                final_state,
                0,
                "Video analysis cancelled",
                stage=AnalysisStage.PERSISTENCE,
            )
            return record
        except Exception as exc:
            logger.exception("Video analysis failed")
            error = _diagnostic("Video analysis failed", exc)
            record = self._terminal_record(final_state, AnalysisStatus.FAILED, [error])
            self._save_terminal_record(final_state, record)
            _emit(final_state, 0, error, stage=AnalysisStage.PERSISTENCE)
            return record
        finally:
            _remove_workspace(final_state.get("workspace"), self.services.cache.work_dir)

    def _invoke_graph(self, state: AnalysisState) -> AnalysisState:
        try:
            from services.analysis.graph import build_analysis_graph

            graph = build_analysis_graph(self.services)
        except ModuleNotFoundError as exc:
            if (exc.name or "").split(".", maxsplit=1)[0] != "langgraph":
                raise
            return _invoke_fixed_sequence(state, self.services)
        # Consume node updates explicitly so `state` always reflects the last completed
        # node if a later LangGraph node is cancelled or fails. This lets terminal
        # records retain the fingerprint/partial evidence and guarantees workspace
        # cleanup on exceptional exits.
        try:
            with suppress_framework_tracing():
                events = graph.stream(
                    state,
                    config={"callbacks": []},
                    stream_mode="updates",
                )
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    for update in event.values():
                        if isinstance(update, dict):
                            state.update(update)
        except FrameworkTracingControlUnavailable:
            logger.warning(
                "LangGraph tracing could not be suppressed; using the fixed local sequence"
            )
            return _invoke_fixed_sequence(state, self.services)
        return state

    def _terminal_record(
        self,
        state: AnalysisState,
        status: AnalysisStatus,
        additional_errors: list[str],
    ) -> AnalysisRecord:
        request = state["request"]
        preflight = state.get("preflight")
        text_output = state.get("text_output") or TextEvidenceOutput()
        return AnalysisRecord(
            video_fingerprint=(preflight.video_fingerprint if preflight else "unavailable"),
            text_source_fingerprint=(
                preflight.text_source_fingerprint
                if preflight
                else "audio-fallback:unavailable:v1"
            ),
            model_id=request.settings.model_id,
            model_revision=request.settings.model_revision,
            settings_version=request.settings.settings_version,
            settings=request.settings.model_dump(mode="json"),
            status=status,
            media=preflight.media if preflight else None,
            text_evidence=text_output.evidence,
            visual_evidence=state.get("visual_evidence", []),
            candidate_windows=state.get("candidate_windows", []),
            suggestions=state.get("suggestions", []),
            metrics=state.get("metrics", {}),
            provider_diagnostics=state.get("provider_diagnostics"),
            warnings=state.get("warnings", []),
            errors=[*state.get("errors", []), *additional_errors],
            started_at=state["started_at"],
            completed_at=datetime.now(UTC),
        )

    def _save_terminal_record(self, state: AnalysisState, record: AnalysisRecord) -> None:
        preflight = state.get("preflight")
        if preflight is None:
            return
        try:
            self.services.cache.save_preserving_completed(preflight.cache_key, record)
        except OSError:
            logger.warning("Unable to persist terminal analysis status", exc_info=True)


def _invoke_fixed_sequence(state: AnalysisState, services: AnalysisServices) -> AnalysisState:
    for node in (
        preflight_node,
        gather_text_evidence_node,
        sample_visual_evidence_node,
        prefilter_visual_evidence_node,
        review_visual_batches_node,
        fuse_evidence_node,
        persist_and_publish_node,
    ):
        state.update(node(state, services))
    return state


def _emit(
    state: AnalysisState,
    percent: int,
    message: str,
    *,
    stage: AnalysisStage = AnalysisStage.PREFLIGHT,
    stage_percent: int = 0,
    completed_units: int = 0,
    total_units: int = 0,
    candidate_count: int = 0,
    failed_units: int = 0,
    repaired_units: int = 0,
    cache_hits: int = 0,
    resumed_units: int = 0,
    eta_seconds: float | None = None,
    device: str = "",
) -> None:
    normalized_percent = max(0, min(100, int(percent)))
    normalized_message = str(message)
    callback = state.get("progress_callback")
    if callback is not None:
        callback(normalized_percent, normalized_message)
    event_callback = state.get("event_callback")
    if event_callback is not None:
        elapsed = max(0.0, perf_counter() - state.get("started_monotonic", perf_counter()))
        event_callback(
            AnalysisProgressEvent(
                stage=stage,
                overall_percent=normalized_percent,
                stage_percent=max(0, min(100, int(stage_percent))),
                message=normalized_message,
                completed_units=completed_units,
                total_units=total_units,
                candidate_count=candidate_count,
                failed_units=failed_units,
                repaired_units=repaired_units,
                cache_hits=cache_hits,
                resumed_units=resumed_units,
                elapsed_seconds=elapsed,
                eta_seconds=eta_seconds,
                device=device,
            )
        )


def _stage_progress(state: AnalysisState, stage: AnalysisStage):
    ranges = {
        AnalysisStage.PREFLIGHT: (0, 5),
        AnalysisStage.TEXT_EVIDENCE: (5, 15),
        AnalysisStage.COARSE_SAMPLING: (15, 25),
        AnalysisStage.PREFILTER: (25, 45),
        AnalysisStage.CANDIDATE_PLANNING: (45, 48),
        AnalysisStage.VLM_REVIEW: (48, 95),
        AnalysisStage.FUSION: (95, 98),
        AnalysisStage.PERSISTENCE: (98, 100),
    }
    start, end = ranges[stage]

    def publish(percent, message):
        local_percent = max(0, min(100, int(percent)))
        overall = start + int((end - start) * local_percent / 100)
        _emit(
            state,
            overall,
            message,
            stage=stage,
            stage_percent=local_percent,
        )

    return publish


def _text_candidate_windows(text_evidence) -> list[CandidateWindow]:
    windows: list[CandidateWindow] = []
    for index, evidence in enumerate(text_evidence):
        midpoint = (evidence.start_seconds + evidence.end_seconds) / 2.0
        windows.append(
            CandidateWindow(
                window_id=f"text-{index:05d}",
                start_seconds=evidence.start_seconds,
                end_seconds=evidence.end_seconds,
                peak_probability=0.0,
                evidence_timestamps=[midpoint],
                trigger="text",
            )
        )
    return windows


def _candidate_batches(
    batches: list[VisualBatch],
    candidates: list[CandidateWindow],
) -> list[VisualBatch]:
    return [
        batch
        for batch in batches
        if any(
            batch.end_seconds >= candidate.start_seconds
            and batch.start_seconds <= candidate.end_seconds
            for candidate in candidates
        )
    ]


def _visual_evidence_from_response(
    response: VLMReviewResponse,
    batch: VisualBatch,
) -> list[VisualEvidence]:
    return [
        VisualEvidence(
            batch_id=batch.batch_id,
            category=item.category,
            confidence=item.confidence,
            start_seconds=item.start_seconds,
            end_seconds=item.end_seconds,
            evidence_timestamps=item.evidence_timestamps,
            reason=item.reason,
            needs_review=True,
        )
        for item in response.suggestions
    ]


def _save_failed_batch_checkpoint(
    cache: AnalysisCache,
    analysis_cache_key: str,
    batch_key: str,
    batch: VisualBatch,
    settings,
    error: Exception,
    attempt_count: int,
    inference_seconds: float,
) -> None:
    raw_output = str(getattr(error, "raw_output", "") or "")[:16384] or None
    repaired_output = str(getattr(error, "repaired_output", "") or "")[:16384] or None
    try:
        cache.save_batch_checkpoint(
            BatchCheckpoint(
                analysis_cache_key=analysis_cache_key,
                batch_key=batch_key,
                batch_id=batch.batch_id,
                start_seconds=batch.start_seconds,
                end_seconds=batch.end_seconds,
                frame_timestamps=[frame.timestamp_seconds for frame in batch.frames],
                prompt_schema_version=str(settings.prompt_schema_revision),
                model_id=settings.model_id,
                model_revision=settings.model_revision,
                status=BatchCheckpointStatus.FAILED,
                error=_diagnostic("Batch inference failed", error),
                raw_output=raw_output,
                repaired_output=repaired_output,
                repaired=bool(getattr(error, "repaired", False)),
                stop_reason=str(getattr(error, "stop_reason", "failed") or "failed")[:128],
                attempt_count=attempt_count,
                inference_seconds=max(0.0, inference_seconds),
            )
        )
    except (OSError, ValueError):
        logger.warning("Unable to persist failed VLM batch checkpoint", exc_info=True)


def _provider_device_text(
    diagnostics: ProviderDiagnostics | dict | None,
    provider,
) -> str:
    candidate = diagnostics or getattr(provider, "diagnostics", None)
    if isinstance(candidate, dict):
        try:
            candidate = ProviderDiagnostics.model_validate(candidate)
        except Exception:
            candidate = None
    if not isinstance(candidate, ProviderDiagnostics):
        return ""
    base = {
        "cuda": "GPU",
        "hybrid": "GPU + CPU offload",
        "cpu": "CPU",
        "unavailable": "",
    }[candidate.device_mode]
    quantization = candidate.quantization.strip()
    return " ".join(part for part in (base, quantization) if part).strip()


def _trace_metadata(state: AnalysisState) -> dict:
    request = state["request"]
    preflight = state.get("preflight")
    metadata = {
        "model_id": request.settings.model_id,
        "model_revision": request.settings.model_revision,
        "settings_version": request.settings.settings_version,
    }
    if preflight is not None:
        metadata.update(
            video_fingerprint=preflight.video_fingerprint,
            duration_seconds=preflight.media.duration_seconds,
        )
    return metadata


def _start_trace(state: AnalysisState, services: AnalysisServices, node_name: str):
    return services.tracer.start_node(node_name, _trace_metadata(state))


def _finish_trace(
    run_id,
    services: AnalysisServices,
    state: AnalysisState,
    metadata: dict,
    error: Exception | None = None,
) -> None:
    services.tracer.finish_node(
        run_id,
        {**_trace_metadata(state), **metadata},
        error=error,
    )


def _diagnostic(prefix: str, error: Exception) -> str:
    detail = redact_sensitive_text(" ".join(str(error or "").split()), limit=500)
    return f"{prefix}: {detail}" if detail else prefix


def _completion_message(record: AnalysisRecord) -> str:
    count = len(record.suggestions)
    if record.status == AnalysisStatus.PARTIAL:
        return f"Analysis completed with warnings: {count} suggestion(s)"
    return f"Analysis completed: {count} suggestion(s)"


def _remove_workspace(workspace: Path | None, work_root: Path) -> None:
    if workspace is None:
        return
    try:
        resolved_workspace = workspace.resolve()
        resolved_root = work_root.resolve()
        if resolved_workspace.parent != resolved_root:
            logger.warning("Refusing to remove analysis workspace outside the cache root")
            return
        shutil.rmtree(resolved_workspace, ignore_errors=True)
    except OSError:
        logger.warning("Unable to clean analysis workspace", exc_info=True)
