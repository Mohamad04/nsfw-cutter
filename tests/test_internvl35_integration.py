from __future__ import annotations

import os

import pytest
from PIL import Image

from services.analysis.internvl35_binary_capability import (
    MODEL_REPOSITORY_ID,
    InternVLProvider,
)
from services.analysis.smolvlm_verifier import (
    EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    VLMFrameDescriptor,
    VLMVerificationRequest,
    VLMVerificationRequestMetadata,
)


@pytest.mark.skipif(
    os.environ.get("NSFW_CUTTER_RUN_INTERNVL35_INTEGRATION_TESTS") != "1",
    reason="set NSFW_CUTTER_RUN_INTERNVL35_INTEGRATION_TESTS=1 explicitly",
)
def test_real_internvl35_runtime_4bit_loads() -> None:
    runtime = InternVLProvider(local_files_only=False).runtime()
    assert runtime.provenance.repository_id == MODEL_REPOSITORY_ID
    assert runtime.provenance.quantization.load_in_4bit is True
    assert runtime.provenance.quantization.quantized_linear_modules > 0
    image = Image.new("RGB", (384, 206), (32, 64, 96))
    request = VLMVerificationRequest(
        metadata=VLMVerificationRequestMetadata(
            event_id="integration",
            frames=(VLMFrameDescriptor(frame_index=1, timestamp_us=0),),
            policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY,
        ),
        images=(image,),
    )
    budget = runtime.inspect_output_budget()
    result = runtime.generate_binary(
        request, "weapons", max_new_tokens=budget.configured_max_new_tokens
    )
    image.close()
    assert result.processor_metrics is not None
    assert result.generated_token_count > 0
