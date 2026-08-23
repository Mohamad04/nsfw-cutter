from __future__ import annotations

import logging
import os
import re
import uuid
from contextlib import contextmanager
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_TRACE_KEYS = {
    "batch_count",
    "batch_id",
    "candidate_count",
    "completed_batch_count",
    "duration_seconds",
    "elapsed_ms",
    "error",
    "error_type",
    "evidence_timestamps",
    "final_confidence",
    "fps",
    "frame_count",
    "failed_batch_count",
    "model_id",
    "model_revision",
    "node",
    "node_timing_ms",
    "scores",
    "repaired_batch_count",
    "resumed_batch_count",
    "settings_version",
    "status",
    "suggestion_count",
    "text_confidence",
    "timestamps",
    "video_fingerprint",
    "visual_confidence",
}
_SENSITIVE_KEY_PARTS = {
    "api_key",
    "audio",
    "frame_path",
    "frames",
    "local_path",
    "path",
    "prompt",
    "secret",
    "subtitle",
    "token",
    "transcript",
    "video_path",
}
_WINDOWS_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n]*")
_POSIX_PATH = re.compile(r"(?<![\w.])/(?:home|users|tmp|var|private|mnt)/[^\r\n]*")
_API_KEY = re.compile(
    r"\b(?:sk[-_][A-Za-z0-9_-]{10,}|lsv2_pt_[A-Za-z0-9_-]{10,}|ls__[A-Za-z0-9_-]{10,})\b",
    re.IGNORECASE,
)


def redact_trace_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Build a whitelist-only trace payload which cannot contain raw media data."""
    if not isinstance(payload, dict):
        return {}
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        normalized_key = str(key).strip()
        lowered_key = normalized_key.casefold()
        if lowered_key in _SENSITIVE_KEY_PARTS or lowered_key not in _ALLOWED_TRACE_KEYS:
            continue
        if lowered_key == "error":
            redacted[normalized_key] = "[ERROR_DETAIL_REDACTED]"
            continue
        redacted[normalized_key] = _redact_trace_value(value)
    return redacted


def _redact_trace_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, (list, tuple)):
        return [_redact_trace_value(item) for item in value[:256]]
    if isinstance(value, dict):
        return redact_trace_payload(value)
    return str(type(value).__name__)


def redact_sensitive_text(value: str, limit: int = 1000) -> str:
    """Remove local paths and common API-key forms from a diagnostic string."""
    scrubbed = _API_KEY.sub("[SECRET_REDACTED]", str(value or ""))
    scrubbed = _WINDOWS_PATH.sub("[LOCAL_PATH_REDACTED]", scrubbed)
    scrubbed = _POSIX_PATH.sub("[LOCAL_PATH_REDACTED]", scrubbed)
    return scrubbed[:limit]


class OptionalLangSmithTracer:
    """Manual metadata-only tracing; never decorates functions or serializes state."""

    def __init__(self, *, enabled: bool | None = None, client=None) -> None:
        self.enabled = (
            _environment_flag("NSFW_CUTTER_LANGSMITH_TRACING")
            if enabled is None
            else enabled
        )
        self.project_name = os.environ.get(
            "NSFW_CUTTER_LANGSMITH_PROJECT",
            "nsfw-cutter-vlm-development",
        )
        self._client = client
        self._starts: dict[uuid.UUID, float] = {}

    def start_node(self, node_name: str, metadata: dict[str, Any]) -> uuid.UUID | None:
        if not self.enabled:
            return None
        client = self._get_client()
        if client is None:
            return None
        run_id = uuid.uuid4()
        safe_metadata = redact_trace_payload({"node": node_name, **metadata})
        try:
            client.create_run(
                name=f"vlm_analysis.{node_name}",
                run_type="chain",
                inputs={"metadata": safe_metadata},
                id=run_id,
                project_name=self.project_name,
            )
        except Exception:
            logger.warning("Unable to start optional LangSmith trace", exc_info=True)
            return None
        self._starts[run_id] = perf_counter()
        return run_id

    def finish_node(
        self,
        run_id: uuid.UUID | None,
        metadata: dict[str, Any],
        error: Exception | None = None,
    ) -> None:
        if run_id is None:
            return
        client = self._get_client()
        if client is None:
            return
        started_at = self._starts.pop(run_id, perf_counter())
        payload = {
            **metadata,
            "elapsed_ms": round((perf_counter() - started_at) * 1000.0, 3),
            "status": "error" if error is not None else metadata.get("status", "completed"),
        }
        if error is not None:
            payload["error_type"] = type(error).__name__
            payload["error"] = "[ERROR_DETAIL_REDACTED]"
        safe_metadata = redact_trace_payload(payload)
        try:
            client.update_run(
                run_id,
                outputs={"metadata": safe_metadata},
                error=safe_metadata.get("error"),
            )
        except Exception:
            logger.warning("Unable to finish optional LangSmith trace", exc_info=True)

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from langsmith import Client
        except ImportError:
            logger.warning(
                "LangSmith tracing was requested but langsmith is not installed; tracing is disabled"
            )
            self.enabled = False
            return None
        try:
            self._client = Client()
        except Exception:
            logger.warning("LangSmith tracing configuration is unavailable", exc_info=True)
            self.enabled = False
            return None
        return self._client


def _environment_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


class FrameworkTracingControlUnavailable(RuntimeError):
    """Raised when LangGraph tracing cannot be explicitly suppressed."""


@contextmanager
def suppress_framework_tracing():
    """Disable LangChain/LangSmith automatic tracing around the raw graph state."""
    try:
        from langchain_core.tracers.context import tracing_v2_callback_var
        from langsmith.run_helpers import tracing_context
    except ImportError as exc:
        raise FrameworkTracingControlUnavailable(
            "Automatic framework tracing could not be disabled safely"
        ) from exc

    callback_v2_token = tracing_v2_callback_var.set(None)
    try:
        with tracing_context(enabled=False, parent=False):
            yield
    finally:
        tracing_v2_callback_var.reset(callback_v2_token)
