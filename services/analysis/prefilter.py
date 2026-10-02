from __future__ import annotations

import gc
import logging
import math
import os
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from importlib.util import find_spec
from itertools import pairwise
from pathlib import Path

from core.paths import get_model_cache_dir
from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    DEFAULT_PREFILTER_MODEL_ID,
    DEFAULT_PREFILTER_MODEL_REVISION,
    AnalysisSettings,
    CandidateWindow,
    PrefilterFrameScore,
    SampledFrame,
)
from services.analysis.providers.prefilter_base import (
    PrefilterDiagnostics,
    PrefilterProgressCallback,
    PrefilterProviderError,
    PrefilterProviderUnavailableError,
)

logger = logging.getLogger(__name__)
_MIN_WINDOW_SECONDS = 0.001
_INTERVAL_EPSILON = 1e-9


@dataclass
class _CandidateSeed:
    start_seconds: float
    end_seconds: float
    peak_probability: float
    evidence_timestamps: list[float] = field(default_factory=list)
    has_visual: bool = False
    has_text: bool = False


def group_candidate_windows(
    scores: Sequence[PrefilterFrameScore],
    *,
    duration_seconds: float,
    settings: AnalysisSettings,
    text_windows: Sequence[CandidateWindow] = (),
) -> list[CandidateWindow]:
    """Build deterministic, path-free candidate windows for dense VLM review.

    The classifier is deliberately only a recall-oriented gate. Text windows can
    widen or create a candidate, but neither input becomes final visual evidence.
    """

    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("candidate planning requires a finite positive duration")

    threshold = settings.resolved_prefilter_threshold
    seeds: list[_CandidateSeed] = []
    for score in scores:
        if (
            score.nsfw_probability < threshold
            and not score.conservatively_included
        ):
            continue
        timestamp = _clamp(float(score.frame.timestamp_seconds), 0.0, duration)
        seeds.append(
            _CandidateSeed(
                start_seconds=timestamp,
                end_seconds=timestamp,
                peak_probability=float(score.nsfw_probability),
                evidence_timestamps=[timestamp],
                has_visual=True,
            )
        )

    for window in text_windows:
        start = _clamp(float(window.start_seconds), 0.0, duration)
        end = _clamp(float(window.end_seconds), 0.0, duration)
        if end <= start:
            continue
        evidence = [
            float(timestamp)
            for timestamp in window.evidence_timestamps
            if math.isfinite(float(timestamp)) and 0.0 <= float(timestamp) <= duration
        ]
        seeds.append(
            _CandidateSeed(
                start_seconds=start,
                end_seconds=end,
                peak_probability=float(window.peak_probability),
                evidence_timestamps=evidence,
                has_visual=window.trigger in {"visual", "visual_and_text"},
                has_text=True,
            )
        )

    if not seeds:
        return []

    grouped = _merge_seeds(seeds, settings.candidate_gap_seconds)
    padded = [
        _CandidateSeed(
            start_seconds=max(
                0.0,
                seed.start_seconds - settings.candidate_padding_seconds,
            ),
            end_seconds=min(
                duration,
                seed.end_seconds + settings.candidate_padding_seconds,
            ),
            peak_probability=seed.peak_probability,
            evidence_timestamps=seed.evidence_timestamps,
            has_visual=seed.has_visual,
            has_text=seed.has_text,
        )
        for seed in grouped
    ]
    # Padding can make separately grouped candidates overlap. Collapse those
    # overlaps so the dense sampler and VLM never review the same time twice.
    padded = _merge_seeds(padded, 0.0)

    split_seeds: list[_CandidateSeed] = []
    for seed in padded:
        start, end = _ensure_nonzero_interval(
            seed.start_seconds,
            seed.end_seconds,
            duration,
        )
        split_seeds.extend(
            _split_seed(
                _CandidateSeed(
                    start_seconds=start,
                    end_seconds=end,
                    peak_probability=seed.peak_probability,
                    evidence_timestamps=seed.evidence_timestamps,
                    has_visual=seed.has_visual,
                    has_text=seed.has_text,
                ),
                settings.max_candidate_window_seconds,
            )
        )

    windows: list[CandidateWindow] = []
    for index, seed in enumerate(split_seeds):
        windows.append(
            CandidateWindow(
                window_id=f"candidate-{index:05d}",
                start_seconds=seed.start_seconds,
                end_seconds=seed.end_seconds,
                peak_probability=seed.peak_probability,
                evidence_timestamps=sorted(set(seed.evidence_timestamps)),
                trigger=_trigger(seed),
            )
        )
    return windows


# Kept as a descriptive compatibility alias for callers written against the
# design prototype. New pipeline code should use ``group_candidate_windows``.
build_candidate_windows = group_candidate_windows


class LocalNSFWPrefilter:
    """Pinned, local-only Marqo NSFW classifier with conservative failure handling."""

    def __init__(self, model_cache_dir: str | Path | None = None) -> None:
        self.model_cache_dir = (
            Path(model_cache_dir) if model_cache_dir is not None else get_model_cache_dir()
        )
        self._configured_model_id = DEFAULT_PREFILTER_MODEL_ID
        self._configured_model_revision = DEFAULT_PREFILTER_MODEL_REVISION
        self._processor = None
        self._model = None
        self._torch = None
        self._loaded_key: tuple[str, str, bool] | None = None
        self._device = "cpu"
        self._device_name = ""
        self._precision = "float32"
        self._nsfw_label_index: int | None = None
        self._warnings: list[str] = []
        self._diagnostics = self._new_diagnostics()

    @property
    def model_id(self) -> str:
        return self._configured_model_id

    @property
    def model_revision(self) -> str:
        return self._configured_model_revision

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def diagnostics(self) -> PrefilterDiagnostics:
        return self._diagnostics.model_copy(deep=True)

    def check_ready(
        self,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> None:
        """Validate dependencies and the pinned cache without loading weights."""

        cancellation.raise_if_cancelled()
        self._set_configured_model(settings)
        missing = [
            module_name
            for module_name in ("torch", "transformers", "timm", "PIL")
            if find_spec(module_name) is None
        ]
        if missing:
            raise PrefilterProviderUnavailableError(
                "The local NSFW prefilter dependencies are unavailable "
                f"({', '.join(missing)}). Install requirements-ai.txt before analysis."
            )
        if _environment_flag("NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD"):
            return

        try:
            from huggingface_hub import try_to_load_from_cache
        except ImportError as exc:
            raise PrefilterProviderUnavailableError(
                "huggingface-hub is unavailable. Install requirements-ai.txt before "
                "analysis."
            ) from exc

        for filename in ("config.json", "model.safetensors"):
            cancellation.raise_if_cancelled()
            _cached_prefilter_file(
                try_to_load_from_cache,
                settings,
                self.model_cache_dir,
                filename,
            )

    def score_frames(
        self,
        frames: Sequence[SampledFrame],
        settings: AnalysisSettings,
        cancellation: CancellationToken,
        progress_callback: PrefilterProgressCallback | None = None,
    ) -> list[PrefilterFrameScore]:
        cancellation.raise_if_cancelled()
        ordered_frames = list(frames)
        self._warnings = []
        self._set_configured_model(settings)
        self._diagnostics = self._new_diagnostics(frame_count=len(ordered_frames))
        if not ordered_frames:
            return []

        self._ensure_loaded(settings, cancellation)
        results: list[PrefilterFrameScore] = []
        successful_count = 0
        failed_chunk_count = 0
        conservative_count = 0
        batch_size = settings.prefilter_batch_size

        for offset in range(0, len(ordered_frames), batch_size):
            cancellation.raise_if_cancelled()
            chunk = ordered_frames[offset : offset + batch_size]
            try:
                probabilities = self._score_chunk(chunk, cancellation)
                chunk_scores = [
                    PrefilterFrameScore(
                        frame=frame,
                        nsfw_probability=probability,
                    )
                    for frame, probability in zip(
                        chunk,
                        probabilities,
                        strict=True,
                    )
                ]
                successful_count += len(chunk_scores)
            except AnalysisCancelled:
                raise
            except Exception as exc:
                failed_chunk_count += 1
                conservative_count += len(chunk)
                warning = (
                    f"NSFW prefilter chunk {offset // batch_size + 1} failed "
                    f"({type(exc).__name__}); {len(chunk)} frames were included "
                    "conservatively."
                )
                logger.warning(warning, exc_info=True)
                self._warnings.append(warning)
                chunk_scores = [
                    PrefilterFrameScore(
                        frame=frame,
                        nsfw_probability=1.0,
                        conservatively_included=True,
                    )
                    for frame in chunk
                ]
            results.extend(chunk_scores)
            self._diagnostics = self._diagnostics.model_copy(
                update={
                    "successful_frame_count": successful_count,
                    "failed_chunk_count": failed_chunk_count,
                    "conservatively_included_count": conservative_count,
                }
            )
            cancellation.raise_if_cancelled()
            if progress_callback is not None:
                completed = min(len(ordered_frames), offset + len(chunk))
                progress_callback(
                    int(completed * 100 / len(ordered_frames)),
                    f"Classified {completed} of {len(ordered_frames)} sampled frames",
                )

        return results

    def release(self) -> None:
        """Release classifier references and CUDA cache before the VLM is loaded."""

        model = self._model
        torch_module = self._torch
        self._processor = None
        self._model = None
        self._torch = None
        self._loaded_key = None
        self._nsfw_label_index = None
        if model is not None:
            try:
                model.to("cpu")
            except Exception:
                logger.debug("Unable to move the released prefilter to CPU", exc_info=True)
        del model
        gc.collect()
        if torch_module is not None:
            try:
                if torch_module.cuda.is_available():
                    torch_module.cuda.empty_cache()
            except Exception:
                logger.debug("Unable to clear the prefilter CUDA cache", exc_info=True)

    def _ensure_loaded(
        self,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> None:
        loaded_key = (
            settings.prefilter_model_id,
            settings.prefilter_model_revision,
            settings.use_gpu,
        )
        if self._loaded_key == loaded_key:
            self._diagnostics = self._diagnostics.model_copy(
                update={
                    "device_mode": self._device,
                    "device_name": self._device_name,
                    "precision": self._precision,
                }
            )
            return
        if self._model is not None:
            self.release()
        self.check_ready(settings, cancellation)

        try:
            import torch
            from transformers import (
                AutoImageProcessor,
                AutoModelForImageClassification,
            )
        except ImportError as exc:
            raise PrefilterProviderUnavailableError(
                "The local NSFW prefilter dependencies are unavailable. Install "
                "requirements-ai.txt before running analysis."
            ) from exc

        allow_download = _environment_flag("NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD")
        common_kwargs = {
            "cache_dir": str(self.model_cache_dir),
            "revision": settings.prefilter_model_revision,
            "local_files_only": not allow_download,
        }
        cancellation.raise_if_cancelled()
        try:
            processor = AutoImageProcessor.from_pretrained(
                settings.prefilter_model_id,
                **common_kwargs,
            )
            cancellation.raise_if_cancelled()
            model = AutoModelForImageClassification.from_pretrained(
                settings.prefilter_model_id,
                use_safetensors=True,
                **common_kwargs,
            )
        except AnalysisCancelled:
            raise
        except Exception as exc:
            raise PrefilterProviderUnavailableError(
                _model_load_error(
                    settings.prefilter_model_id,
                    allow_download,
                    exc,
                )
            ) from exc
        cancellation.raise_if_cancelled()

        label_index = _resolve_nsfw_label_index(model.config)
        use_cuda = bool(settings.use_gpu and torch.cuda.is_available())
        device = "cuda" if use_cuda else "cpu"
        precision = "float16" if use_cuda else "float32"
        device_name = ""
        try:
            if use_cuda:
                model.to(device="cuda", dtype=torch.float16)
                device_name = str(torch.cuda.get_device_name(0))
            else:
                model.to(device="cpu", dtype=torch.float32)
        except Exception as cuda_or_cpu_exc:
            if not use_cuda:
                raise PrefilterProviderUnavailableError(
                    "Unable to initialize the local NSFW prefilter on CPU "
                    f"({type(cuda_or_cpu_exc).__name__})."
                ) from cuda_or_cpu_exc
            warning = (
                "CUDA prefilter initialization failed; using the CPU fallback."
            )
            logger.warning(warning, exc_info=True)
            self._warnings.append(warning)
            try:
                torch.cuda.empty_cache()
                model.to(device="cpu", dtype=torch.float32)
            except Exception as cpu_exc:
                raise PrefilterProviderUnavailableError(
                    "Unable to initialize the local NSFW prefilter on either CUDA or "
                    f"CPU ({type(cpu_exc).__name__})."
                ) from cpu_exc
            device = "cpu"
            precision = "float32"
            device_name = ""

        if settings.use_gpu and not use_cuda:
            warning = "CUDA is unavailable; the NSFW prefilter is using CPU inference."
            logger.warning(warning)
            self._warnings.append(warning)

        model.eval()
        self._processor = processor
        self._model = model
        self._torch = torch
        self._loaded_key = loaded_key
        self._device = device
        self._device_name = device_name
        self._precision = precision
        self._nsfw_label_index = label_index
        self._diagnostics = self._diagnostics.model_copy(
            update={
                "device_mode": device,
                "device_name": device_name,
                "precision": precision,
            }
        )
        cancellation.raise_if_cancelled()

    def _score_chunk(
        self,
        frames: Sequence[SampledFrame],
        cancellation: CancellationToken,
    ) -> list[float]:
        if (
            self._processor is None
            or self._model is None
            or self._torch is None
            or self._nsfw_label_index is None
        ):
            raise PrefilterProviderError("The NSFW prefilter is not loaded")

        from PIL import Image

        images = []
        for frame in frames:
            cancellation.raise_if_cancelled()
            with Image.open(frame.path) as image:
                images.append(image.convert("RGB"))

        try:
            inputs = self._processor(images=images, return_tensors="pt")
        finally:
            for image in images:
                image.close()
        moved_inputs = {}
        for name, value in inputs.items():
            if not self._torch.is_tensor(value):
                moved_inputs[name] = value
                continue
            move_kwargs = {
                "device": self._device,
                "non_blocking": self._device == "cuda",
            }
            if value.is_floating_point():
                move_kwargs["dtype"] = (
                    self._torch.float16
                    if self._device == "cuda"
                    else self._torch.float32
                )
            moved_inputs[name] = value.to(**move_kwargs)

        autocast = (
            self._torch.autocast(
                device_type="cuda",
                dtype=self._torch.float16,
            )
            if self._device == "cuda"
            else nullcontext()
        )
        with self._torch.inference_mode(), autocast:
            output = self._model(**moved_inputs)
        logits = getattr(output, "logits", None)
        if logits is None:
            raise PrefilterProviderError("The prefilter did not return classification logits")
        probabilities = (
            logits.float()
            .softmax(dim=-1)[:, self._nsfw_label_index]
            .detach()
            .cpu()
            .tolist()
        )
        if len(probabilities) != len(frames):
            raise PrefilterProviderError(
                "The prefilter returned a different number of scores than input frames"
            )
        normalized = [float(value) for value in probabilities]
        if any(
            not math.isfinite(value) or value < 0.0 or value > 1.0
            for value in normalized
        ):
            raise PrefilterProviderError("The prefilter returned an invalid probability")
        return normalized

    def _set_configured_model(self, settings: AnalysisSettings) -> None:
        self._configured_model_id = settings.prefilter_model_id
        self._configured_model_revision = settings.prefilter_model_revision
        self._diagnostics = self._diagnostics.model_copy(
            update={
                "model_id": self._configured_model_id,
                "model_revision": self._configured_model_revision,
            }
        )

    def _new_diagnostics(self, *, frame_count: int = 0) -> PrefilterDiagnostics:
        return PrefilterDiagnostics(
            model_id=self._configured_model_id,
            model_revision=self._configured_model_revision,
            frame_count=frame_count,
        )


def _merge_seeds(
    seeds: Sequence[_CandidateSeed],
    gap_seconds: float,
) -> list[_CandidateSeed]:
    ordered = sorted(
        seeds,
        key=lambda seed: (
            seed.start_seconds,
            seed.end_seconds,
            not seed.has_visual,
            not seed.has_text,
            tuple(sorted(seed.evidence_timestamps)),
        ),
    )
    merged: list[_CandidateSeed] = []
    for seed in ordered:
        candidate = _CandidateSeed(
            start_seconds=seed.start_seconds,
            end_seconds=seed.end_seconds,
            peak_probability=seed.peak_probability,
            evidence_timestamps=list(seed.evidence_timestamps),
            has_visual=seed.has_visual,
            has_text=seed.has_text,
        )
        if (
            not merged
            or candidate.start_seconds
            > merged[-1].end_seconds + gap_seconds + _INTERVAL_EPSILON
        ):
            merged.append(candidate)
            continue
        current = merged[-1]
        current.end_seconds = max(current.end_seconds, candidate.end_seconds)
        current.peak_probability = max(
            current.peak_probability,
            candidate.peak_probability,
        )
        current.evidence_timestamps = sorted(
            set(current.evidence_timestamps + candidate.evidence_timestamps)
        )
        current.has_visual = current.has_visual or candidate.has_visual
        current.has_text = current.has_text or candidate.has_text
    return merged


def _split_seed(seed: _CandidateSeed, maximum_seconds: float) -> list[_CandidateSeed]:
    boundaries = [seed.start_seconds]
    cursor = seed.start_seconds
    while seed.end_seconds - cursor > maximum_seconds + _INTERVAL_EPSILON:
        cursor += maximum_seconds
        boundaries.append(cursor)
    boundaries.append(seed.end_seconds)

    results = []
    for index, (start, end) in enumerate(pairwise(boundaries)):
        is_last = index == len(boundaries) - 2
        evidence = [
            timestamp
            for timestamp in seed.evidence_timestamps
            if timestamp >= start - _INTERVAL_EPSILON
            and (
                timestamp < end - _INTERVAL_EPSILON
                or (is_last and timestamp <= end + _INTERVAL_EPSILON)
            )
        ]
        results.append(
            _CandidateSeed(
                start_seconds=start,
                end_seconds=end,
                peak_probability=seed.peak_probability,
                evidence_timestamps=evidence,
                has_visual=seed.has_visual,
                has_text=seed.has_text,
            )
        )
    return results


def _ensure_nonzero_interval(
    start_seconds: float,
    end_seconds: float,
    duration_seconds: float,
) -> tuple[float, float]:
    if end_seconds - start_seconds >= _MIN_WINDOW_SECONDS:
        return start_seconds, end_seconds
    if end_seconds + _MIN_WINDOW_SECONDS <= duration_seconds:
        return start_seconds, end_seconds + _MIN_WINDOW_SECONDS
    return max(0.0, start_seconds - _MIN_WINDOW_SECONDS), end_seconds


def _trigger(seed: _CandidateSeed) -> str:
    if seed.has_visual and seed.has_text:
        return "visual_and_text"
    if seed.has_text:
        return "text"
    return "visual"


def _resolve_nsfw_label_index(config) -> int:
    id_to_label = getattr(config, "id2label", None) or {}
    for raw_index, raw_label in id_to_label.items():
        if str(raw_label).strip().casefold() == "nsfw":
            return int(raw_index)
    label_to_id = getattr(config, "label2id", None) or {}
    for raw_label, raw_index in label_to_id.items():
        if str(raw_label).strip().casefold() == "nsfw":
            return int(raw_index)
    raise PrefilterProviderUnavailableError(
        "The pinned NSFW prefilter does not expose the required 'NSFW' label."
    )


def _cached_prefilter_file(
    cache_lookup,
    settings: AnalysisSettings,
    cache_dir: Path,
    filename: str,
) -> Path:
    cached = cache_lookup(
        settings.prefilter_model_id,
        filename,
        cache_dir=str(cache_dir),
        revision=settings.prefilter_model_revision,
    )
    if not isinstance(cached, str) or not Path(cached).is_file():
        raise PrefilterProviderUnavailableError(
            f"Local NSFW prefilter '{settings.prefilter_model_id}' is not available "
            "at the pinned revision in the user model cache. Set "
            "NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD=1 for an explicit setup download."
        )
    return Path(cached)


def _model_load_error(model_id: str, allow_download: bool, error: Exception) -> str:
    if allow_download:
        return f"Unable to load local NSFW prefilter '{model_id}' ({type(error).__name__})."
    return (
        f"Local NSFW prefilter '{model_id}' is not available in the user model cache. "
        "Download it during setup or set NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD=1 "
        "for an explicit first-run download."
    )


def _environment_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
