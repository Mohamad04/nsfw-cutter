import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from core.paths import PROJECT_ROOT, get_model_cache_dir
from services.analysis.cache import AnalysisCache
from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import (
    AnalysisRecord,
    AnalysisSettings,
    AnalysisStatus,
    MediaSummary,
)
from services.analysis.preflight import FileFingerprintService, fingerprint_text_source


class FileFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_content_based_and_stable_across_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.mp4"
            second = root / "renamed.mkv"
            changed = root / "changed.mp4"
            first.write_bytes(b"same local media bytes")
            second.write_bytes(b"same local media bytes")
            changed.write_bytes(b"different local media bytes")
            service = FileFingerprintService()

            first_fingerprint = service.fingerprint(first, CancellationToken())
            second_fingerprint = service.fingerprint(second, CancellationToken())
            changed_fingerprint = service.fingerprint(changed, CancellationToken())

        self.assertTrue(first_fingerprint.startswith("sha256:"))
        self.assertEqual(first_fingerprint, second_fingerprint)
        self.assertNotEqual(first_fingerprint, changed_fingerprint)

    def test_selected_text_source_fingerprint_tracks_content_or_embedded_stream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "selected subtitle.srt"
            subtitle.write_text("first subtitle contents", encoding="utf-8")
            candidate = {
                "source": "external",
                "file_path": str(subtitle),
                "is_text_readable": True,
            }
            first = fingerprint_text_source(candidate, CancellationToken())
            subtitle.write_text("changed subtitle contents", encoding="utf-8")
            changed = fingerprint_text_source(candidate, CancellationToken())

        embedded_first = fingerprint_text_source(
            {"source": "embedded", "stream_index": 2, "is_text_readable": True},
            CancellationToken(),
        )
        embedded_second = fingerprint_text_source(
            {"source": "embedded", "stream_index": 3, "is_text_readable": True},
            CancellationToken(),
        )

        self.assertTrue(first.startswith("subtitle-sha256:"))
        self.assertNotEqual(first, changed)
        self.assertNotEqual(embedded_first, embedded_second)
        self.assertNotIn(str(subtitle), first)


class ModelCachePathTests(unittest.TestCase):
    def test_configured_model_cache_must_be_absolute_and_outside_app(self):
        with (
            patch.dict(os.environ, {"NSFW_CUTTER_MODEL_CACHE": "relative-models"}),
            self.assertRaisesRegex(ValueError, "absolute path"),
        ):
            get_model_cache_dir()

        forbidden = PROJECT_ROOT / "forbidden-model-cache"
        with (
            patch.dict(os.environ, {"NSFW_CUTTER_MODEL_CACHE": str(forbidden)}),
            self.assertRaisesRegex(ValueError, "outside the application"),
        ):
            get_model_cache_dir()

    def test_absolute_model_cache_override_is_created(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = Path(temp_dir) / "models"
            with patch.dict(os.environ, {"NSFW_CUTTER_MODEL_CACHE": str(configured)}):
                resolved = get_model_cache_dir()

            self.assertEqual(resolved, configured.resolve())
            self.assertTrue(resolved.is_dir())


class AnalysisCacheTests(unittest.TestCase):
    def test_key_is_stable_and_changes_with_fingerprint_model_or_settings(self):
        settings = AnalysisSettings(use_gpu=False)
        base_key = AnalysisCache.make_key("sha256:aaa", settings)

        self.assertEqual(base_key, AnalysisCache.make_key("sha256:aaa", settings))
        self.assertEqual(len(base_key), 64)
        self.assertNotEqual(
            base_key,
            AnalysisCache.make_key("sha256:bbb", settings),
        )
        self.assertNotEqual(
            base_key,
            AnalysisCache.make_key(
                "sha256:aaa",
                settings.model_copy(update={"model_revision": "revision-2"}),
            ),
        )
        self.assertNotEqual(
            base_key,
            AnalysisCache.make_key(
                "sha256:aaa",
                settings.model_copy(update={"sample_rate_fps": 2.0}),
            ),
        )
        self.assertNotEqual(
            base_key,
            AnalysisCache.make_key(
                "sha256:aaa",
                settings,
                "subtitle-sha256:different",
            ),
        )
        self.assertNotEqual(settings.model_revision, "main")
        self.assertEqual(len(settings.model_revision), 40)

    def test_completed_record_round_trips_and_partial_record_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            settings = AnalysisSettings(use_gpu=False)
            completed_key = cache.make_key("sha256:completed", settings)
            partial_key = cache.make_key("sha256:partial", settings)

            cache.save(
                completed_key,
                self._record(settings, "sha256:completed", AnalysisStatus.COMPLETED),
            )
            cache.save(
                partial_key,
                self._record(settings, "sha256:partial", AnalysisStatus.PARTIAL),
            )

            completed = cache.load(completed_key)
            reusable_partial = cache.load(partial_key)
            diagnostic_partial = cache.load(partial_key, reusable_only=False)

        self.assertIsNotNone(completed)
        self.assertEqual(completed.video_fingerprint, "sha256:completed")
        self.assertIsNone(reusable_partial)
        self.assertIsNotNone(diagnostic_partial)
        self.assertEqual(diagnostic_partial.status, AnalysisStatus.PARTIAL)

    def test_invalid_record_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            key = cache.make_key("sha256:corrupt", AnalysisSettings(use_gpu=False))
            cache.record_path(key).write_text("{not valid json", encoding="utf-8")

            self.assertIsNone(cache.load(key, reusable_only=False))

    @staticmethod
    def _record(
        settings: AnalysisSettings,
        fingerprint: str,
        status: AnalysisStatus,
    ) -> AnalysisRecord:
        now = datetime.now(UTC)
        return AnalysisRecord(
            video_fingerprint=fingerprint,
            model_id=settings.model_id,
            model_revision=settings.model_revision,
            settings_version=settings.settings_version,
            settings=settings.model_dump(mode="json"),
            status=status,
            media=MediaSummary(
                duration_seconds=5.0,
                fps=24.0,
                format_name="mock",
                streams=[{"codec_type": "video"}],
            ),
            started_at=now,
            completed_at=now,
        )


if __name__ == "__main__":
    unittest.main()
