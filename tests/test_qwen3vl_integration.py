from __future__ import annotations

import os

import pytest

from services.analysis.qwen3vl_binary_capability import (
    Qwen3VLProvider,
)
from services.analysis.smolvlm_verifier import synthetic_verification_request


@pytest.mark.skipif(
    os.environ.get("NSFW_CUTTER_RUN_QWEN3_VL_INTEGRATION_TESTS") != "1",
    reason="set NSFW_CUTTER_RUN_QWEN3_VL_INTEGRATION_TESTS=1 explicitly",
)
def test_real_qwen3vl_cuda_bf16_binary_path() -> None:
    provider = Qwen3VLProvider()
    runtime = provider.runtime()
    budget = runtime.inspect_output_budget()
    request = synthetic_verification_request(1)
    result = runtime.generate_binary(
        request,
        "weapons",
        max_new_tokens=budget.max_new_tokens,
    )
    assert result.error is None
    assert result.processor_metrics is not None
    assert result.processor_metrics.input_image_count == 1
    assert result.generated_token_count > 0
