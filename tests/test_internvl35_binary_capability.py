from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.analysis import internvl35_binary_capability as intern


def test_exact_model_specification() -> None:
    assert intern.MODEL_REPOSITORY_ID == "OpenGVLab/InternVL3_5-4B-HF"
    assert intern.MODEL_REVISION == "6bd4487402110ef9889ba50eb7aefeb302526fed"
    assert intern.MODEL_FILE_MANIFEST[intern.MODEL_SHARD_1][0] == 4_954_007_064
    assert intern.MODEL_FILE_MANIFEST[intern.MODEL_SHARD_2][0] == 4_511_078_400
    assert intern.MODEL_FILE_MANIFEST[intern.MODEL_INDEX][0] == 79_936


def test_resolver_pins_revision_and_rejects_mixed_snapshot(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    manifest = {"one": (1, hashlib.sha256(b"x").hexdigest()), "two": (1, hashlib.sha256(b"y").hexdigest())}
    (first / "one").write_bytes(b"x")
    (second / "two").write_bytes(b"y")
    requested: list[dict[str, object]] = []

    def download(**kwargs: object) -> str:
        requested.append(kwargs)
        return str((first / "one") if kwargs["filename"] == "one" else (second / "two"))

    original = intern.MODEL_FILE_MANIFEST
    intern.MODEL_FILE_MANIFEST = manifest
    try:
        with pytest.raises(intern.InternVL35ArtifactError, match="mixed"):
            intern.InternVL35ArtifactResolver(hub_download=download).resolve()
    finally:
        intern.MODEL_FILE_MANIFEST = original
    assert all(item["revision"] == intern.MODEL_REVISION for item in requested)
    assert all(item["repo_id"] == intern.MODEL_REPOSITORY_ID for item in requested)


def test_manifest_rejects_wrong_shard_hash(tmp_path: Path) -> None:
    file = tmp_path / "shard"
    file.write_bytes(b"bad")
    original = intern.MODEL_FILE_MANIFEST
    intern.MODEL_FILE_MANIFEST = {"shard": (3, "0" * 64)}
    try:
        with pytest.raises(intern.InternVL35ArtifactError, match="SHA-256"):
            intern.verify_file_manifest({"shard": file})
    finally:
        intern.MODEL_FILE_MANIFEST = original


def test_default_bitsandbytes_contract() -> None:
    class Config:
        def to_dict(self) -> dict[str, object]:
            return {
                "load_in_4bit": True,
                "bnb_4bit_quant_type": "fp4",
                "bnb_4bit_use_double_quant": False,
                "bnb_4bit_compute_dtype": "float32",
            }

    intern.validate_quantization_config(Config())


def test_quantization_contract_rejects_nf4() -> None:
    class Config:
        def to_dict(self) -> dict[str, object]:
            return {
                "load_in_4bit": True,
                "bnb_4bit_quant_type": "nf4",
                "bnb_4bit_use_double_quant": False,
                "bnb_4bit_compute_dtype": "float32",
            }

    with pytest.raises(intern.InternVL35ContractError, match="changed"):
        intern.validate_quantization_config(Config())


def test_cuda_bf16_and_rtx3070_gate() -> None:
    cuda = SimpleNamespace(
        is_available=lambda: True,
        is_bf16_supported=lambda: True,
        get_device_name=lambda _index: "NVIDIA GeForce RTX 3070",
    )
    intern.validate_cuda(SimpleNamespace(cuda=cuda))
    cuda.get_device_name = lambda _index: "another GPU"
    with pytest.raises(intern.InternVL35LoadError, match="RTX 3070"):
        intern.validate_cuda(SimpleNamespace(cuda=cuda))


def test_runtime_class_and_4bit_validation() -> None:
    Processor = type(intern.EXPECTED_PROCESSOR_CLASS, (), {})
    Model = type(intern.EXPECTED_MODEL_CLASS, (), {})
    model = Model()
    model.is_loaded_in_4bit = True
    intern.validate_runtime_classes(
        Processor(), model, expected_processor=Processor, expected_model=Model
    )
    model.is_loaded_in_4bit = False
    with pytest.raises(intern.InternVL35ContractError, match="not marked 4-bit"):
        intern.validate_runtime_classes(
            Processor(), model, expected_processor=Processor, expected_model=Model
        )


class FakeTensor:
    def __init__(self, shape: tuple[int, ...], *, matches: int = 0) -> None:
        self.shape = shape
        self.ndim = len(shape)
        self.matches = matches

    def __eq__(self, _other: object) -> FakeTensor:
        return self

    def sum(self) -> SimpleNamespace:
        return SimpleNamespace(item=lambda: self.matches)


def test_processor_metrics_verify_patch_and_visual_tokens() -> None:
    images = tuple(SimpleNamespace(width=384, height=206) for _ in range(6))
    request = SimpleNamespace(images=images)
    image_processor = SimpleNamespace(
        get_number_of_image_patches=lambda *_args, **_kwargs: 3
    )
    processor = SimpleNamespace(
        image_token_id=42, image_seq_length=256, image_processor=image_processor
    )
    metrics = intern.extract_processor_metrics(
        {
            "pixel_values": FakeTensor((18, 3, 448, 448)),
            "input_ids": FakeTensor((1, 4700), matches=4608),
        },
        request,
        processor,
    )
    assert metrics.patch_count == 18
    assert metrics.total_visual_tokens == 4608


def test_six_image_gate_prevents_capability_run() -> None:
    smoke = SimpleNamespace(six_image_gate_passed=False)
    with pytest.raises(intern.InternVL35BenchmarkError, match="forbidden"):
        intern.evaluate_binary_capability(
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            event_artifact_path="events.json",
            ground_truth_path="gt.json",
            frame_cache_root="cache",
            provider=SimpleNamespace(),
            smoke=smoke,
            baseline_paths={},
        )


def test_comparison_requires_exact_baseline_keys() -> None:
    with pytest.raises(intern.InternVL35BenchmarkError, match="Baseline keys"):
        intern.compare_four_models([], SimpleNamespace(), SimpleNamespace(), {})


def test_report_models_serialize_without_pixels() -> None:
    fields = intern.InternVLCapabilityReport.model_fields
    assert "events" in fields
    assert "images" not in fields
    assert "movie" not in fields


def test_module_has_no_movie_or_inference_pipeline_imports() -> None:
    source = Path(intern.__file__).read_text(encoding="utf-8")
    assert "ffmpeg" not in source.casefold()
    assert "onnxruntime" not in source.casefold()
    assert "MoviePreprocessingService" not in source
