import json
import string
import unittest
from pathlib import Path
from unittest.mock import patch

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
    _validate_wire_output,
    _wire_response_to_review,
    _wire_schema_for_batch,
)


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
