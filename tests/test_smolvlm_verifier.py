from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from services.analysis import smolvlm_verifier as smolvlm
from services.analysis.cancellation import CancellationToken
from services.analysis.smolvlm_benchmark import (
    SmolVLMBenchmarkIteration,
    _is_single_json_object,
    summarize_benchmark_case,
)
from services.analysis.smolvlm_verifier import (
    EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    GeneratedVerificationPayload,
    ProcessorExpansionMetrics,
    SmolVLMArtifactIntegrityError,
    SmolVLMArtifactResolver,
    SmolVLMRuntime,
    SmolVLMRuntimeProvenance,
    SmolVLMVerifier,
    VerificationPolicy,
    VerificationStatus,
    VLMFrameDescriptor,
    VLMVerificationRequest,
    VLMVerificationRequestMetadata,
    parse_verification_json,
    synthetic_verification_request,
)


def _metadata(frame_count: int = 2) -> VLMVerificationRequestMetadata:
    return VLMVerificationRequestMetadata(
        event_id="event-1",
        frames=tuple(
            VLMFrameDescriptor(
                frame_index=index,
                timestamp_us=index * 1_000_000,
                selection_reasons=("test",),
            )
            for index in range(1, frame_count + 1)
        ),
        policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    )


def _valid_unsafe_json(**changes: object) -> str:
    payload: dict[str, object] = {
        "unsafe": True,
        "categories": ["weapons"],
        "severity": "high",
        "reason": "A firearm is visible.",
        "evidence_frame_indices": [1],
    }
    payload.update(changes)
    return json.dumps(payload)


def _provenance() -> SmolVLMRuntimeProvenance:
    return SmolVLMRuntimeProvenance(
        repository_id=smolvlm.MODEL_REPOSITORY_ID,
        revision=smolvlm.MODEL_REVISION,
        checkpoint_sha256=smolvlm.MODEL_WEIGHTS_SHA256,
        model_class=smolvlm.EXPECTED_MODEL_CLASS,
        processor_class=smolvlm.EXPECTED_PROCESSOR_CLASS,
        parameter_count=smolvlm.EXPECTED_PARAMETER_COUNT,
        model_dtype="float32",
        device="cpu",
        transformers_version="test",
        torch_version="test",
        attention_implementation="sdpa",
    )


def _expansion() -> ProcessorExpansionMetrics:
    return ProcessorExpansionMetrics(
        image_splitting=True,
        input_image_count=1,
        original_image_dimensions=({"width": 384, "height": 384},),
        pixel_values_shape=(1, 17, 3, 512, 512),
        visual_block_count=17,
        pixel_attention_mask_shape=(1, 17, 512, 512),
        input_ids_shape=(1, 1200),
        pre_expansion_prompt_token_count=120,
        visual_token_count=1088,
        non_visual_input_token_count=112,
        input_sequence_length=1200,
        declared_context_length=8192,
        remaining_context_before_generation=6992,
        remaining_context_after_requested_generation=6960,
    )


def test_artifact_resolver_verifies_pinned_manifest_and_never_requests_pickle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        "model.safetensors": b"safe tensors",
        "config.json": b"{}",
    }
    manifest = {
        name: (len(content), hashlib.sha256(content).hexdigest())
        for name, content in files.items()
    }
    monkeypatch.setattr(smolvlm, "MODEL_FILE_MANIFEST", manifest)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for name, content in files.items():
        (snapshot / name).write_bytes(content)
    requested: list[str] = []

    def download(**kwargs: object) -> str:
        requested.append(str(kwargs["filename"]))
        assert kwargs["revision"] == smolvlm.MODEL_REVISION
        return str(snapshot / str(kwargs["filename"]))

    artifact = SmolVLMArtifactResolver(
        model_cache_dir=tmp_path / "cache", hub_download=download
    ).resolve(local_files_only=True)

    assert requested == list(manifest)
    assert "pytorch_model.bin" not in requested
    assert artifact.weights_path.name == "model.safetensors"


def test_artifact_resolver_rejects_wrong_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "model.safetensors"
    path.write_bytes(b"wrong")
    monkeypatch.setattr(
        smolvlm,
        "MODEL_FILE_MANIFEST",
        {"model.safetensors": (5, hashlib.sha256(b"right").hexdigest())},
    )

    with pytest.raises(SmolVLMArtifactIntegrityError, match="SHA-256"):
        SmolVLMArtifactResolver(
            model_cache_dir=tmp_path,
            hub_download=lambda **_: str(path),
        ).resolve()


def test_verifier_is_lazy() -> None:
    resolver = SimpleNamespace(calls=0)

    def resolve(**_: object) -> None:
        resolver.calls += 1

    resolver.resolve = resolve
    SmolVLMVerifier(resolver=resolver)  # type: ignore[arg-type]
    assert resolver.calls == 0


def test_verification_policy_rejects_duplicate_allowlists() -> None:
    with pytest.raises(ValidationError, match="unique"):
        VerificationPolicy(
            policy_id="test",
            version="1",
            allowed_categories=("weapons", "weapons"),
            allowed_severities=("low",),
            prompt_template_version="1",
        )


def test_request_requires_ordered_matching_rgb_frames() -> None:
    metadata = _metadata(2)
    images = (
        Image.new("RGB", (4, 4)),
        Image.new("RGB", (4, 4)),
    )
    request = VLMVerificationRequest(metadata=metadata, images=images)
    assert [frame.timestamp_us for frame in request.metadata.frames] == [
        1_000_000,
        2_000_000,
    ]

    with pytest.raises(smolvlm.SmolVLMRequestError, match="count"):
        VLMVerificationRequest(metadata=metadata, images=images[:1])
    with pytest.raises(smolvlm.SmolVLMRequestError, match="RGB"):
        VLMVerificationRequest(metadata=_metadata(1), images=(Image.new("L", (4, 4)),))


def test_prompt_contains_exact_policy_allowlists_and_no_timestamps() -> None:
    conversation = smolvlm._build_conversation(_metadata(2))
    text = " ".join(item.get("text", "") for item in conversation[0]["content"])
    for category in EXPERIMENTAL_VISUAL_SAFETY_POLICY.allowed_categories:
        assert category in text
    for severity in EXPERIMENTAL_VISUAL_SAFETY_POLICY.allowed_severities:
        assert severity in text
    assert "Frame 1" in text and "Frame 2" in text
    assert "timestamp_us" not in text


def test_strict_json_parser_accepts_valid_unsafe_and_safe_payloads() -> None:
    unsafe = parse_verification_json(_valid_unsafe_json(), _metadata())
    assert unsafe.unsafe is True
    safe = parse_verification_json(
        json.dumps(
            {
                "unsafe": False,
                "categories": [],
                "severity": None,
                "reason": "No listed visual evidence is visible.",
                "evidence_frame_indices": [],
            }
        ),
        _metadata(),
    )
    assert safe.unsafe is False


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("```json\n{}\n```", "Expecting value"),
        (_valid_unsafe_json(categories=["unknown"]), "outside the policy"),
        (_valid_unsafe_json(severity="critical"), "policy-approved severity"),
        (_valid_unsafe_json(evidence_frame_indices=[3]), "unavailable evidence"),
        (_valid_unsafe_json(timestamp="00:01:00"), "Extra inputs"),
        (_valid_unsafe_json(unsafe="true"), "valid boolean"),
    ],
)
def test_strict_json_parser_rejects_malformed_or_untrusted_output(
    raw: str, match: str
) -> None:
    with pytest.raises((ValueError, TypeError, ValidationError), match=match):
        parse_verification_json(raw, _metadata())


def test_safe_payload_cannot_claim_categories_or_evidence() -> None:
    with pytest.raises(ValueError, match="safe output"):
        parse_verification_json(
            _valid_unsafe_json(unsafe=False, severity=None),
            _metadata(),
        )


def test_cancelled_request_is_unverified_without_calling_model() -> None:
    token = CancellationToken()
    token.cancel()
    runtime = SmolVLMRuntime(
        torch=None,
        processor=None,
        model=SimpleNamespace(generate=lambda **_: pytest.fail("must not generate")),
        provenance=_provenance(),
        context_length=8192,
        image_splitting_supported=True,
    )
    result = runtime.verify(
        synthetic_verification_request(1),
        max_new_tokens=32,
        cancellation=token,
    )
    assert result.status == VerificationStatus.UNVERIFIED
    assert "cancelled" in (result.error or "")


def test_model_exception_is_unverified_not_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInferenceMode:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: object) -> None:
            return None

    runtime = SmolVLMRuntime(
        torch=SimpleNamespace(inference_mode=lambda: FakeInferenceMode()),
        processor=None,
        model=SimpleNamespace(
            generate=lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))
        ),
        provenance=_provenance(),
        context_length=8192,
        image_splitting_supported=True,
    )
    prepared = smolvlm.PreparedSmolVLMRequest(
        model_inputs={},
        prompt_input_length=10,
        prompt_text="prompt",
        chat_template_seconds=0.01,
        processor_seconds=0.02,
        expansion=_expansion(),
    )
    monkeypatch.setattr(runtime, "prepare", lambda *_, **__: prepared)
    result = runtime.verify(synthetic_verification_request(1), max_new_tokens=32)
    assert result.status == VerificationStatus.UNVERIFIED
    assert result.payload is None
    assert "generation failed" in (result.error or "")


def test_generated_payload_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GeneratedVerificationPayload.model_validate(
            {
                "unsafe": False,
                "categories": [],
                "severity": None,
                "reason": "Safe.",
                "evidence_frame_indices": [],
                "confidence": 0.9,
            }
        )


def test_benchmark_statistics_are_deterministic() -> None:
    measurements = tuple(
        SmolVLMBenchmarkIteration(
            processor_seconds=0.1,
            chat_template_seconds=0.01,
            generation_seconds=float(index),
            total_seconds=float(index) + 0.11,
            generated_tokens=10,
            tokens_per_second=10.0 / index,
            visual_blocks=17,
            visual_tokens=1088,
            input_sequence_length=1200,
            valid_json=index == 1,
            pydantic_valid_json=index == 1,
            status=(
                VerificationStatus.VERIFIED_SAFE
                if index == 1
                else VerificationStatus.UNVERIFIED
            ),
            error=None if index == 1 else "invalid",
        )
        for index in (1, 2)
    )
    result = summarize_benchmark_case(
        image_count=1,
        max_new_tokens=32,
        image_splitting=True,
        warmup_runs=1,
        measurements=measurements,
    )
    assert result.mean_generation_seconds == 1.5
    assert result.strict_json_success_rate == 0.5
    assert result.unverified_count == 1


def test_benchmark_distinguishes_json_syntax_from_strict_validation() -> None:
    assert _is_single_json_object('{"unsafe": true}') is True
    assert _is_single_json_object("```json\n{}\n```") is False
    assert _is_single_json_object("[]") is False


def test_module_has_no_video_decoder_dependencies() -> None:
    source = Path(smolvlm.__file__).read_text(encoding="utf-8")
    assert "decord" not in source
    assert "ffmpeg" not in source.lower()
