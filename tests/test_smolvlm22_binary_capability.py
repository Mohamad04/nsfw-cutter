from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.analysis.smolvlm22_binary_capability as smol22
from services.analysis.qwen3vl_binary_capability import LatencySummary
from services.analysis.smolvlm_verifier import (
    RawSmolVLMGeneration,
    SmolVLMArtifactIntegrityError,
    SmolVLMArtifactResolver,
    SmolVLMArtifactUnavailableError,
    SmolVLMModelLoadError,
    SmolVLMModelSpec,
    SmolVLMRuntimeProvenance,
    SmolVLMVerifier,
    default_smolvlm_model_spec,
)
from services.analysis.smolvlm_visual_capability import (
    CATEGORY_IDS,
    BinaryCapabilitySummary,
    CategoryBinaryMetrics,
    OutputTokenBudgetInspection,
    RequestLatencyMetrics,
)


def _test_spec(manifest: dict[str, tuple[int, str]]) -> SmolVLMModelSpec:
    return SmolVLMModelSpec(
        repository_id="test/model",
        revision="a" * 40,
        file_manifest=manifest,
        primary_artifact_filename=next(iter(manifest)),
        primary_artifact_sha256=next(iter(manifest.values()))[1],
        expected_model_class="SmolVLMForConditionalGeneration",
        expected_processor_class="SmolVLMProcessor",
        expected_parameter_count=123,
        expected_context_length=8192,
    )


def _runtime_provenance() -> SmolVLMRuntimeProvenance:
    return SmolVLMRuntimeProvenance(
        repository_id=smol22.MODEL_REPOSITORY_ID,
        revision=smol22.MODEL_REVISION,
        checkpoint_sha256=smol22.MODEL_FILE_MANIFEST[smol22.MODEL_SHARD_1][1],
        model_class=smol22.EXPECTED_MODEL_CLASS,
        processor_class=smol22.EXPECTED_PROCESSOR_CLASS,
        parameter_count=smol22.EXPECTED_PARAMETER_COUNT,
        model_dtype="bfloat16",
        device="cuda",
        transformers_version="test",
        torch_version="test",
        attention_implementation="sdpa",
    )


def _smoke(gate: bool) -> smol22.SmolVLM22SmokeReport:
    return smol22.SmolVLM22SmokeReport(
        artifact_resolution_seconds=0.0,
        model_load_seconds=0.0,
        provenance=smol22.SmolVLM22RuntimeProvenance(
            repository_id=smol22.MODEL_REPOSITORY_ID,
            revision=smol22.MODEL_REVISION,
            shard_sha256={
                smol22.MODEL_SHARD_1: smol22.MODEL_FILE_MANIFEST[
                    smol22.MODEL_SHARD_1
                ][1],
                smol22.MODEL_SHARD_2: smol22.MODEL_FILE_MANIFEST[
                    smol22.MODEL_SHARD_2
                ][1],
            },
            model_class=smol22.EXPECTED_MODEL_CLASS,
            processor_class=smol22.EXPECTED_PROCESSOR_CLASS,
            parameter_count=smol22.EXPECTED_PARAMETER_COUNT,
            model_dtype="bfloat16",
            device="cuda",
            transformers_version="test",
            torch_version="test",
            attention_implementation="sdpa",
            gpu_name="test",
            gpu_total_memory_bytes=8_000_000_000,
            gpu_compute_capability=(8, 6),
            cuda_bf16_supported=True,
            steady_model_cuda_allocated_bytes=4_500_000_000,
            steady_model_cuda_reserved_bytes=4_600_000_000,
        ),
        file_manifest=smol22.MODEL_FILE_MANIFEST,
        token_budget=OutputTokenBudgetInspection(
            output_kind="binary",
            candidate_count=4,
            minimum_candidate_token_count=1,
            maximum_candidate_token_count=2,
            eos_token_id=1,
            required_max_new_tokens=3,
            configured_max_new_tokens=3,
        ),
        cache_validation={},
        cases=(),
        six_image_gate_passed=gate,
    )


def _category_metrics() -> tuple[CategoryBinaryMetrics, ...]:
    return tuple(
        CategoryBinaryMetrics(
            category=category,
            silver_intervals=1,
            detected_intervals=1,
            recall=1.0,
            yes_responses=1,
            no_responses=0,
            unverified_responses=0,
            total_generation_seconds=0.1,
            total_generated_tokens=2,
        )
        for category in CATEGORY_IDS
    )


def _binary_summary() -> BinaryCapabilitySummary:
    return BinaryCapabilitySummary(
        event_count=1,
        request_count=6,
        valid_yes_no_count=6,
        valid_yes_no_rate=1.0,
        unverified_count=0,
        unverified_rate=0.0,
        output_distribution={"yes": 6, "no": 0, "unverified": 0},
        detected_intervals=1,
        total_intervals=1,
        known_unsafe_recall=1.0,
        category_detected_intervals=1,
        category_aware_recall=1.0,
        category_metrics=_category_metrics(),
        missed_interval_ids=(),
        latency=RequestLatencyMetrics(
            request_count=6,
            total_generation_seconds=1.0,
            total_request_seconds=2.0,
            mean_request_seconds=1 / 3,
            p50_request_seconds=0.3,
            p90_request_seconds=0.4,
            total_generated_tokens=12,
        ),
    )


def _performance() -> smol22.SmolVLM22PerformanceSummary:
    latency = LatencySummary(
        request_count=6,
        total_processor_seconds=0.5,
        total_generation_seconds=1.0,
        total_request_seconds=2.0,
        mean_request_seconds=1 / 3,
        p50_request_seconds=0.3,
        p90_request_seconds=0.4,
        p95_request_seconds=0.45,
        maximum_request_seconds=0.5,
        total_generated_tokens=12,
    )
    return smol22.SmolVLM22PerformanceSummary(
        latency=latency,
        latency_by_image_count={1: latency},
        peak_cuda_allocated_bytes=10,
        peak_cuda_reserved_bytes=20,
    )


def test_22b_model_spec_is_exact_and_not_500m() -> None:
    spec = smol22.SMOLVLM22_MODEL_SPEC
    assert spec.repository_id == "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
    assert spec.revision == "482adb537c021c86670beed01cd58990d01e72e4"
    assert spec.expected_parameter_count == 2_246_784_880
    assert spec.repository_id != default_smolvlm_model_spec().repository_id
    assert {name for name in spec.file_manifest if name.endswith(".safetensors")} == {
        smol22.MODEL_SHARD_1,
        smol22.MODEL_SHARD_2,
    }
    assert smol22.MODEL_INDEX in spec.file_manifest


def test_two_shards_and_index_are_verified_without_fallback(tmp_path: Path) -> None:
    payloads = {
        "model-00001-of-00002.safetensors": b"one",
        "model-00002-of-00002.safetensors": b"two",
        "model.safetensors.index.json": b"{}",
    }
    manifest = {
        name: (len(payload), hashlib.sha256(payload).hexdigest())
        for name, payload in payloads.items()
    }
    spec = _test_spec(manifest)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for name, payload in payloads.items():
        (snapshot / name).write_bytes(payload)
    requested: list[dict[str, object]] = []

    def download(**kwargs: object) -> str:
        requested.append(kwargs)
        return str(snapshot / str(kwargs["filename"]))

    artifact = SmolVLMArtifactResolver(
        model_cache_dir=tmp_path,
        hub_download=download,
        model_spec=spec,
    ).resolve(local_files_only=True)

    assert artifact.model_spec == spec
    assert [item["filename"] for item in requested] == list(manifest)
    assert all(item["revision"] == spec.revision for item in requested)
    assert all(item["filename"] != "model.safetensors" for item in requested)
    assert all(item["filename"] != "pytorch_model.bin" for item in requested)


def test_bad_shard_index_hash_is_rejected(tmp_path: Path) -> None:
    index = tmp_path / smol22.MODEL_INDEX
    index.write_bytes(b"wrong")
    manifest = {
        smol22.MODEL_INDEX: (5, hashlib.sha256(b"right").hexdigest())
    }
    with pytest.raises(SmolVLMArtifactIntegrityError, match="SHA-256"):
        SmolVLMArtifactResolver(
            model_cache_dir=tmp_path,
            hub_download=lambda **_: str(index),
            model_spec=_test_spec(manifest),
        ).resolve()


def test_mixed_snapshot_directories_are_rejected(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "a").write_bytes(b"a")
    (second / "b").write_bytes(b"b")
    manifest = {
        "a": (1, hashlib.sha256(b"a").hexdigest()),
        "b": (1, hashlib.sha256(b"b").hexdigest()),
    }
    with pytest.raises(SmolVLMArtifactUnavailableError, match="one local snapshot"):
        SmolVLMArtifactResolver(
            model_cache_dir=tmp_path,
            hub_download=lambda **kwargs: str(
                (first if kwargs["filename"] == "a" else second)
                / str(kwargs["filename"])
            ),
            model_spec=_test_spec(manifest),
        ).resolve()


def test_shared_verifier_accepts_22b_model_spec_without_loading() -> None:
    verifier = SmolVLMVerifier(
        model_spec=smol22.SMOLVLM22_MODEL_SPEC,
        device="cuda",
        dtype="bfloat16",
        attention_implementation="sdpa",
    )
    assert verifier.resolver.model_spec == smol22.SMOLVLM22_MODEL_SPEC
    assert verifier.dtype == "bfloat16"
    assert verifier.attention_implementation == "sdpa"
    assert verifier._runtime is None


def test_cuda_bf16_gate_rejects_unsupported_runtime(tmp_path: Path) -> None:
    torch_module = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            is_bf16_supported=lambda: False,
        )
    )
    factory = __import__(
        "services.analysis.smolvlm_verifier", fromlist=["SmolVLMRuntimeFactory"]
    ).SmolVLMRuntimeFactory(
        torch_module=torch_module,
        auto_processor_class=object(),
        auto_model_class=object(),
        expected_processor_class=object(),
        expected_model_class=object(),
        transformers_version="test",
    )
    artifact = SimpleNamespace(snapshot_dir=tmp_path, model_spec=smol22.SMOLVLM22_MODEL_SPEC)
    with pytest.raises(SmolVLMModelLoadError, match="BF16"):
        factory.create(artifact, device="cuda", dtype="bfloat16")


def test_six_image_gate_prevents_full_run() -> None:
    with pytest.raises(smol22.SmolVLM22BenchmarkError, match="Six-image smoke gate"):
        smol22.evaluate_binary_capability(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            event_artifact_path="events.json",
            ground_truth_path="gt.json",
            frame_cache_root="cache",
            verifier=None,  # type: ignore[arg-type]
            smoke=_smoke(False),
            smol500_path="smol.json",
            qwen_path="qwen.json",
        )


def test_three_model_comparison_uses_existing_artifacts(tmp_path: Path) -> None:
    def baseline(*, qwen: bool) -> dict[str, object]:
        summary = {
            "valid_yes_no_rate": 0.9,
            "known_unsafe_recall": 0.8,
            "category_aware_recall": 0.7,
            "latency": {
                "total_request_seconds": 4.0,
                "total_generation_seconds": 3.0,
                "mean_request_seconds": 0.2,
            },
            "category_metrics": [
                {"category": category, "recall": 0.5}
                for category in CATEGORY_IDS
            ],
        }
        if qwen:
            summary["peak_cuda_allocated_bytes"] = 99
        events = [
            {
                "silver_overlaps": [
                    {"interval_id": "silver:000", "exact_overlap": True}
                ],
                "answers": [{"category": "drugs", "answer": "no"}],
            },
            {
                "silver_overlaps": [
                    {"interval_id": "silver:009", "exact_overlap": True}
                ],
                "answers": [{"category": "weapons", "answer": "yes"}],
            },
        ]
        return {"summary": summary, "events": events}

    smol_path = tmp_path / "smol.json"
    qwen_path = tmp_path / "qwen.json"
    smol_path.write_text(json.dumps(baseline(qwen=False)), encoding="utf-8")
    qwen_path.write_text(json.dumps(baseline(qwen=True)), encoding="utf-8")
    records = [
        SimpleNamespace(
            silver_overlaps=(
                SimpleNamespace(interval_id="silver:000", exact_overlap=True),
            ),
            answers=(SimpleNamespace(category="drugs", answer=SimpleNamespace(value="yes")),),
        ),
        SimpleNamespace(
            silver_overlaps=(
                SimpleNamespace(interval_id="silver:009", exact_overlap=True),
            ),
            answers=(SimpleNamespace(category="weapons", answer=SimpleNamespace(value="no")),),
        ),
    ]
    comparison = smol22.compare_three_models(
        records,  # type: ignore[arg-type]
        _binary_summary(),
        _performance(),
        smol500_path=smol_path,
        qwen_path=qwen_path,
    )
    assert comparison.metrics["marijuana_drugs_answer"]["smolvlm2_2_2b"] == "yes"
    assert comparison.metrics["weapons_answer"]["smolvlm2_2_2b"] == "no"
    assert comparison.metrics["peak_cuda_allocated_bytes"]["qwen3vl_2b"] == 99


def test_result_models_are_pixel_free_and_serializable() -> None:
    payload = json.loads(_smoke(False).model_dump_json())
    assert payload["provenance"]["model_dtype"] == "bfloat16"
    assert "images" not in payload
    assert "pixel_values" not in payload


def test_minimum_token_budget_uses_runtime_tokenization() -> None:
    class Tokenizer:
        eos_token_id = 7

        def __call__(self, value: str, **_: object) -> dict[str, list[int]]:
            return {"input_ids": [1, 2] if value.endswith(".") else [1]}

    budget = smol22.minimum_binary_token_budget(Tokenizer())
    assert budget.required_max_new_tokens == 3
    assert budget.configured_max_new_tokens == 3


def test_generation_provenance_can_represent_pinned_22b() -> None:
    generation = RawSmolVLMGeneration(
        event_id="event:1",
        raw_generated_text="YES",
        error=None,
        truncated=False,
        generated_token_count=2,
        chat_template_seconds=0.0,
        processor_seconds=0.0,
        generation_seconds=0.1,
        decode_seconds=0.0,
        total_seconds=0.1,
        tokens_per_second=20.0,
        expansion=None,
        provenance=_runtime_provenance(),
    )
    assert generation.provenance.repository_id == smol22.MODEL_REPOSITORY_ID
