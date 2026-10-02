from __future__ import annotations

from services.analysis.smolvlm_quality_evaluation import SilverIntervalReference
from services.analysis.smolvlm_verifier import (
    EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    RawSmolVLMGeneration,
    SmolVLMRuntimeProvenance,
    VLMFrameDescriptor,
    VLMVerificationRequestMetadata,
)
from services.analysis.smolvlm_visual_capability import (
    CATEGORY_IDS,
    BinaryAnswer,
    BinaryAttempt,
    BinaryEventResult,
    BitmaskAttempt,
    BitmaskEventResult,
    build_binary_conversation,
    build_bitmask_conversation,
    full_bitmask_gate,
    inspect_output_token_budget,
    parse_binary_answer,
    parse_six_bit_output,
    phase_b_gate,
    summarize_binary_capability,
    summarize_bitmask_capability,
)
from services.analysis.stage1_evaluation import GroundTruthInterval


def test_strict_binary_parser_accepts_yes_no_case_and_whitespace() -> None:
    assert parse_binary_answer("YES") == BinaryAnswer.YES
    assert parse_binary_answer(" no ") == BinaryAnswer.NO
    assert parse_binary_answer("\nYeS\t") == BinaryAnswer.YES
    assert parse_binary_answer(" Yes. ") == BinaryAnswer.YES
    assert parse_binary_answer("NO.") == BinaryAnswer.NO


def test_strict_binary_parser_rejects_prose_other_punctuation_and_invalid_answer() -> None:
    assert parse_binary_answer("YES because it is visible") == BinaryAnswer.UNVERIFIED
    assert parse_binary_answer("YES!") == BinaryAnswer.UNVERIFIED
    assert parse_binary_answer("YES..") == BinaryAnswer.UNVERIFIED
    assert parse_binary_answer("maybe") == BinaryAnswer.UNVERIFIED


def test_six_bit_parser_enforces_exact_length_and_characters() -> None:
    assert parse_six_bit_output("000010") == (
        False,
        False,
        False,
        False,
        True,
        False,
    )
    assert parse_six_bit_output("00010") is None
    assert parse_six_bit_output("00001x") is None
    assert parse_six_bit_output(" 000010") is None


def test_six_bit_category_position_mapping() -> None:
    attempt = BitmaskAttempt(
        bits=parse_six_bit_output("101011"),
        validation_error=None,
        generation=_generation("101011"),
    )
    assert attempt.detected_categories() == (
        "nudity",
        "violence",
        "weapons",
        "drugs",
    )


def test_prompts_have_no_examples_or_json_and_label_frames() -> None:
    metadata = _metadata()
    conversations = [
        build_binary_conversation(metadata, category) for category in CATEGORY_IDS
    ] + [build_bitmask_conversation(metadata)]
    for conversation in conversations:
        text = " ".join(
            item.get("text", "") for item in conversation[0]["content"]
        )
        assert "Frame 1" in text and "Frame 2" in text
        assert "{" not in text and "}" not in text
        assert "000010" not in text


def test_runtime_tokenization_validates_binary_and_bitmask_budgets() -> None:
    tokenizer = _Tokenizer()
    binary = inspect_output_token_budget(tokenizer, output_kind="binary")
    bitmask = inspect_output_token_budget(tokenizer, output_kind="bitmask")
    assert binary.configured_max_new_tokens == 4
    assert binary.required_max_new_tokens == 3
    assert bitmask.required_max_new_tokens == 3
    assert bitmask.configured_max_new_tokens == 3


def test_binary_recall_aggregation_and_unlabeled_yes_is_not_precision() -> None:
    intervals = (
        GroundTruthInterval(
            start="00:00:01.000", end="00:00:02.000", category="weapons"
        ),
        GroundTruthInterval(
            start="00:00:03.000", end="00:00:04.000", category="drugs"
        ),
    )
    records = (
        _binary_record("labeled", "silver:000", weapons=BinaryAnswer.YES),
        _binary_record("drug", "silver:001", drugs=BinaryAnswer.NO),
        _binary_record("unlabeled", None, nudity=BinaryAnswer.YES),
    )

    summary = summarize_binary_capability(records, intervals)

    assert summary.detected_intervals == 1
    assert summary.category_detected_intervals == 1
    assert summary.category_aware_recall == 0.5
    assert not hasattr(summary, "precision")


def test_bitmask_recall_and_phase_a_disagreement_aggregation() -> None:
    intervals = (
        GroundTruthInterval(
            start="00:00:01.000", end="00:00:02.000", category="weapons"
        ),
    )
    binary = _binary_record("event", "silver:000", weapons=BinaryAnswer.YES)
    bitmask = BitmaskEventResult(
        event_id="event",
        start_timestamp_us=1_000_000,
        end_timestamp_us=2_000_000,
        selected_frame_timestamps_us=(1_500_000,),
        silver_overlaps=(_overlap("silver:000", "weapons"),),
        attempt=BitmaskAttempt(
            bits=parse_six_bit_output("000010"),
            validation_error=None,
            generation=_generation("000010"),
        ),
    )

    summary = summarize_bitmask_capability((bitmask,), intervals, (binary,))

    assert summary.known_unsafe_recall == 1.0
    assert summary.category_aware_recall == 1.0
    assert summary.phase_a_comparable_answers == 6
    assert summary.phase_a_disagreements == 0


def test_phase_b_is_gated_on_nonzero_category_aware_detection() -> None:
    missed = summarize_binary_capability(
        (_binary_record("event", "silver:000"),),
        (
            GroundTruthInterval(
                start="00:00:01.000", end="00:00:02.000", category="weapons"
            ),
        ),
    )
    detected = summarize_binary_capability(
        (_binary_record("event", "silver:000", weapons=BinaryAnswer.YES),),
        (
            GroundTruthInterval(
                start="00:00:01.000", end="00:00:02.000", category="weapons"
            ),
        ),
    )
    assert phase_b_gate(missed).should_run is False
    assert phase_b_gate(detected).should_run is True


def test_full_bitmask_gate_requires_validity_and_phase_a_retention() -> None:
    interval = GroundTruthInterval(
        start="00:00:01.000", end="00:00:02.000", category="weapons"
    )
    binary_record = _binary_record("event", "silver:000", weapons=BinaryAnswer.YES)
    phase_a = summarize_binary_capability((binary_record,), (interval,))
    bitmask_record = BitmaskEventResult(
        event_id="event",
        start_timestamp_us=1_000_000,
        end_timestamp_us=2_000_000,
        selected_frame_timestamps_us=(1_500_000,),
        silver_overlaps=(_overlap("silver:000", "weapons"),),
        attempt=BitmaskAttempt(
            bits=parse_six_bit_output("000010"),
            validation_error=None,
            generation=_generation("000010"),
        ),
    )
    phase_b = summarize_bitmask_capability(
        (bitmask_record,),
        (interval,),
        (binary_record,),
    )
    assert full_bitmask_gate(phase_b, phase_a).should_run is True


def _binary_record(
    event_id: str,
    interval_id: str | None,
    **answers: BinaryAnswer,
) -> BinaryEventResult:
    attempts = tuple(
        BinaryAttempt(
            category=category,
            answer=answers.get(category, BinaryAnswer.NO),
            validation_error=None,
            generation=_generation(answers.get(category, BinaryAnswer.NO).value.upper()),
        )
        for category in CATEGORY_IDS
    )
    overlaps = (
        (_overlap(interval_id, "weapons" if interval_id == "silver:000" else "drugs"),)
        if interval_id
        else ()
    )
    return BinaryEventResult(
        event_id=event_id,
        start_timestamp_us=1_000_000,
        end_timestamp_us=2_000_000,
        selected_frame_timestamps_us=(1_500_000,),
        selected_frame_paths=("cached.png",),
        silver_overlaps=overlaps,
        answers=attempts,
    )


def _overlap(interval_id: str, category: str) -> SilverIntervalReference:
    return SilverIntervalReference(
        interval_id=interval_id,
        start="00:00:01.000",
        end="00:00:02.000",
        start_us=1_000_000,
        end_us=2_000_000,
        category=category,
        severity="medium",
        exact_overlap=True,
        tolerant_overlap_5s=True,
    )


def _metadata() -> VLMVerificationRequestMetadata:
    return VLMVerificationRequestMetadata(
        event_id="event",
        frames=(
            VLMFrameDescriptor(frame_index=1, timestamp_us=1),
            VLMFrameDescriptor(frame_index=2, timestamp_us=2),
        ),
        policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    )


def _generation(raw: str) -> RawSmolVLMGeneration:
    return RawSmolVLMGeneration(
        event_id="event",
        raw_generated_text=raw,
        error=None,
        truncated=False,
        generated_token_count=1,
        chat_template_seconds=0.01,
        processor_seconds=0.02,
        generation_seconds=0.03,
        decode_seconds=0.01,
        total_seconds=0.07,
        tokens_per_second=1.0,
        expansion=None,
        provenance=_provenance(),
    )


def _provenance() -> SmolVLMRuntimeProvenance:
    return SmolVLMRuntimeProvenance(
        repository_id="test/model",
        revision="a" * 40,
        checkpoint_sha256="b" * 64,
        model_class="SmolVLMForConditionalGeneration",
        processor_class="SmolVLMProcessor",
        parameter_count=1,
        model_dtype="float32",
        device="cuda",
        transformers_version="test",
        torch_version="test",
        attention_implementation="sdpa",
    )


class _Tokenizer:
    eos_token_id = 2

    def __call__(self, value: str, *, add_special_tokens: bool) -> dict[str, list[int]]:
        assert add_special_tokens is False
        return {"input_ids": [1] if len(value) <= 3 else [1, 2]}
