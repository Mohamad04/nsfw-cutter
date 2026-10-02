import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from services.analysis.model_provisioning import (
    GIB,
    PRODUCTION_MODELS,
    InsufficientModelDiskSpaceError,
    ModelComponent,
    ModelProvisioningCancelled,
    ModelProvisioningError,
    ProductionModelProvisioner,
    ProvisioningState,
    ReadinessState,
    check_all_models,
    check_model,
)


class _FakeModelCache:
    def __init__(self, root: Path):
        self.root = root
        self.specs = {spec.repo_id: spec for spec in PRODUCTION_MODELS}

    def snapshot_path(self, repo_id: str) -> Path:
        spec = self.specs[repo_id]
        return self.root / spec.component.value / spec.revision

    def lookup(self, repo_id, filename, *, cache_dir, revision):
        self.assert_request(repo_id, cache_dir, revision)
        path = self.snapshot_path(repo_id) / filename
        return str(path) if path.is_file() else None

    def assert_request(self, repo_id, cache_dir, revision):
        spec = self.specs[repo_id]
        if Path(cache_dir) != self.root:
            raise AssertionError(f"Unexpected cache directory: {cache_dir}")
        if revision != spec.revision:
            raise AssertionError(f"Unexpected revision for {repo_id}: {revision}")

    def populate(self, repo_id: str) -> Path:
        spec = self.specs[repo_id]
        snapshot = self.snapshot_path(repo_id)
        snapshot.mkdir(parents=True, exist_ok=True)
        if spec.component is ModelComponent.NSFW_PREFILTER:
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            (snapshot / "model.safetensors").write_bytes(b"weights")
        elif spec.component is ModelComponent.VISUAL_REVIEW:
            shard = "model-00001-of-00001.safetensors"
            for filename in (
                "config.json",
                "preprocessor_config.json",
                "tokenizer_config.json",
                "tokenizer.json",
            ):
                (snapshot / filename).write_text("{}", encoding="utf-8")
            (snapshot / "model.safetensors.index.json").write_text(
                json.dumps({"weight_map": {"layer": shard}}),
                encoding="utf-8",
            )
            (snapshot / shard).write_bytes(b"weights")
        else:
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            (snapshot / "model.bin").write_bytes(b"weights")
            (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
            (snapshot / "vocabulary.txt").write_text("token", encoding="utf-8")
        return snapshot

    def populate_all(self):
        for spec in PRODUCTION_MODELS:
            self.populate(spec.repo_id)


class ProductionModelManifestTests(unittest.TestCase):
    def test_manifest_contains_only_the_three_approved_pinned_models(self):
        self.assertEqual(
            [(spec.repo_id, spec.revision) for spec in PRODUCTION_MODELS],
            [
                (
                    "Marqo/nsfw-image-detection-384",
                    "0c26ec22111b83f106d72a55f611ec35962bcb65",
                ),
                (
                    "Qwen/Qwen2.5-VL-3B-Instruct",
                    "66285546d2b821cf421d4f5eb2576359d3770cd3",
                ),
                (
                    "Systran/faster-whisper-small",
                    "536b0662742c02347bc0e980a01041f333bce120",
                ),
            ],
        )
        manifest_text = " ".join(spec.repo_id for spec in PRODUCTION_MODELS).casefold()
        for experiment_name in (
            "tinyclip",
            "smolvlm",
            "internvl",
            "qwen3vl",
            "stage1",
            "benchmark",
            "evaluation",
            "ablation",
            "routing",
            "clustering",
        ):
            self.assertNotIn(experiment_name, manifest_text)


class ModelReadinessTests(unittest.TestCase):
    def test_fully_ready_cache_is_validated_without_network_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            cache.populate_all()
            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download"
                ) as download,
            ):
                readiness = check_all_models(cache_dir=cache.root)

        self.assertTrue(all(item.state is ReadinessState.READY for item in readiness))
        download.assert_not_called()

    def test_missing_snapshot_is_distinct_from_incomplete_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            spec = PRODUCTION_MODELS[0]
            with patch(
                "services.analysis.model_provisioning.try_to_load_from_cache",
                side_effect=cache.lookup,
            ):
                missing = check_model(spec, cache_dir=cache.root)
                snapshot = cache.snapshot_path(spec.repo_id)
                snapshot.mkdir(parents=True)
                (snapshot / "config.json").write_text("{}", encoding="utf-8")
                incomplete = check_model(spec, cache_dir=cache.root)

        self.assertEqual(missing.state, ReadinessState.MISSING)
        self.assertEqual(incomplete.state, ReadinessState.INCOMPLETE)
        self.assertEqual(incomplete.missing_files, ("model.safetensors",))

    def test_malformed_qwen_shard_index_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            spec = PRODUCTION_MODELS[1]
            snapshot = cache.populate(spec.repo_id)
            (snapshot / "model.safetensors.index.json").write_text(
                "not-json", encoding="utf-8"
            )
            with patch(
                "services.analysis.model_provisioning.try_to_load_from_cache",
                side_effect=cache.lookup,
            ):
                readiness = check_model(spec, cache_dir=cache.root)

        self.assertEqual(readiness.state, ReadinessState.INVALID)
        self.assertIn("invalid safetensors index", readiness.reason)

    def test_non_object_qwen_index_roots_are_invalid(self):
        for payload in ([], "hello"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp_dir:
                cache = _FakeModelCache(Path(temp_dir))
                spec = PRODUCTION_MODELS[1]
                snapshot = cache.populate(spec.repo_id)
                (snapshot / "model.safetensors.index.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
                with patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ):
                    readiness = check_model(spec, cache_dir=cache.root)

            self.assertEqual(readiness.state, ReadinessState.INVALID)
            self.assertIn("index root must be an object", readiness.reason)

    def test_malformed_qwen_weight_maps_are_invalid(self):
        for weight_map in (None, [], {}, {"layer": None}):
            with (
                self.subTest(weight_map=weight_map),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                cache = _FakeModelCache(Path(temp_dir))
                spec = PRODUCTION_MODELS[1]
                snapshot = cache.populate(spec.repo_id)
                (snapshot / "model.safetensors.index.json").write_text(
                    json.dumps({"weight_map": weight_map}), encoding="utf-8"
                )
                with patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ):
                    readiness = check_model(spec, cache_dir=cache.root)

            self.assertEqual(readiness.state, ReadinessState.INVALID)

    def test_qwen_unsafe_posix_and_windows_shard_paths_are_invalid(self):
        unsafe_paths = (
            "../outside.safetensors",
            "/subdir/outside.safetensors",
            "foo/../../outside.safetensors",
            "C:\\outside\\weights.safetensors",
            "C:outside\\weights.safetensors",
            "..\\outside.safetensors",
            "subdir\\..\\outside.safetensors",
            "\\outside\\weights.safetensors",
            "\\\\server\\share\\weights.safetensors",
        )
        for shard_name in unsafe_paths:
            with (
                self.subTest(shard_name=shard_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                cache = _FakeModelCache(Path(temp_dir))
                spec = PRODUCTION_MODELS[1]
                snapshot = cache.populate(spec.repo_id)
                (snapshot / "model.safetensors.index.json").write_text(
                    json.dumps({"weight_map": {"layer": shard_name}}),
                    encoding="utf-8",
                )
                with patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ):
                    readiness = check_model(spec, cache_dir=cache.root)

            self.assertEqual(readiness.state, ReadinessState.INVALID)
            self.assertIn("unsafe shard filename", readiness.reason)

    def test_qwen_shard_cache_inspection_error_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            spec = PRODUCTION_MODELS[1]
            cache.populate(spec.repo_id)

            def failing_shard_lookup(repo_id, filename, *, cache_dir, revision):
                if filename == "model-00001-of-00001.safetensors":
                    raise OSError("cache metadata is unreadable")
                return cache.lookup(
                    repo_id,
                    filename,
                    cache_dir=cache_dir,
                    revision=revision,
                )

            with patch(
                "services.analysis.model_provisioning.try_to_load_from_cache",
                side_effect=failing_shard_lookup,
            ):
                readiness = check_model(spec, cache_dir=cache.root)

        self.assertEqual(readiness.state, ReadinessState.INVALID)
        self.assertIn("Unable to inspect weight shards", readiness.reason)

    def test_missing_qwen_shard_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            spec = PRODUCTION_MODELS[1]
            snapshot = cache.populate(spec.repo_id)
            (snapshot / "model-00001-of-00001.safetensors").unlink()
            with patch(
                "services.analysis.model_provisioning.try_to_load_from_cache",
                side_effect=cache.lookup,
            ):
                readiness = check_model(spec, cache_dir=cache.root)

        self.assertEqual(readiness.state, ReadinessState.INCOMPLETE)
        self.assertIn("model-00001-of-00001.safetensors", readiness.missing_files)

    def test_missing_whisper_runtime_file_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            spec = PRODUCTION_MODELS[2]
            snapshot = cache.populate(spec.repo_id)
            (snapshot / "model.bin").unlink()
            with patch(
                "services.analysis.model_provisioning.try_to_load_from_cache",
                side_effect=cache.lookup,
            ):
                readiness = check_model(spec, cache_dir=cache.root)

        self.assertEqual(readiness.state, ReadinessState.INCOMPLETE)
        self.assertIn("model.bin", readiness.missing_files)

    def test_missing_whisper_vocabulary_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            spec = PRODUCTION_MODELS[2]
            snapshot = cache.populate(spec.repo_id)
            (snapshot / "vocabulary.txt").unlink()
            with patch(
                "services.analysis.model_provisioning.try_to_load_from_cache",
                side_effect=cache.lookup,
            ):
                readiness = check_model(spec, cache_dir=cache.root)

        self.assertEqual(readiness.state, ReadinessState.INCOMPLETE)
        self.assertIn("vocabulary.*", readiness.missing_files)


class ModelProvisioningTests(unittest.TestCase):
    def test_successfully_provisions_each_pinned_model_sequentially(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            calls = []
            events = []

            def download(**kwargs):
                calls.append(kwargs)
                cache.populate(kwargs["repo_id"])
                return str(cache.snapshot_path(kwargs["repo_id"]))

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ),
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
            ):
                result = ProductionModelProvisioner(cache.root).provision_all(
                    progress_callback=events.append
                )

        self.assertTrue(result.success)
        self.assertEqual([call["repo_id"] for call in calls], [s.repo_id for s in PRODUCTION_MODELS])
        for call, spec in zip(calls, PRODUCTION_MODELS, strict=True):
            self.assertEqual(call["revision"], spec.revision)
            self.assertEqual(Path(call["cache_dir"]), cache.root)
            self.assertIs(call["token"], False)
            if spec.download_allow_patterns is None:
                self.assertNotIn("allow_patterns", call)
            else:
                self.assertEqual(
                    call["allow_patterns"], spec.download_allow_patterns
                )
        self.assertEqual(events[-1].state, ProvisioningState.COMPLETE)
        self.assertEqual(events[-1].overall_fraction, 1.0)

    def test_failure_preserves_partial_state_and_prevents_aggregate_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            events = []

            def download(**kwargs):
                if kwargs["repo_id"] == PRODUCTION_MODELS[1].repo_id:
                    partial = cache.snapshot_path(kwargs["repo_id"]) / "partial.tmp"
                    partial.parent.mkdir(parents=True, exist_ok=True)
                    partial.write_bytes(b"partial")
                    raise OSError("connection interrupted")
                cache.populate(kwargs["repo_id"])

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ),
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
                self.assertRaisesRegex(ModelProvisioningError, "Partial cache"),
            ):
                ProductionModelProvisioner(cache.root).provision_all(
                    progress_callback=events.append
                )

            partial = cache.snapshot_path(PRODUCTION_MODELS[1].repo_id) / "partial.tmp"
            self.assertTrue(partial.is_file())
        self.assertNotIn(ProvisioningState.COMPLETE, [event.state for event in events])

    def test_retry_reuses_preserved_cache_and_completes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            attempts = {spec.repo_id: 0 for spec in PRODUCTION_MODELS}

            def download(**kwargs):
                repo_id = kwargs["repo_id"]
                attempts[repo_id] += 1
                if repo_id == PRODUCTION_MODELS[0].repo_id and attempts[repo_id] == 1:
                    partial = cache.snapshot_path(repo_id) / "partial.tmp"
                    partial.parent.mkdir(parents=True, exist_ok=True)
                    partial.write_bytes(b"partial")
                    raise OSError("temporary failure")
                cache.populate(repo_id)

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ),
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
            ):
                provisioner = ProductionModelProvisioner(cache.root)
                with self.assertRaises(ModelProvisioningError):
                    provisioner.provision_all()
                result = provisioner.provision_all()

            self.assertTrue(result.success)
            self.assertTrue(
                (cache.snapshot_path(PRODUCTION_MODELS[0].repo_id) / "partial.tmp").exists()
            )
        self.assertEqual(attempts[PRODUCTION_MODELS[0].repo_id], 2)

    def test_insufficient_disk_space_fails_before_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download"
                ) as download,
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=1 * GIB),
                ),
                self.assertRaisesRegex(
                    InsufficientModelDiskSpaceError, "Insufficient free space"
                ),
            ):
                ProductionModelProvisioner(cache.root).provision_all()

        download.assert_not_called()

    def test_adequate_disk_space_proceeds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))

            def download(**kwargs):
                cache.populate(kwargs["repo_id"])

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ) as mocked_download,
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
            ):
                ProductionModelProvisioner(cache.root).provision_all()

        self.assertEqual(mocked_download.call_count, 3)

    def test_cancellation_after_transfer_preserves_snapshot_for_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            cancelled = False
            events = []

            def download(**kwargs):
                nonlocal cancelled
                cache.populate(kwargs["repo_id"])
                cancelled = True

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ),
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
                self.assertRaises(ModelProvisioningCancelled),
            ):
                ProductionModelProvisioner(cache.root).provision_all(
                    progress_callback=events.append,
                    cancellation_check=lambda: cancelled,
                )

            first_snapshot = cache.snapshot_path(PRODUCTION_MODELS[0].repo_id)
            self.assertTrue((first_snapshot / "model.safetensors").is_file())
        self.assertEqual(events[-1].state, ProvisioningState.CANCELLED)

    def test_cancellation_during_final_validation_prevents_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            cancelled = False
            events = []

            def download(**kwargs):
                cache.populate(kwargs["repo_id"])

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ),
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
            ):
                provisioner = ProductionModelProvisioner(cache.root)
                original_check = provisioner.check_model

                def check_and_cancel(spec):
                    nonlocal cancelled
                    readiness = original_check(spec)
                    if spec is PRODUCTION_MODELS[-1]:
                        cancelled = True
                    return readiness

                with (
                    patch.object(provisioner, "check_model", side_effect=check_and_cancel),
                    self.assertRaises(ModelProvisioningCancelled),
                ):
                    provisioner.provision_all(
                        progress_callback=events.append,
                        cancellation_check=lambda: cancelled,
                    )

        self.assertNotIn(ProvisioningState.COMPLETE, [event.state for event in events])
        self.assertEqual(events[-1].state, ProvisioningState.CANCELLED)

    def test_cancellation_from_final_ready_callback_prevents_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            cancelled = False
            events = []

            def download(**kwargs):
                cache.populate(kwargs["repo_id"])

            def progress(event):
                nonlocal cancelled
                events.append(event)
                if (
                    event.state is ProvisioningState.READY
                    and event.completed_components == len(PRODUCTION_MODELS)
                ):
                    cancelled = True

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ),
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
                self.assertRaises(ModelProvisioningCancelled),
            ):
                ProductionModelProvisioner(cache.root).provision_all(
                    progress_callback=progress,
                    cancellation_check=lambda: cancelled,
                )

        self.assertNotIn(ProvisioningState.COMPLETE, [event.state for event in events])
        self.assertEqual(events[-1].state, ProvisioningState.CANCELLED)

    def test_cancellation_after_first_ready_model_stops_later_downloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = _FakeModelCache(Path(temp_dir))
            cancelled = False
            events = []
            downloads = []

            def download(**kwargs):
                downloads.append(kwargs["repo_id"])
                cache.populate(kwargs["repo_id"])

            def progress(event):
                nonlocal cancelled
                events.append(event)
                if (
                    event.state is ProvisioningState.READY
                    and event.completed_components == 1
                ):
                    cancelled = True

            with (
                patch(
                    "services.analysis.model_provisioning.try_to_load_from_cache",
                    side_effect=cache.lookup,
                ),
                patch(
                    "services.analysis.model_provisioning.snapshot_download",
                    side_effect=download,
                ),
                patch(
                    "services.analysis.model_provisioning.shutil.disk_usage",
                    return_value=types.SimpleNamespace(free=100 * GIB),
                ),
                self.assertRaises(ModelProvisioningCancelled),
            ):
                ProductionModelProvisioner(cache.root).provision_all(
                    progress_callback=progress,
                    cancellation_check=lambda: cancelled,
                )

            first_snapshot = cache.snapshot_path(PRODUCTION_MODELS[0].repo_id)
            self.assertTrue((first_snapshot / "model.safetensors").is_file())

        self.assertEqual(downloads, [PRODUCTION_MODELS[0].repo_id])
        self.assertNotIn(ProvisioningState.COMPLETE, [event.state for event in events])
        self.assertEqual(events[-1].state, ProvisioningState.CANCELLED)


if __name__ == "__main__":
    unittest.main()
