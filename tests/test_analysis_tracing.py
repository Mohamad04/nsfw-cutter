import json
import os
import unittest
from unittest.mock import patch

from services.analysis.tracing import (
    OptionalLangSmithTracer,
    redact_trace_payload,
    suppress_framework_tracing,
)


class _FakeLangSmithClient:
    def __init__(self):
        self.created = []
        self.updated = []

    def create_run(self, **kwargs):
        self.created.append(kwargs)

    def update_run(self, *args, **kwargs):
        self.updated.append((args, kwargs))


class TraceRedactionTests(unittest.TestCase):
    def test_redaction_uses_allowlist_and_excludes_raw_media_text_paths_and_secrets(self):
        payload = {
            "node": "review_visual_batches",
            "video_fingerprint": "sha256:safe-fingerprint",
            "duration_seconds": 12.5,
            "status": (
                r"Using sk_abcdefghijklmnop failed at "
                r"C:\Users\alice\Project Files\private video.mp4"
            ),
            "timestamps": [1.0, 2.0],
            "frames": ["raw frame bytes"],
            "audio": "raw audio bytes",
            "transcript": "full private transcript",
            "subtitle": "private subtitle text",
            "video_path": r"C:\Users\alice\private.mp4",
            "local_path": "/home/alice/private.mp4",
            "api_key": "sk_secret-top-level-value",
            "secret": "developer secret",
            "prompt": "raw model prompt",
            "unrecognized": "must be dropped",
            "scores": {
                "visual_confidence": 0.91,
                "text_confidence": 0.3,
                "transcript": "nested transcript",
                "path": r"C:\Users\alice\frame.jpg",
                "secret": "nested secret",
            },
            "error": (
                r"Using sk_abcdefghijklmnop could not open "
                r"C:\Users\alice\Project Files\private video.mp4"
            ),
        }

        redacted = redact_trace_payload(payload)
        serialized = json.dumps(redacted, sort_keys=True)

        self.assertEqual(redacted["node"], "review_visual_batches")
        self.assertEqual(redacted["video_fingerprint"], "sha256:safe-fingerprint")
        self.assertEqual(
            redacted["scores"],
            {"visual_confidence": 0.91, "text_confidence": 0.3},
        )
        for sensitive_key in (
            "frames",
            "audio",
            "transcript",
            "subtitle",
            "video_path",
            "local_path",
            "api_key",
            "secret",
            "prompt",
            "unrecognized",
        ):
            self.assertNotIn(sensitive_key, redacted)
        for sensitive_value in (
            "raw frame bytes",
            "raw audio bytes",
            "full private transcript",
            "nested transcript",
            "alice",
            "abcdefghijklmnop",
        ):
            self.assertNotIn(sensitive_value, serialized)
        self.assertEqual(redacted["error"], "[ERROR_DETAIL_REDACTED]")
        self.assertIn("[SECRET_REDACTED]", redacted["status"])
        self.assertIn("[LOCAL_PATH_REDACTED]", redacted["status"])

    def test_non_mapping_payload_is_discarded(self):
        self.assertEqual(redact_trace_payload(None), {})
        self.assertEqual(redact_trace_payload(["not", "metadata"]), {})

    def test_tracer_is_disabled_by_default_and_enabled_calls_are_redacted(self):
        client = _FakeLangSmithClient()
        with patch.dict(os.environ, {}, clear=True):
            disabled = OptionalLangSmithTracer(client=client)
            self.assertIsNone(
                disabled.start_node(
                    "preflight",
                    {"video_path": r"C:\Private Files\video.mp4"},
                )
            )
        self.assertEqual(client.created, [])

        enabled = OptionalLangSmithTracer(enabled=True, client=client)
        run_id = enabled.start_node(
            "preflight",
            {
                "video_fingerprint": "sha256:safe",
                "video_path": r"C:\Private Files\video.mp4",
                "transcript": "private transcript",
            },
        )
        enabled.finish_node(
            run_id,
            {"status": "failed", "error": r"Failed at C:\Private Files\video.mp4"},
            error=RuntimeError(r"Failed at C:\Private Files\video.mp4"),
        )

        self.assertEqual(len(client.created), 1)
        self.assertEqual(len(client.updated), 1)
        serialized = json.dumps([client.created, client.updated], default=str)
        self.assertIn("sha256:safe", serialized)
        self.assertNotIn("Private Files", serialized)
        self.assertNotIn("private transcript", serialized)

    def test_framework_tracing_suppression_overrides_environment_opt_in(self):
        try:
            from langchain_core.tracers.context import _tracing_v2_is_enabled
            from langsmith import utils as langsmith_utils
        except ImportError:
            self.skipTest("optional LangGraph/LangSmith stack is not installed")

        with patch.dict(
            os.environ,
            {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true"},
        ), suppress_framework_tracing():
            self.assertFalse(langsmith_utils.tracing_is_enabled())
            self.assertFalse(_tracing_v2_is_enabled())


if __name__ == "__main__":
    unittest.main()
