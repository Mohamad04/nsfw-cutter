from __future__ import annotations

import json
import math
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath

from huggingface_hub import snapshot_download, try_to_load_from_cache

from core.paths import get_model_cache_dir
from services.analysis.contracts import (
    DEFAULT_PREFILTER_MODEL_ID,
    DEFAULT_PREFILTER_MODEL_REVISION,
    DEFAULT_QWEN_MODEL_ID,
    DEFAULT_QWEN_MODEL_REVISION,
    DEFAULT_WHISPER_MODEL_ID,
    DEFAULT_WHISPER_MODEL_REVISION,
)

GIB = 1024**3

# Verified blob payload in the production cache used for the release smoke. These
# values are estimates for disk preflight/status, not integrity checks.
PREFILTER_EXPECTED_BYTES = 22_405_349
QWEN_EXPECTED_BYTES = 7_520_919_614
WHISPER_EXPECTED_BYTES = 486_212_372
MINIMUM_DISK_HEADROOM_BYTES = 2 * GIB
DISK_HEADROOM_FRACTION = 0.15


class ModelComponent(str, Enum):
    NSFW_PREFILTER = "nsfw_prefilter"
    VISUAL_REVIEW = "visual_review"
    SPEECH_TRANSCRIPTION = "speech_transcription"


@dataclass(frozen=True)
class ProductionModelSpec:
    component: ModelComponent
    repo_id: str
    revision: str
    required_files: tuple[str, ...]
    required_globs: tuple[str, ...] = ()
    download_allow_patterns: tuple[str, ...] | None = None
    approximate_download_bytes: int = 0


PRODUCTION_MODELS: tuple[ProductionModelSpec, ...] = (
    ProductionModelSpec(
        component=ModelComponent.NSFW_PREFILTER,
        repo_id=DEFAULT_PREFILTER_MODEL_ID,
        revision=DEFAULT_PREFILTER_MODEL_REVISION,
        required_files=("config.json", "model.safetensors"),
        approximate_download_bytes=PREFILTER_EXPECTED_BYTES,
    ),
    ProductionModelSpec(
        component=ModelComponent.VISUAL_REVIEW,
        repo_id=DEFAULT_QWEN_MODEL_ID,
        revision=DEFAULT_QWEN_MODEL_REVISION,
        required_files=(
            "config.json",
            "model.safetensors.index.json",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "tokenizer.json",
        ),
        approximate_download_bytes=QWEN_EXPECTED_BYTES,
    ),
    ProductionModelSpec(
        component=ModelComponent.SPEECH_TRANSCRIPTION,
        repo_id=DEFAULT_WHISPER_MODEL_ID,
        revision=DEFAULT_WHISPER_MODEL_REVISION,
        required_files=("config.json", "model.bin", "tokenizer.json"),
        required_globs=("vocabulary.*",),
        download_allow_patterns=(
            "config.json",
            "preprocessor_config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
        ),
        approximate_download_bytes=WHISPER_EXPECTED_BYTES,
    ),
)


class ReadinessState(str, Enum):
    READY = "ready"
    MISSING = "missing"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


@dataclass(frozen=True)
class ModelReadiness:
    spec: ProductionModelSpec
    state: ReadinessState
    reason: str
    snapshot_path: Path | None = None
    missing_files: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.state is ReadinessState.READY


class ProvisioningState(str, Enum):
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    READY = "ready"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ProvisioningProgress:
    component: ModelComponent | None
    state: ProvisioningState
    message: str
    completed_components: int
    total_components: int
    # This is deliberately component-level progress. snapshot_download does not
    # expose a stable aggregate byte callback suitable for a UI-independent API.
    overall_fraction: float | None = None
    current_file: str | None = None
    completed_files: int | None = None
    total_files: int | None = None


@dataclass(frozen=True)
class ProvisioningResult:
    models: tuple[ModelReadiness, ...]

    @property
    def success(self) -> bool:
        return len(self.models) == len(PRODUCTION_MODELS) and all(
            model.ready for model in self.models
        )


ProgressCallback = Callable[[ProvisioningProgress], None]
CancellationCheck = Callable[[], bool]


class ModelProvisioningError(RuntimeError):
    """Raised when an approved production model cannot be provisioned."""


class InsufficientModelDiskSpaceError(ModelProvisioningError):
    """Raised before download when the model cache filesystem is too full."""


class ModelProvisioningCancelled(ModelProvisioningError):
    """Raised at a safe cooperative cancellation point.

    Hugging Face does not expose a public cancellation token for an individual
    snapshot transfer. Cancellation is therefore observed before and after each
    component; any partial cache data is intentionally retained for retry.
    """


def check_model(
    spec: ProductionModelSpec,
    *,
    cache_dir: str | Path | None = None,
) -> ModelReadiness:
    """Validate one immutable production snapshot without network access."""

    root = Path(cache_dir) if cache_dir is not None else get_model_cache_dir()
    found: dict[str, Path] = {}
    missing: list[str] = []
    try:
        for filename in spec.required_files:
            cached = try_to_load_from_cache(
                spec.repo_id,
                filename,
                cache_dir=str(root),
                revision=spec.revision,
            )
            if isinstance(cached, str) and Path(cached).is_file():
                found[filename] = Path(cached)
            else:
                missing.append(filename)
    except Exception as exc:  # noqa: BLE001 - cache inspection must report invalid state
        return ModelReadiness(
            spec=spec,
            state=ReadinessState.INVALID,
            reason=(
                f"Unable to inspect the pinned cache for {spec.repo_id}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    if not found:
        return ModelReadiness(
            spec=spec,
            state=ReadinessState.MISSING,
            reason=(
                f"Pinned snapshot {spec.revision} for {spec.repo_id} is missing "
                "from the user model cache."
            ),
            missing_files=tuple(missing),
        )

    snapshot_path = next(iter(found.values())).parent
    for pattern in spec.required_globs:
        if not any(path.is_file() for path in snapshot_path.glob(pattern)):
            missing.append(pattern)
    if missing:
        return ModelReadiness(
            spec=spec,
            state=ReadinessState.INCOMPLETE,
            reason=(
                f"Pinned snapshot {spec.revision} for {spec.repo_id} is incomplete; "
                f"missing: {', '.join(missing)}. Retry model provisioning."
            ),
            snapshot_path=snapshot_path,
            missing_files=tuple(missing),
        )

    if spec.component is ModelComponent.VISUAL_REVIEW:
        return _validate_qwen_shards(spec, root, found, snapshot_path)

    return ModelReadiness(
        spec=spec,
        state=ReadinessState.READY,
        reason=f"Pinned snapshot {spec.revision} for {spec.repo_id} is ready.",
        snapshot_path=snapshot_path,
    )


def check_all_models(
    *,
    cache_dir: str | Path | None = None,
) -> tuple[ModelReadiness, ...]:
    """Validate the complete static production model set locally."""

    return tuple(check_model(spec, cache_dir=cache_dir) for spec in PRODUCTION_MODELS)


class ProductionModelProvisioner:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.cache_dir = (
            Path(cache_dir) if cache_dir is not None else get_model_cache_dir()
        )

    def check_model(self, spec: ProductionModelSpec) -> ModelReadiness:
        return check_model(spec, cache_dir=self.cache_dir)

    def check_all_models(self) -> tuple[ModelReadiness, ...]:
        return check_all_models(cache_dir=self.cache_dir)

    def provision_all(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> ProvisioningResult:
        """Provision all approved models sequentially at immutable revisions."""

        emit = progress_callback or (lambda _event: None)
        total = len(PRODUCTION_MODELS)
        self._raise_if_cancelled(cancellation_check, emit, 0)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        emit(
            ProvisioningProgress(
                component=None,
                state=ProvisioningState.CHECKING,
                message="Checking production model cache and available disk space.",
                completed_components=0,
                total_components=total,
                overall_fraction=0.0,
            )
        )
        initial = self.check_all_models()
        self._check_disk_space(initial)

        completed: list[ModelReadiness] = []
        for spec, existing in zip(PRODUCTION_MODELS, initial, strict=True):
            self._raise_if_cancelled(cancellation_check, emit, len(completed))
            if existing.ready:
                completed.append(existing)
                self._emit_ready(emit, spec, len(completed), total, "already ready")
                self._raise_if_cancelled(cancellation_check, emit, len(completed))
                continue

            emit(
                ProvisioningProgress(
                    component=spec.component,
                    state=ProvisioningState.DOWNLOADING,
                    message=(
                        f"Downloading {spec.repo_id} at pinned revision "
                        f"{spec.revision}."
                    ),
                    completed_components=len(completed),
                    total_components=total,
                    overall_fraction=len(completed) / total,
                )
            )
            kwargs = {
                "repo_id": spec.repo_id,
                "revision": spec.revision,
                "cache_dir": str(self.cache_dir),
                "token": False,
            }
            if spec.download_allow_patterns is not None:
                kwargs["allow_patterns"] = spec.download_allow_patterns
            try:
                snapshot_download(**kwargs)
            except Exception as exc:
                emit(
                    ProvisioningProgress(
                        component=spec.component,
                        state=ProvisioningState.FAILED,
                        message=(
                            f"Failed to download {spec.repo_id}: "
                            f"{type(exc).__name__}: {exc}. Retry to reuse partial data."
                        ),
                        completed_components=len(completed),
                        total_components=total,
                        overall_fraction=len(completed) / total,
                    )
                )
                raise ModelProvisioningError(
                    f"Failed to provision {spec.repo_id}. Partial cache data was "
                    "preserved; retry model setup to continue."
                ) from exc

            self._raise_if_cancelled(cancellation_check, emit, len(completed))
            emit(
                ProvisioningProgress(
                    component=spec.component,
                    state=ProvisioningState.VALIDATING,
                    message=f"Validating the pinned {spec.repo_id} snapshot locally.",
                    completed_components=len(completed),
                    total_components=total,
                    overall_fraction=len(completed) / total,
                )
            )
            readiness = self.check_model(spec)
            self._raise_if_cancelled(cancellation_check, emit, len(completed))
            if not readiness.ready:
                emit(
                    ProvisioningProgress(
                        component=spec.component,
                        state=ProvisioningState.FAILED,
                        message=readiness.reason,
                        completed_components=len(completed),
                        total_components=total,
                        overall_fraction=len(completed) / total,
                    )
                )
                raise ModelProvisioningError(readiness.reason)
            completed.append(readiness)
            self._emit_ready(emit, spec, len(completed), total, "downloaded and validated")
            self._raise_if_cancelled(cancellation_check, emit, len(completed))

        self._raise_if_cancelled(cancellation_check, emit, len(completed))
        result = ProvisioningResult(models=tuple(completed))
        if not result.success:
            raise ModelProvisioningError(
                "Production model provisioning did not validate all approved models."
            )
        self._raise_if_cancelled(cancellation_check, emit, len(completed))
        emit(
            ProvisioningProgress(
                component=None,
                state=ProvisioningState.COMPLETE,
                message="All production AI models are ready for offline use.",
                completed_components=total,
                total_components=total,
                overall_fraction=1.0,
            )
        )
        return result

    def _check_disk_space(self, readiness: tuple[ModelReadiness, ...]) -> None:
        pending_bytes = sum(
            item.spec.approximate_download_bytes for item in readiness if not item.ready
        )
        if pending_bytes <= 0:
            return
        headroom = max(
            MINIMUM_DISK_HEADROOM_BYTES,
            math.ceil(pending_bytes * DISK_HEADROOM_FRACTION),
        )
        required = pending_bytes + headroom
        free = shutil.disk_usage(self.cache_dir).free
        if free < required:
            raise InsufficientModelDiskSpaceError(
                "Insufficient free space for production AI models in "
                f"'{self.cache_dir}'. Approximately {_format_gib(required)} GiB is "
                f"required (model payload plus headroom), but {_format_gib(free)} GiB "
                "is available. Free disk space or choose an absolute "
                "NSFW_CUTTER_MODEL_CACHE location and retry."
            )

    @staticmethod
    def _emit_ready(
        emit: ProgressCallback,
        spec: ProductionModelSpec,
        completed: int,
        total: int,
        detail: str,
    ) -> None:
        emit(
            ProvisioningProgress(
                component=spec.component,
                state=ProvisioningState.READY,
                message=f"{spec.repo_id} is {detail}.",
                completed_components=completed,
                total_components=total,
                overall_fraction=completed / total,
            )
        )

    @staticmethod
    def _raise_if_cancelled(
        cancellation_check: CancellationCheck | None,
        emit: ProgressCallback,
        completed: int,
    ) -> None:
        if cancellation_check is None or not cancellation_check():
            return
        emit(
            ProvisioningProgress(
                component=None,
                state=ProvisioningState.CANCELLED,
                message=(
                    "Model provisioning was cancelled between components. Partial "
                    "cache data was preserved for retry."
                ),
                completed_components=completed,
                total_components=len(PRODUCTION_MODELS),
                overall_fraction=completed / len(PRODUCTION_MODELS),
            )
        )
        raise ModelProvisioningCancelled(
            "Model provisioning was cancelled. Partial cache data was preserved."
        )


def _validate_qwen_shards(
    spec: ProductionModelSpec,
    cache_dir: Path,
    found: dict[str, Path],
    snapshot_path: Path,
) -> ModelReadiness:
    index_path = found["model.safetensors.index.json"]
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("index root must be an object")
        weight_map = payload.get("weight_map")
        if not isinstance(weight_map, dict) or not weight_map:
            raise ValueError("weight_map must be a non-empty object")
        shard_names = sorted({_validate_relative_filename(value) for value in weight_map.values()})
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return ModelReadiness(
            spec=spec,
            state=ReadinessState.INVALID,
            reason=(
                f"Pinned snapshot {spec.revision} for {spec.repo_id} has an invalid "
                f"safetensors index: {exc}. Retry model provisioning."
            ),
            snapshot_path=snapshot_path,
        )

    missing_shards = []
    try:
        for shard_name in shard_names:
            cached = try_to_load_from_cache(
                spec.repo_id,
                shard_name,
                cache_dir=str(cache_dir),
                revision=spec.revision,
            )
            if not isinstance(cached, str) or not Path(cached).is_file():
                missing_shards.append(shard_name)
    except Exception as exc:  # noqa: BLE001 - expose a stable readiness result
        return ModelReadiness(
            spec=spec,
            state=ReadinessState.INVALID,
            reason=(
                f"Unable to inspect weight shards for pinned snapshot {spec.revision} "
                f"of {spec.repo_id}: {type(exc).__name__}: {exc}. Retry model "
                "provisioning."
            ),
            snapshot_path=snapshot_path,
        )
    if missing_shards:
        return ModelReadiness(
            spec=spec,
            state=ReadinessState.INCOMPLETE,
            reason=(
                f"Pinned snapshot {spec.revision} for {spec.repo_id} is incomplete; "
                f"missing weight shards: {', '.join(missing_shards)}. Retry model "
                "provisioning."
            ),
            snapshot_path=snapshot_path,
            missing_files=tuple(missing_shards),
        )
    return ModelReadiness(
        spec=spec,
        state=ReadinessState.READY,
        reason=f"Pinned snapshot {spec.revision} for {spec.repo_id} is ready.",
        snapshot_path=snapshot_path,
    )


def _validate_relative_filename(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("weight_map contains an invalid shard filename")
    filenames = (PurePosixPath(value), PureWindowsPath(value))
    if any(
        filename.is_absolute()
        or bool(filename.drive)
        or bool(filename.root)
        or ".." in filename.parts
        for filename in filenames
    ):
        raise ValueError("weight_map contains an unsafe shard filename")
    return filenames[0].as_posix()


def _format_gib(value: int) -> str:
    return f"{value / GIB:.2f}"
