import json
import os
import string
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from services.analysis.cache import AnalysisCache
from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import (
    AnalysisSettings,
    ProviderDiagnostics,
    SampledFrame,
    VisualBatch,
    VLMWireResponse,
)
from services.analysis.providers.base import VLMStructuredOutputError
from services.analysis.providers.qwen import (
    LocalQwenVLProvider,
    _build_lmfe_tokenizer_data,
    _build_schema_prefix_allowed_tokens_fn,
    _generation_stopping_criteria,
    _messages_for_batch,
    _GenerationAttempt,
    _validate_wire_output,
    _wire_response_to_review,
    _wire_schema_for_batch,
)
from services.analysis.visual_sampling import _build_batches


def _batch(*, contact_sheet: bool = False) -> VisualBatch:
    return VisualBatch(
        batch_id="batch-1",
        start_seconds=9.5,
        end_seconds=12.5,
        frames=[
            SampledFrame(
                timestamp_seconds=10.0,
                path=Path("frame-1.jpg"),
                source="interval",
            ),
            SampledFrame(
                timestamp_seconds=12.0,
                path=Path("frame-2.jpg"),
                source="interval",
            ),
        ],
        contact_sheet_path=Path("contact-sheet.jpg") if contact_sheet else None,
    )


def _wire_payload(**changes) -> dict:
    item = {
        "category": "nudity",
        "confidence": 0.91,
        "first_frame": 1,
        "last_frame": 2,
        "evidence_frames": [1, 2],
        "reason": "brief visual evidence",
    }
    item.update(changes)
    return {"suggestions": [item]}


def _three_batches():
    # No files are opened: omit contact_sheet_dir to exercise production batching.
    frames = [SampledFrame(timestamp_seconds=float(t), path=Path(f"synthetic-{t}.jpg"),
                           source="refined") for t in range(20)]
    return _build_batches(frames, 8, 22.4)


def _filter_accepts(tokenizer, tokenizer_data, schema, payload):
    allowed = _build_schema_prefix_allowed_tokens_fn(
        tokenizer_data, schema, initial_prompt_length=3)
    sequence = [-1, -2, -3]  # Prompt tokens must be excluded from JSON filtering.
    target = json.dumps(payload, separators=(",", ":"))
    for token in tokenizer.encode(target, add_special_tokens=False):
        if token not in allowed(0, sequence):
            return False
        sequence.append(token)
    return tokenizer.eos_token_id in allowed(0, sequence)


@pytest.fixture(scope="module", params=["character", "local_qwen"])
def constrained_tokenizer(request):
    if request.param == "character":
        tokenizer = _CharacterTokenizer()
    else:
        snapshot = os.environ.get("NSFW_CUTTER_TEST_QWEN_TOKENIZER")
        if not snapshot:
            pytest.skip("Set NSFW_CUTTER_TEST_QWEN_TOKENIZER to a local pinned Qwen snapshot")
        path = Path(snapshot)
        assert path.is_dir(), "Explicit tokenizer snapshot must exist; never download"
        from transformers import AutoTokenizer
        # Only tokenizer files: no processor, model weights, network or generation.
        tokenizer = AutoTokenizer.from_pretrained(
            str(path.resolve()), local_files_only=True, trust_remote_code=False)
    return tokenizer, _build_lmfe_tokenizer_data(tokenizer)


@pytest.mark.parametrize("batch_index", [0, 1, 2])
def test_local_indices_restart_and_map_to_each_batch(batch_index):
    batches = _three_batches()
    assert [len(b.frames) for b in batches] == [8, 8, 4]
    batch = batches[batch_index]
    count = len(batch.frames)
    schema = _wire_schema_for_batch(batch)
    properties = schema["$defs"]["VLMWireSuggestion"]["properties"]
    for field in (properties["first_frame"], properties["last_frame"],
                  properties["evidence_frames"]["items"]):
        assert field["enum"] == list(range(1, count + 1))
    prompt = _messages_for_batch(batch)[0]["content"][-1]["text"]
    for index, frame in enumerate(batch.frames, 1):
        assert f"frame {index}={frame.timestamp_seconds:.3f}s" in prompt
    wire = _validate_wire_output(json.dumps(_wire_payload(
        last_frame=count, evidence_frames=list(range(1, count + 1)))), batch)
    item = _wire_response_to_review(wire, batch).suggestions[0]
    assert item.evidence_timestamps == [f.timestamp_seconds for f in batch.frames]
    assert (item.start_seconds, item.end_seconds) == (batch.start_seconds, batch.end_seconds)


@pytest.mark.parametrize("batch_index", [0, 1, 2])
def test_real_filter_accepts_every_local_index_and_empty(constrained_tokenizer, batch_index):
    tokenizer, data = constrained_tokenizer
    batch = _three_batches()[batch_index]
    schema = _wire_schema_for_batch(batch)
    for index in range(1, len(batch.frames) + 1):
        payload = _wire_payload(first_frame=index, last_frame=index, evidence_frames=[index])
        assert _filter_accepts(tokenizer, data, schema, payload)
        _validate_wire_output(json.dumps(payload), batch)
    assert _filter_accepts(tokenizer, data, schema, {"suggestions": []})
    assert not _validate_wire_output('{"suggestions":[]}', batch).suggestions


@pytest.mark.parametrize("field", ["first_frame", "last_frame", "evidence_frames"])
@pytest.mark.parametrize("invalid", [0, 5, 8, 16, 19])
def test_real_filter_and_validator_reject_invalid_local_indices(constrained_tokenizer, field, invalid):
    tokenizer, data = constrained_tokenizer
    batch = _three_batches()[2]
    payload = _wire_payload(last_frame=4, evidence_frames=[1, 4])
    payload["suggestions"][0][field] = [invalid] if field == "evidence_frames" else invalid
    assert not _filter_accepts(tokenizer, data, _wire_schema_for_batch(batch), payload)
    with pytest.raises(VLMStructuredOutputError):
        _validate_wire_output(json.dumps(payload), batch)


def test_schema_revision_invalidates_record_and_batch_cache_keys():
    current = AnalysisSettings()
    old = AnalysisSettings(prompt_schema_revision=2)
    assert current.prompt_schema_revision == 3
    assert {k: v for k, v in current.model_dump().items() if k != "prompt_schema_revision"} == {
        k: v for k, v in old.model_dump().items() if k != "prompt_schema_revision"}
    old_key = AnalysisCache.make_key("sha256:synthetic", old)
    new_key = AnalysisCache.make_key("sha256:synthetic", current)
    assert old_key != new_key
    batch = _three_batches()[2]
    assert AnalysisCache.make_batch_key(old_key, batch, old, prompt_schema_version="2") != (
        AnalysisCache.make_batch_key(new_key, batch, current, prompt_schema_version="3"))


@pytest.mark.parametrize("repair_valid", [True, False])
def test_initial_and_repair_share_enum_constraints_and_keep_errors(constrained_tokenizer, repair_valid):
    tokenizer, data = constrained_tokenizer
    batch = _three_batches()[2]
    invalid = _wire_payload(first_frame=16, last_frame=19, evidence_frames=[16, 19])
    valid = _wire_payload(first_frame=1, last_frame=4, evidence_frames=[1, 4])
    raw_output = json.dumps(invalid)
    repaired_output = json.dumps(valid if repair_valid else invalid)
    provider = LocalQwenVLProvider(model_cache_dir=Path("unused-model-cache"))
    # Mock only model execution and input preparation; run production review,
    # schema construction, repair dispatch, validation and conversion unchanged.
    with (
        patch.object(provider, "_ensure_loaded"),
        patch.object(provider, "_prepare_visual_inputs", return_value=object()),
        patch.object(provider, "_prepare_repair_inputs", return_value=object()) as prepare_repair,
        patch.object(provider, "_generate", side_effect=[
            _GenerationAttempt(raw_output, 1, "completed"),
            _GenerationAttempt(repaired_output, 1, "completed"),
        ]) as generate,
    ):
        if repair_valid:
            result = provider.review_batch(batch, AnalysisSettings(), CancellationToken())
            assert result.repaired
            assert result.response.suggestions[0].evidence_timestamps == [16.0, 19.0]
        else:
            with pytest.raises(VLMStructuredOutputError) as error:
                provider.review_batch(batch, AnalysisSettings(), CancellationToken())
            assert error.value.raw_output == raw_output
            assert error.value.repaired_output == repaired_output
            assert isinstance(error.value.__cause__, VLMStructuredOutputError)
        prepare_repair.assert_called_once_with(raw_output)
        assert generate.call_count == 2
        initial_schema = generate.call_args_list[0].kwargs["wire_schema"]
        repair_schema = generate.call_args_list[1].kwargs["wire_schema"]
        assert initial_schema is repair_schema
        for schema in (initial_schema, repair_schema):
            assert not _filter_accepts(tokenizer, data, schema, invalid)
            assert _filter_accepts(tokenizer, data, schema, valid)
            assert _filter_accepts(tokenizer, data, schema, {"suggestions": []})


class _CharacterTokenizer:
    """Small deterministic tokenizer sufficient to exercise LMFE prefix filtering."""

    def __init__(self):
        alphabet = string.printable
        self._characters = list(dict.fromkeys(alphabet))
        self._ids = {character: index for index, character in enumerate(self._characters)}
        self.eos_token_id = len(self._characters)
        self.pad_token_id = self.eos_token_id
        self.unk_token_id = -1
        self.all_special_ids = [self.eos_token_id]

    def __len__(self):
        return len(self._characters) + 1

    def encode(self, value, add_special_tokens=False):
        del add_special_tokens
        return [self._ids[character] for character in value]

    def decode(self, token_ids):
        return "".join(
            self._characters[token_id]
            for token_id in token_ids
            if 0 <= token_id < len(self._characters)
        )

    def convert_tokens_to_ids(self, _value):
        return self.unk_token_id


class _FakeInputs(dict):
    def __init__(self):
        super().__init__(input_ids=[[10, 11]])
        self.input_ids = self["input_ids"]
        self.to_calls = []

    def to(self, device):
        self.to_calls.append(device)
        return self


class _FakeProcessor:
    def __init__(self, decoded_outputs):
        self.tokenizer = _CharacterTokenizer()
        self.decoded_outputs = list(decoded_outputs)
        self.call_kwargs = []
        self.messages = []

    def apply_chat_template(self, messages, **_kwargs):
        self.messages.append(messages)
        return "prompt"

    def __call__(self, **kwargs):
        self.call_kwargs.append(kwargs)
        return _FakeInputs()

    def batch_decode(self, *_args, **_kwargs):
        return [self.decoded_outputs.pop(0)]


class _FakeGenerationModel:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return [kwargs["input_ids"][0] + [20]]


class StructuredOutputTests(unittest.TestCase):
    def test_wire_response_is_strict_and_references_only_batch_frames(self):
        response = _validate_wire_output(json.dumps(_wire_payload()), _batch())
        self.assertEqual(response.suggestions[0].evidence_frames, [1, 2])

        with self.assertRaises(VLMStructuredOutputError) as missing_outer:
            _validate_wire_output("{}", _batch())
        with self.assertRaises(VLMStructuredOutputError):
            _validate_wire_output(
                json.dumps(_wire_payload(last_frame=3, evidence_frames=[3])),
                _batch(),
            )
        self.assertEqual(missing_outer.exception.raw_output, "{}")
        self.assertNotIn("{}", str(missing_outer.exception))

    def test_wire_response_converts_frame_indices_to_bounded_timestamps(self):
        wire_response = VLMWireResponse.model_validate(_wire_payload())
        response = _wire_response_to_review(wire_response, _batch())

        item = response.suggestions[0]
        self.assertEqual(item.start_seconds, 9.5)
        self.assertEqual(item.end_seconds, 12.5)
        self.assertEqual(item.evidence_timestamps, [10.0, 12.0])
        self.assertTrue(item.needs_review)

    def test_generation_schema_is_narrowed_to_the_actual_batch_frame_count(self):
        schema = _wire_schema_for_batch(_batch())
        properties = schema["$defs"]["VLMWireSuggestion"]["properties"]

        self.assertEqual(properties["first_frame"]["maximum"], 2)
        self.assertEqual(properties["last_frame"]["maximum"], 2)
        self.assertEqual(properties["evidence_frames"]["items"]["maximum"], 2)

    def test_contact_sheet_is_one_visual_input_with_numbered_frame_mapping(self):
        messages = _messages_for_batch(_batch(contact_sheet=True))
        content = messages[0]["content"]
        images = [item for item in content if item["type"] == "image"]
        prompt = next(item["text"] for item in content if item["type"] == "text")

        self.assertEqual(images, [{"type": "image", "image": "contact-sheet.jpg"}])
        self.assertIn("numbered panels", prompt)
        self.assertIn("frame 1=10.000s", prompt)
        self.assertIn("frame 2=12.000s", prompt)

    def test_lmfe_constraint_accepts_compact_schema_and_only_then_eos(self):
        tokenizer = _CharacterTokenizer()
        tokenizer_data = _build_lmfe_tokenizer_data(tokenizer)
        allowed_tokens_fn = _build_schema_prefix_allowed_tokens_fn(
            tokenizer_data,
            VLMWireResponse.model_json_schema(),
            initial_prompt_length=3,
        )
        target = json.dumps({"suggestions": []}, separators=(",", ":"))
        # These deliberately invalid/non-token prompt IDs must never be interpreted
        # as generated JSON by the format enforcer.
        sequence = [999, 998, 997]

        first_allowed = allowed_tokens_fn(0, sequence)
        self.assertIn(tokenizer.encode("{")[0], first_allowed)
        self.assertNotIn(tokenizer.encode("x")[0], first_allowed)
        for token_id in tokenizer.encode(target):
            self.assertIn(token_id, allowed_tokens_fn(0, sequence))
            sequence.append(token_id)

        self.assertIn(tokenizer.eos_token_id, allowed_tokens_fn(0, sequence))

    def test_deadline_and_cancellation_are_both_generation_stop_conditions(self):
        cancellation = CancellationToken()
        criteria, deadline = _generation_stopping_criteria(cancellation, 0.0)

        self.assertTrue(criteria[1](None, None))
        self.assertTrue(deadline.expired)
        cancellation.cancel()
        self.assertTrue(criteria[0](None, None))

    def test_invalid_visual_output_gets_one_text_only_constrained_repair(self):
        raw_output = '{"suggestions":['
        repaired_output = json.dumps(_wire_payload())
        processor = _FakeProcessor([raw_output, repaired_output])
        model = _FakeGenerationModel()
        provider = LocalQwenVLProvider(model_cache_dir=Path("model-cache"))
        provider._processor = processor
        provider._model = model
        provider._device = "cpu"
        provider._tokenizer_data = object()
        provider.diagnostics = ProviderDiagnostics(device_mode="cpu")
        settings = AnalysisSettings(max_new_tokens=384, repair_max_new_tokens=192)

        with (
            patch.object(provider, "_ensure_loaded"),
            patch(
                "qwen_vl_utils.process_vision_info",
                return_value=(["visual-input"], None),
            ) as process_vision_info,
            patch(
                "services.analysis.providers.qwen._build_schema_prefix_allowed_tokens_fn",
                return_value=lambda _batch_id, _tokens: [1],
            ),
        ):
            result = provider.review_batch(_batch(), settings, CancellationToken())

        self.assertTrue(result.repaired)
        self.assertEqual(result.raw_output, raw_output)
        self.assertEqual(result.repaired_output, repaired_output)
        self.assertEqual(len(result.response.suggestions), 1)
        self.assertEqual(process_vision_info.call_count, 1)
        self.assertIn("images", processor.call_kwargs[0])
        self.assertNotIn("images", processor.call_kwargs[1])
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(model.calls[0]["max_new_tokens"], 192)
        self.assertEqual(model.calls[1]["max_new_tokens"], 128)
        self.assertIn("prefix_allowed_tokens_fn", model.calls[0])


if __name__ == "__main__":
    unittest.main()
