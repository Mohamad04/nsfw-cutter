import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from services.infrastructure.ffmpeg.probe import extract_keyframes
from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyframeIndexRequest:
    job_token: str
    media_path: str


@dataclass(frozen=True)
class _KeyframeCacheEntry:
    file_signature: tuple[int | None, int | None]
    timestamps: list[float]


@dataclass(frozen=True)
class _KeyframeIndexJob:
    job_token: str
    file_signature: tuple[int | None, int | None]
    started_at: float


class KeyframeService:
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"

    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        probe_runner=None,
        keyframe_probe=None,
    ):
        self.ffmpeg_service = ffmpeg_service
        self.probe_runner = probe_runner
        self.keyframe_probe = keyframe_probe or extract_keyframes
        self._active_media_path = ""
        self._keyframe_state = self.IDLE
        self._keyframe_timestamps: list[float] = []
        self._keyframe_error = ""
        self._active_job_token = ""
        self._cache: dict[str, _KeyframeCacheEntry] = {}
        self._loading_jobs: dict[str, _KeyframeIndexJob] = {}

    def extract_keyframes(self, input_path: str | Path) -> list[float]:
        return self.keyframe_probe(
            input_path,
            ffmpeg_service=self.ffmpeg_service,
            probe_runner=self.probe_runner,
        )

    @property
    def active_media_path(self) -> str:
        return self._active_media_path

    @property
    def keyframe_state(self) -> str:
        return self._keyframe_state

    @property
    def keyframe_timestamps(self) -> list[float]:
        return list(self._keyframe_timestamps)

    @property
    def keyframe_error(self) -> str:
        return self._keyframe_error

    @property
    def active_job_token(self) -> str:
        return self._active_job_token

    def request_indexing(self, media_path: str | Path) -> KeyframeIndexRequest | None:
        resolved_path = _resolved_path(media_path)
        signature = _file_signature(resolved_path)
        self._active_media_path = resolved_path
        self._keyframe_error = ""

        cached = self._cache.get(resolved_path)
        if cached is not None and cached.file_signature == signature:
            self._keyframe_state = self.READY
            self._keyframe_timestamps = list(cached.timestamps)
            self._active_job_token = ""
            logger.info(
                "[Keyframes] Reusing cached index: %s / count=%s",
                resolved_path,
                len(cached.timestamps),
            )
            return None

        active_job = self._loading_jobs.get(resolved_path)
        if active_job is not None and active_job.file_signature == signature:
            self._keyframe_state = self.LOADING
            self._keyframe_timestamps = []
            self._active_job_token = active_job.job_token
            logger.info(
                "[Keyframes] Duplicate indexing ignored; already loading: %s / job=%s",
                resolved_path,
                active_job.job_token,
            )
            return None

        job_token = uuid.uuid4().hex
        self._loading_jobs[resolved_path] = _KeyframeIndexJob(
            job_token=job_token,
            file_signature=signature,
            started_at=perf_counter(),
        )
        self._keyframe_state = self.LOADING
        self._keyframe_timestamps = []
        self._active_job_token = job_token
        logger.info(
            "[Keyframes] Scheduling background indexing: %s / job=%s",
            resolved_path,
            job_token,
        )
        return KeyframeIndexRequest(job_token=job_token, media_path=resolved_path)

    def complete_indexing(
        self,
        media_path: str | Path,
        job_token: str,
        timestamps: list[float],
        elapsed_seconds: float | None = None,
    ) -> bool:
        resolved_path = _resolved_path(media_path)
        job = self._loading_jobs.get(resolved_path)
        if job is None or job.job_token != job_token:
            logger.info(
                "[Keyframes] Ignoring stale result for superseded job: %s / job=%s",
                resolved_path,
                job_token,
            )
            return False

        del self._loading_jobs[resolved_path]
        if (
            self._active_media_path != resolved_path
            or self._active_job_token != job_token
        ):
            logger.info(
                "[Keyframes] Ignoring stale result for inactive video: %s / job=%s",
                resolved_path,
                job_token,
            )
            return False

        normalized_timestamps = sorted(
            set(round(float(timestamp), 3) for timestamp in timestamps)
        )
        self._cache[resolved_path] = _KeyframeCacheEntry(
            file_signature=job.file_signature,
            timestamps=normalized_timestamps,
        )
        self._keyframe_state = self.READY
        self._keyframe_timestamps = list(normalized_timestamps)
        self._keyframe_error = ""
        self._active_job_token = ""
        elapsed = elapsed_seconds
        if elapsed is None:
            elapsed = perf_counter() - job.started_at
        logger.info(
            "[Keyframes] Indexing completed: %s / count=%s / elapsed=%.3fs",
            resolved_path,
            len(normalized_timestamps),
            elapsed,
        )
        return True

    def fail_indexing(
        self,
        media_path: str | Path,
        job_token: str,
        error_message: str,
    ) -> bool:
        resolved_path = _resolved_path(media_path)
        job = self._loading_jobs.get(resolved_path)
        if job is None or job.job_token != job_token:
            logger.info(
                "[Keyframes] Ignoring stale failure for superseded job: %s / job=%s",
                resolved_path,
                job_token,
            )
            return False

        del self._loading_jobs[resolved_path]
        if (
            self._active_media_path != resolved_path
            or self._active_job_token != job_token
        ):
            logger.info(
                "[Keyframes] Ignoring stale failure for inactive video: %s / job=%s",
                resolved_path,
                job_token,
            )
            return False

        self._keyframe_state = self.ERROR
        self._keyframe_timestamps = []
        self._keyframe_error = str(error_message)
        self._active_job_token = ""
        logger.error(
            "[Keyframes] Indexing failed: %s / error=%s",
            resolved_path,
            error_message,
        )
        return True

    def clear_active_media(self) -> None:
        self._active_media_path = ""
        self._keyframe_state = self.IDLE
        self._keyframe_timestamps = []
        self._keyframe_error = ""
        self._active_job_token = ""

    def get_cached_keyframes(self, media_path: str | Path | None = None) -> list[float] | None:
        resolved_path = self._active_media_path if media_path is None else _resolved_path(media_path)
        if not resolved_path:
            return None

        cached = self._cache.get(resolved_path)
        if cached is None or cached.file_signature != _file_signature(resolved_path):
            return None
        return list(cached.timestamps)


def _resolved_path(media_path: str | Path) -> str:
    return str(Path(media_path).expanduser().resolve())


def _file_signature(media_path: str | Path) -> tuple[int | None, int | None]:
    try:
        stat = Path(media_path).stat()
    except OSError:
        return None, None
    return stat.st_mtime_ns, stat.st_size
