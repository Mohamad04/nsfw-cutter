from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.analysis.qwen3vl_binary_capability as qwen
from services.analysis.qwen3vl_binary_capability import (
    Qwen3VLArtifactIntegrityError,
    Qwen3VLArtifactResolver,
    Qwen3VLBenchmarkError,
    Qwen3VLCudaOutOfMemoryError,
    Qwen3VLModelContractError,
    Qwen3VLModelLoadError,
    Qwen3VLRuntime,
    QwenGeneration,
    QwenRuntimeProvenance,
    extract_processor_metrics,
)
from services.analysis.smolvlm_verifier import synthetic_verification_request
from services.analysis.smolvlm_visual_capability import (
    CATEGORY_QUESTIONS,
    BinaryAnswer,
    CategoryBinaryMetrics,
    parse_binary_answer,
)


class FakeTensor:
    def __init__(self, shape: tuple[int, ...], values: object | None = None) -> None:
        self.shape = shape
        self.ndim = len(shape)
        self._values = values

    def tolist(self) -> object:
        return self._values


def _provenance() -> QwenRuntimeProvenance:
    return QwenRuntimeProvenance(
        repository_id=qwen.MODEL_REPOSITORY_ID,
        revision=qwen.MODEL_REVISION,
        checkpoint_sha256=qwen.MODEL_WEIGHTS_SHA256,
        model_class=qwen.EXPECTED_MODEL_CLASS,
        processor_class=qwen.EXPECTED_PROCESSOR_CLASS,
        parameter_count=qwen.EXPECTED_PARAMETER_COUNT,
        model_dtype="bfloat16",
        device="cuda",
        transformers_version="test",
        torch_version="test",
        attention_implementation="sdpa",
        gpu_name="test GPU",
        gpu_total_memory_bytes=8_000_000_000,
        gpu_compute_capability=(8, 6),
        cuda_bf16_supported=True,
        steady_model_cuda_allocated_bytes=4_000_000_000,
        steady_model_cuda_reserved_bytes=4_100_000_000,
    )


def test_resolver_verifies_manifest_and_never_requests_main_or_pickle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"model.safetensors": b"weights", "config.json": b"{}"}
    manifest = {
        name: (len(payload), hashlib.sha256(payload).hexdigest())
        for name, payload in files.items()
    }
    monkeypatch.setattr(qwen, "MODEL_FILE_MANIFEST", manifest)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for name, payload in files.items():
        (snapshot / name).write_bytes(payload)
    requested: list[dict[str, object]] = []

    def download(**kwargs: object) -> str:
        requested.append(kwargs)
        return str(snapshot / str(kwargs["filename"]))

    artifact = Qwen3VLArtifactResolver(
        model_cache_dir=tmp_path / "cache", hub_download=download
    ).resolve(local_files_only=True)

    assert artifact.weights_path.name == "model.safetensors"
    assert [item["filename"] for item in requested] == list(manifest)
    assert all(item["revision"] == qwen.MODEL_REVISION for item in requested)
    assert all(item["revision"] != "main" for item in requested)
    assert all(item["filename"] != "pytorch_model.bin" for item in requested)


def test_resolver_rejects_wrong_checkpoint_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"wrong")
    monkeypatch.setattr(
        qwen,
        "MODEL_FILE_MANIFEST",
        {"model.safetensors": (5, hashlib.sha256(b"right").hexdigest())},
    )
    with pytest.raises(Qwen3VLArtifactIntegrityError, match="SHA-256"):
        Qwen3VLArtifactResolver(
            model_cache_dir=tmp_path,
            hub_download=lambda **_: str(weights),
        ).resolve()


@pytest.mark.parametrize(
    ("cuda_available", "bf16_supported", "message"),
    [(False, True, "CUDA"), (True, False, "BF16")],
)
def test_cuda_bf16_requirement_is_explicit(
    cuda_available: bool, bf16_supported: bool, message: str
) -> None:
    torch_module = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: cuda_available,
            is_bf16_supported=lambda: bf16_supported,
        )
    )
    with pytest.raises(Qwen3VLModelLoadError, match=message):
        qwen._validate_cuda_bf16(torch_module)


def test_native_runtime_class_validation_rejects_lookalikes() -> None:
    Qwen3VLProcessor = type(qwen.EXPECTED_PROCESSOR_CLASS, (), {})
    Qwen3VLModel = type(qwen.EXPECTED_MODEL_CLASS, (), {})
    qwen.validate_runtime_classes(
        Qwen3VLProcessor(),
        Qwen3VLModel(),
        expected_processor_class=Qwen3VLProcessor,
        expected_model_class=Qwen3VLModel,
    )
    with pytest.raises(Qwen3VLModelContractError, match="processor"):
        qwen.validate_runtime_classes(
            object(),
            Qwen3VLModel(),
            expected_processor_class=Qwen3VLProcessor,
            expected_model_class=Qwen3VLModel,
        )


def test_processor_metrics_use_actual_grid_and_merge_contract() -> None:
    request = synthetic_verification_request(3)
    encoded = {
        "pixel_values": FakeTensor((864, 1536)),
        "image_grid_thw": FakeTensor(
            (3, 3),
            [[1, 12, 24], [1, 12, 24], [1, 12, 24]],
        ),
        "input_ids": FakeTensor((1, 300)),
    }
    metrics = extract_processor_metrics(
        encoded,
        request,
        patch_size=16,
        merge_size=2,
    )
    assert metrics.total_visual_tokens == 216
    assert metrics.images[0].processed.width == 384
    assert metrics.images[0].processed.height == 192
    assert metrics.images[0].grid_thw == (1, 12, 24)
    assert metrics.input_sequence_length == 300


def test_processor_metrics_reject_image_grid_count_mismatch() -> None:
    request = synthetic_verification_request(3)
    encoded = {
        "pixel_values": FakeTensor((288, 1536)),
        "image_grid_thw": FakeTensor((1, 3), [[1, 12, 24]]),
        "input_ids": FakeTensor((1, 100)),
    }
    with pytest.raises(Qwen3VLModelContractError, match="count"):
        extract_processor_metrics(encoded, request, patch_size=16, merge_size=2)


def test_qwen_adapter_reuses_exact_questions_and_binary_parser() -> None:
    request = synthetic_verification_request(1)
    conversation = qwen.build_qwen_binary_conversation(request, "drugs")
    text = " ".join(
        str(item.get("text", "")) for item in conversation[0]["content"]
    )
    assert CATEGORY_QUESTIONS["drugs"] in text
    assert text.endswith("Answer only YES or NO.")
    assert parse_binary_answer(" YES. \n") == BinaryAnswer.YES
    assert parse_binary_answer("NO because it is safe") == BinaryAnswer.UNVERIFIED


def test_provider_is_lazy() -> None:
    resolver = SimpleNamespace(calls=0)

    def resolve(**_: object) -> object:
        resolver.calls += 1
        return object()

    resolver.resolve = resolve
    qwen.Qwen3VLProvider(resolver=resolver)  # type: ignore[arg-type]
    assert resolver.calls == 0


def test_six_image_gate_prevents_capability_run() -> None:
    smoke = qwen.QwenSmokeReport(
        artifact_resolution_seconds=0.0,
        model_load_seconds=0.0,
        provenance=_provenance(),
        token_budget=qwen.QwenOutputTokenBudget(
            candidate_token_counts={"YES": 1, "NO": 1, "YES.": 2, "NO.": 2},
            eos_token_ids=(1,),
            max_new_tokens=3,
        ),
        cache_validation={},
        cases=(),
        six_image_gate_passed=False,
    )
    with pytest.raises(Qwen3VLBenchmarkError, match="Six-image smoke gate"):
        qwen.evaluate_binary_capability(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            event_artifact_path="events.json",
            ground_truth_path="gt.json",
            frame_cache_root="cache",
            provider=None,  # type: ignore[arg-type]
            smoke=smoke,
            smol_baseline_path="smol.json",
        )


def test_cuda_oom_is_not_converted_to_binary_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOOM(RuntimeError):
        pass

    class InferenceMode:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: object) -> None:
            return None

    torch_module = SimpleNamespace(
        OutOfMemoryError=FakeOOM,
        bfloat16="bf16",
        inference_mode=lambda: InferenceMode(),
        cuda=SimpleNamespace(
            reset_peak_memory_stats=lambda: None,
            synchronize=lambda: None,
            empty_cache=lambda: None,
            max_memory_allocated=lambda: 1,
            max_memory_reserved=lambda: 2,
        ),
    )
    runtime = Qwen3VLRuntime(
        torch=torch_module,
        processor=None,
        model=SimpleNamespace(
            generate=lambda **_: (_ for _ in ()).throw(FakeOOM("oom"))
        ),
        provenance=_provenance(),
        patch_size=16,
        merge_size=2,
    )
    prepared = qwen.PreparedQwenRequest(
        model_inputs={},
        prompt_input_length=10,
        chat_template_seconds=0.01,
        processor_seconds=0.02,
        processor_metrics=qwen.QwenProcessorMetrics(
            input_image_count=1,
            images=(
                qwen.QwenImageMetric(
                    source=qwen.ImageDimensions(width=4, height=4),
                    processed=qwen.ImageDimensions(width=32, height=32),
                    grid_thw=(1, 2, 2),
                    visual_tokens=1,
                ),
            ),
            pixel_values_shape=(4, 1536),
            image_grid_thw_shape=(1, 3),
            input_ids_shape=(1, 10),
            total_visual_tokens=1,
            input_sequence_length=10,
        ),
    )
    monkeypatch.setattr(runtime, "prepare", lambda *_, **__: prepared)
    with pytest.raises(Qwen3VLCudaOutOfMemoryError):
        runtime.generate_binary(
            synthetic_verification_request(1), "weapons", max_new_tokens=3
        )


def test_target_interval_records_remain_explicit() -> None:
    overlap = SimpleNamespace(interval_id="silver:weapons", exact_overlap=True)
    record = SimpleNamespace(silver_overlaps=(overlap,))
    assert qwen.records_for_interval((record,), "silver:weapons") == (record,)
    assert qwen.records_for_interval((record,), "silver:drugs") == ()


def test_report_models_serialize_without_pixels() -> None:
    generation = QwenGeneration(
        event_id="event:1",
        raw_generated_text="YES",
        error=None,
        truncated=False,
        generated_token_count=2,
        chat_template_seconds=0.01,
        processor_seconds=0.02,
        generation_seconds=0.03,
        decode_seconds=0.001,
        total_seconds=0.061,
        tokens_per_second=66.0,
        peak_cuda_allocated_bytes=1,
        peak_cuda_reserved_bytes=2,
        processor_metrics=None,
        provenance=_provenance(),
    )
    payload = json.loads(generation.model_dump_json())
    assert payload["raw_generated_text"] == "YES"
    assert "images" not in payload
    assert "pixel_values" not in payload


def test_latency_summary_and_comparison_aggregation(tmp_path: Path) -> None:
    generations = tuple(
        QwenGeneration(
            event_id=str(index),
            raw_generated_text="YES",
            error=None,
            truncated=False,
            generated_token_count=2,
            chat_template_seconds=0.0,
            processor_seconds=0.1,
            generation_seconds=float(index),
            decode_seconds=0.0,
            total_seconds=float(index) + 0.1,
            tokens_per_second=2.0 / index,
            peak_cuda_allocated_bytes=index,
            peak_cuda_reserved_bytes=index + 1,
            processor_metrics=None,
            provenance=_provenance(),
        )
        for index in (1, 2)
    )
    summary = qwen.summarize_latency(generations)
    assert summary.mean_request_seconds == pytest.approx(1.6)
    assert summary.maximum_request_seconds == pytest.approx(2.1)

    category_metrics = tuple(
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
        for category in qwen.CATEGORY_IDS
    )
    qwen_summary = qwen.QwenBinarySummary(
        event_count=1,
        request_count=6,
        valid_yes_no_count=6,
        valid_yes_no_rate=1.0,
        valid_yes_count=6,
        valid_no_count=0,
        unverified_count=0,
        known_unsafe_detected_intervals=1,
        total_intervals=1,
        known_unsafe_recall=1.0,
        category_detected_intervals=1,
        category_aware_recall=1.0,
        category_metrics=category_metrics,
        missed_interval_ids=(),
        latency=summary,
        latency_by_image_count={1: summary},
        peak_cuda_allocated_bytes=10,
        peak_cuda_reserved_bytes=20,
    )
    smol_path = tmp_path / "smol.json"
    smol_path.write_text(
        json.dumps(
            {
                "summary": {
                    "valid_yes_no_rate": 0.5,
                    "known_unsafe_recall": 0.5,
                    "category_aware_recall": 0.25,
                    "latency": {
                        "total_request_seconds": 4.0,
                        "total_generation_seconds": 3.0,
                        "mean_request_seconds": 2.0,
                    },
                    "category_metrics": [
                        {"category": category, "recall": 0.5}
                        for category in qwen.CATEGORY_IDS
                    ],
                },
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    comparison = qwen.compare_with_smol(qwen_summary, smol_path)
    assert comparison.metrics["category_aware_recall"] == {
        "smolvlm2_500m": 0.25,
        "qwen3vl_2b": 1.0,
    }


def test_module_has_no_movie_or_preprocessing_execution_dependencies() -> None:
    source = Path(qwen.__file__).read_text(encoding="utf-8").lower()
    assert "ffmpeg" not in source
    assert "moviepreprocessingservice" not in source
    assert "decord" not in source
