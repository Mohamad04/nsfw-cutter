from __future__ import annotations

import os

import pytest

from services.analysis.smolvlm22_binary_capability import (
    create_smolvlm22_verifier,
    minimum_binary_token_budget,
)
from services.analysis.smolvlm_verifier import synthetic_verification_request
from services.analysis.smolvlm_visual_capability import build_binary_conversation


@pytest.mark.skipif(
    os.environ.get("NSFW_CUTTER_RUN_SMOLVLM22_INTEGRATION_TESTS") != "1",
    reason="set NSFW_CUTTER_RUN_SMOLVLM22_INTEGRATION_TESTS=1 explicitly",
)
def test_real_smolvlm22_cuda_bf16_binary_path() -> None:
    verifier = create_smolvlm22_verifier(local_files_only=False)
    runtime = verifier.runtime()
    budget = minimum_binary_token_budget(runtime.processor.tokenizer)
    request = synthetic_verification_request(1)
    result = runtime.generate_raw(
        request,
        build_binary_conversation(request.metadata, "weapons"),
        max_new_tokens=budget.configured_max_new_tokens,
        image_splitting=False,
    )
    assert result.error is None
    assert result.expansion is not None
    assert result.expansion.input_image_count == 1
    assert result.generated_token_count > 0
