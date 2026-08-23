from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.paths import get_analysis_cache_dir
from services.analysis.contracts import (
    AnalysisRecord,
    AnalysisSettings,
    AnalysisStatus,
    VisualBatch,
    SampledFrame,
    VLMReviewResponse,
)

logger = logging.getLogger(__name__)

_DIGEST_LENGTH = 64
_DIGEST_CHARACTERS = frozenset("0123456789abcdef")
_MAX_CAPTURED_OUTPUT_CHARACTERS = 16 * 1024


class BatchCheckpointStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisBatchCheckpoint(BaseModel):
    """Durable result for one VLM batch.

    Checkpoints intentionally represent terminal batch states only. An interrupted
    write therefore leaves either the previous valid checkpoint or no checkpoint,
    and a resumed run can safely treat the latter as pending work.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    analysis_cache_key: str = Field(min_length=_DIGEST_LENGTH, max_length=_DIGEST_LENGTH)
    batch_key: str = Field(min_length=_DIGEST_LENGTH, max_length=_DIGEST_LENGTH)
    batch_id: str = Field(min_length=1, max_length=256)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    frame_timestamps: list[float] = Field(min_length=1)
    prompt_schema_version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=512)
    model_revision: str = Field(min_length=1, max_length=256)
    status: BatchCheckpointStatus
    response: VLMReviewResponse | None = None
    error: str | None = Field(default=None, max_length=1000)
    raw_output: str | None = Field(
        default=None,
        max_length=_MAX_CAPTURED_OUTPUT_CHARACTERS,
    )
    repaired_output: str | None = Field(
        default=None,
        max_length=_MAX_CAPTURED_OUTPUT_CHARACTERS,
    )
    repaired: bool = False
    stop_reason: str | None = Field(default=None, max_length=128)
    attempt_count: int = Field(default=1, ge=1)
    inference_seconds: float | None = Field(default=None, ge=0.0)
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def valid_terminal_state(self):
        self.analysis_cache_key = _normalize_digest(
            self.analysis_cache_key,
            "analysis cache key",
        )
        self.batch_key = _normalize_digest(self.batch_key, "batch checkpoint key")
        self.batch_id = self.batch_id.strip()
        self.prompt_schema_version = self.prompt_schema_version.strip()
        self.model_id = self.model_id.strip()
        self.model_revision = self.model_revision.strip()
        self.error = str(self.error).strip() if self.error is not None else None
        self.stop_reason = (
            str(self.stop_reason).strip() if self.stop_reason is not None else None
        )

        if not self.batch_id:
            raise ValueError("batch id cannot be blank")
        if not self.prompt_schema_version:
            raise ValueError("prompt schema version cannot be blank")
        if not self.model_id or not self.model_revision:
            raise ValueError("model identifiers cannot be blank")
        if self.stop_reason == "":
            raise ValueError("stop reason cannot be blank")
        if self.end_seconds < self.start_seconds:
            raise ValueError("batch checkpoint end cannot precede start")
        if any(
            not math.isfinite(timestamp) or timestamp < 0.0
            for timestamp in self.frame_timestamps
        ):
            raise ValueError("frame timestamps must be finite and non-negative")

        if self.status == BatchCheckpointStatus.COMPLETED:
            if self.response is None:
                raise ValueError("completed batch checkpoint requires a response")
            if self.error:
                raise ValueError("completed batch checkpoint cannot contain an error")
        elif self.status == BatchCheckpointStatus.FAILED:
            if self.response is not None:
                raise ValueError("failed batch checkpoint cannot contain a response")
            if not self.error:
                raise ValueError("failed batch checkpoint requires an error")
        return self


# Concise public name used by pipeline integrations. Keep the longer name as a
# compatibility alias for callers/tests written while the cache API was introduced.
BatchCheckpoint = AnalysisBatchCheckpoint


class PrefilterScoreItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp_seconds: float = Field(ge=0.0)
    nsfw_probability: float = Field(ge=0.0, le=1.0)
    conservatively_included: bool = False

    @model_validator(mode="after")
    def finite_values(self):
        if not math.isfinite(self.timestamp_seconds) or not math.isfinite(
            self.nsfw_probability
        ):
            raise ValueError("prefilter checkpoint values must be finite")
        return self


class PrefilterCheckpoint(BaseModel):
    """Path-free, durable classifier scores for deterministic coarse timestamps."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    analysis_cache_key: str = Field(min_length=_DIGEST_LENGTH, max_length=_DIGEST_LENGTH)
    score_key: str = Field(min_length=_DIGEST_LENGTH, max_length=_DIGEST_LENGTH)
    model_id: str = Field(min_length=1, max_length=512)
    model_revision: str = Field(min_length=1, max_length=256)
    scores: list[PrefilterScoreItem] = Field(min_length=1)
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def normalized_values(self):
        self.analysis_cache_key = _normalize_digest(
            self.analysis_cache_key,
            "analysis cache key",
        )
        self.score_key = _normalize_digest(self.score_key, "prefilter checkpoint key")
        self.model_id = self.model_id.strip()
        self.model_revision = self.model_revision.strip()
        if not self.model_id or not self.model_revision:
            raise ValueError("prefilter model identifiers cannot be blank")
        timestamps = [item.timestamp_seconds for item in self.scores]
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise ValueError("prefilter checkpoint timestamps must be sorted and unique")
        return self


class AnalysisCache:
    """Versioned JSON result cache stored in the app's per-user cache directory."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else get_analysis_cache_dir()
        self.records_dir = self.root / "records"
        self.checkpoints_dir = self.root / "checkpoints"
        self.prefilter_dir = self.root / "prefilter"
        self.work_dir = self.root / "work"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.prefilter_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(
        video_fingerprint: str,
        settings: AnalysisSettings,
        text_source_fingerprint: str = "audio-fallback:v1",
    ) -> str:
        payload = {
            "video_fingerprint": video_fingerprint,
            "text_source_fingerprint": text_source_fingerprint,
            "model_id": settings.model_id,
            "model_revision": settings.model_revision,
            "settings": settings.model_dump(mode="json"),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record_path(self, cache_key: str) -> Path:
        normalized = _normalize_digest(cache_key, "analysis cache key")
        return self.records_dir / f"{normalized}.json"

    @staticmethod
    def make_batch_key(
        analysis_cache_key: str,
        batch: VisualBatch,
        settings: AnalysisSettings,
        *,
        prompt_schema_version: str,
    ) -> str:
        """Return a stable content key for a VLM batch.

        Image paths and the display-only batch id are deliberately excluded. The
        analysis key identifies the media/configuration, while ordered timestamps
        identify the actual visual inputs. The full model settings payload and an
        explicit prompt-schema revision make prompt/model changes invalidate only
        the affected checkpoints.
        """

        normalized_cache_key = _normalize_digest(
            analysis_cache_key,
            "analysis cache key",
        )
        normalized_prompt_version = str(prompt_schema_version).strip()
        if not normalized_prompt_version:
            raise ValueError("prompt schema version cannot be empty")
        payload = {
            "key_version": 1,
            "analysis_cache_key": normalized_cache_key,
            "batch": {
                "start_seconds": _canonical_float(batch.start_seconds),
                "end_seconds": _canonical_float(batch.end_seconds),
                "frame_timestamps": [
                    _canonical_float(frame.timestamp_seconds) for frame in batch.frames
                ],
            },
            "prompt_schema_version": normalized_prompt_version,
            "model_settings": settings.model_dump(mode="json"),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def make_prefilter_key(
        analysis_cache_key: str,
        frames: list[SampledFrame],
        settings: AnalysisSettings,
    ) -> str:
        normalized_cache_key = _normalize_digest(
            analysis_cache_key,
            "analysis cache key",
        )
        payload = {
            "key_version": 1,
            "analysis_cache_key": normalized_cache_key,
            "model_id": settings.prefilter_model_id,
            "model_revision": settings.prefilter_model_revision,
            "sampling_profile_revision": settings.sampling_profile_revision,
            "timestamps": [
                _canonical_float(frame.timestamp_seconds)
                for frame in sorted(frames, key=lambda item: item.timestamp_seconds)
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def batch_checkpoint_path(
        self,
        analysis_cache_key: str,
        batch_key: str,
    ) -> Path:
        normalized_cache_key = _normalize_digest(
            analysis_cache_key,
            "analysis cache key",
        )
        normalized_batch_key = _normalize_digest(batch_key, "batch checkpoint key")
        return self.checkpoints_dir / normalized_cache_key / f"{normalized_batch_key}.json"

    def load(self, cache_key: str, *, reusable_only: bool = True) -> AnalysisRecord | None:
        path = self.record_path(cache_key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = AnalysisRecord.model_validate(payload)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
            logger.warning("Ignoring invalid VLM analysis cache record: %s", path.name)
            return None

        if reusable_only and record.status != AnalysisStatus.COMPLETED:
            return None
        return record

    def save(self, cache_key: str, record: AnalysisRecord) -> Path:
        path = self.record_path(cache_key)
        _atomic_write(path, record.model_dump_json(indent=2))
        return path

    def save_preserving_completed(
        self,
        cache_key: str,
        record: AnalysisRecord,
    ) -> Path:
        """Save an attempt without replacing an existing completed final result.

        Callers should use this explicit method for partial, cancelled, or failed
        terminal attempts. ``save`` intentionally retains its original replacement
        semantics for callers that knowingly want to replace the final record.
        """

        path = self.record_path(cache_key)
        if record.status != AnalysisStatus.COMPLETED:
            existing = self.load(cache_key, reusable_only=False)
            if existing is not None and existing.status == AnalysisStatus.COMPLETED:
                logger.info(
                    "Preserving completed VLM analysis cache record: %s",
                    path.name,
                )
                return path
        return self.save(cache_key, record)

    def load_batch_checkpoint(
        self,
        analysis_cache_key: str,
        batch_key: str,
    ) -> AnalysisBatchCheckpoint | None:
        path = self.batch_checkpoint_path(analysis_cache_key, batch_key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = AnalysisBatchCheckpoint.model_validate(payload)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
            logger.warning("Ignoring invalid VLM batch checkpoint: %s", path.name)
            return None

        normalized_cache_key = _normalize_digest(
            analysis_cache_key,
            "analysis cache key",
        )
        normalized_batch_key = _normalize_digest(batch_key, "batch checkpoint key")
        if (
            checkpoint.analysis_cache_key != normalized_cache_key
            or checkpoint.batch_key != normalized_batch_key
        ):
            logger.warning("Ignoring mismatched VLM batch checkpoint: %s", path.name)
            return None
        return checkpoint

    def load_batch_checkpoints(
        self,
        analysis_cache_key: str,
    ) -> dict[str, AnalysisBatchCheckpoint]:
        """Load all valid batch checkpoints without one corrupt file aborting resume."""

        normalized_cache_key = _normalize_digest(
            analysis_cache_key,
            "analysis cache key",
        )
        directory = self.checkpoints_dir / normalized_cache_key
        if not directory.is_dir():
            return {}

        checkpoints: dict[str, AnalysisBatchCheckpoint] = {}
        for path in sorted(directory.glob("*.json")):
            try:
                batch_key = _normalize_digest(path.stem, "batch checkpoint key")
            except ValueError:
                logger.warning("Ignoring invalid VLM batch checkpoint name: %s", path.name)
                continue
            checkpoint = self.load_batch_checkpoint(normalized_cache_key, batch_key)
            if checkpoint is not None:
                checkpoints[batch_key] = checkpoint
        return checkpoints

    def save_batch_checkpoint(
        self,
        checkpoint: AnalysisBatchCheckpoint,
    ) -> Path:
        path = self.batch_checkpoint_path(
            checkpoint.analysis_cache_key,
            checkpoint.batch_key,
        )
        _atomic_write(path, checkpoint.model_dump_json(indent=2))
        return path

    def prefilter_checkpoint_path(
        self,
        analysis_cache_key: str,
        score_key: str,
    ) -> Path:
        normalized_cache_key = _normalize_digest(
            analysis_cache_key,
            "analysis cache key",
        )
        normalized_score_key = _normalize_digest(score_key, "prefilter checkpoint key")
        return self.prefilter_dir / normalized_cache_key / f"{normalized_score_key}.json"

    def load_prefilter_checkpoint(
        self,
        analysis_cache_key: str,
        score_key: str,
    ) -> PrefilterCheckpoint | None:
        path = self.prefilter_checkpoint_path(analysis_cache_key, score_key)
        try:
            checkpoint = PrefilterCheckpoint.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return None
        except (OSError, ValidationError, ValueError):
            logger.warning("Ignoring invalid prefilter checkpoint: %s", path.name)
            return None
        if (
            checkpoint.analysis_cache_key != analysis_cache_key.strip().lower()
            or checkpoint.score_key != score_key.strip().lower()
        ):
            logger.warning("Ignoring mismatched prefilter checkpoint: %s", path.name)
            return None
        return checkpoint

    def save_prefilter_checkpoint(self, checkpoint: PrefilterCheckpoint) -> Path:
        path = self.prefilter_checkpoint_path(
            checkpoint.analysis_cache_key,
            checkpoint.score_key,
        )
        _atomic_write(path, checkpoint.model_dump_json(indent=2))
        return path

    def create_workspace(self, job_id: str) -> Path:
        safe_job_id = "".join(
            character for character in str(job_id) if character.isalnum() or character in "-_"
        )
        if not safe_job_id:
            raise ValueError("analysis job id cannot be empty")
        path = self.work_dir / safe_job_id
        path.mkdir(parents=True, exist_ok=False)
        return path


def _atomic_write(path: Path, serialized: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def _normalize_digest(value: str, label: str) -> str:
    normalized = str(value).strip().lower()
    if (
        len(normalized) != _DIGEST_LENGTH
        or any(character not in _DIGEST_CHARACTERS for character in normalized)
    ):
        raise ValueError(f"invalid {label}")
    return normalized


def _canonical_float(value: float) -> str:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("batch timestamps must be finite and non-negative")
    return number.hex()
