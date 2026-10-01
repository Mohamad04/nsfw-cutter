from __future__ import annotations

import os

import pytest

from services.analysis.smolvlm_verifier import (
    EXPECTED_MODEL_CLASS,
    EXPECTED_PARAMETER_COUNT,
    EXPECTED_PROCESSOR_CLASS,
    MODEL_WEIGHTS_SHA256,
    SmolVLMArtifactResolver,
    SmolVLMRuntimeFactory,
    synthetic_verification_request,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("NSFW_CUTTER_RUN_SMOLVLM_INTEGRATION_TESTS") != "1",
    reason=(
        "set NSFW_CUTTER_RUN_SMOLVLM_INTEGRATION_TESTS=1 to load the pinned ~2 GB model"
    ),
)


def test_pinned_smolvlm_cpu_multi_image_contract() -> None:
    artifact = SmolVLMArtifactResolver().resolve(
        local_files_only=os.environ.get("NSFW_CUTTER_MODEL_LOCAL_FILES_ONLY") == "1"
    )
    assert artifact.sha256 == MODEL_WEIGHTS_SHA256
    runtime = SmolVLMRuntimeFactory().create(artifact, device="cpu")
    assert runtime.provenance.model_class == EXPECTED_MODEL_CLASS
    assert runtime.provenance.processor_class == EXPECTED_PROCESSOR_CLASS
    assert runtime.provenance.parameter_count == EXPECTED_PARAMETER_COUNT

    # A one-token smoke generation explicitly tests the published pad/generation config
    # without manually repairing any token ID.
    runtime.validate_generation_contract(image_count=1, max_new_tokens=1)
    for image_count in (1, 3, 6):
        request = synthetic_verification_request(image_count)
        prepared = runtime.prepare(
            request,
            max_new_tokens=32,
            image_splitting=True,
        )
        assert prepared.expansion.input_image_count == image_count
        assert prepared.expansion.visual_block_count >= image_count
        assert prepared.expansion.visual_token_count > 0
        assert prepared.expansion.remaining_context_after_requested_generation >= 0
        result = runtime.verify(
            request,
            max_new_tokens=32,
            image_splitting=True,
        )
        assert result.generated_token_count > 0
        assert result.expansion is not None
        assert result.raw_generated_text is not None


def test_official_split_disable_processor_path() -> None:
    artifact = SmolVLMArtifactResolver().resolve(local_files_only=True)
    runtime = SmolVLMRuntimeFactory().create(artifact, device="cpu")
    assert runtime.image_splitting_supported
    default = runtime.prepare(
        synthetic_verification_request(1),
        max_new_tokens=32,
        image_splitting=True,
    ).expansion
    disabled = runtime.prepare(
        synthetic_verification_request(1),
        max_new_tokens=32,
        image_splitting=False,
    ).expansion
    assert disabled.visual_block_count <= default.visual_block_count
    assert disabled.visual_token_count <= default.visual_token_count
