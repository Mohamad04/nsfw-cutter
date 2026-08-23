import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from services.analysis.contracts import (
    NSFWCategory,
    SampledFrame,
    VisualBatch,
    VLMReviewResponse,
)
from services.analysis.providers.base import VLMProviderError
from services.analysis.providers.qwen import _validate_batch_bounds, _validate_output
from services.analysis.visual_sampling import _build_batches


class VLMReviewResponseTests(unittest.TestCase):
    def setUp(self):
        self.valid_item = {
            "category": "nudity",
            "confidence": 0.91,
            "start_seconds": 10.0,
            "end_seconds": 12.0,
            "evidence_timestamps": [11.5, 10.5, 10.5],
            "reason": "Brief visual evidence",
            "needs_review": True,
        }

    def test_valid_json_is_accepted_and_evidence_timestamps_are_normalized(self):
        response = VLMReviewResponse.model_validate_json(
            json.dumps({"suggestions": [self.valid_item]})
        )

        self.assertEqual(len(response.suggestions), 1)
        suggestion = response.suggestions[0]
        self.assertEqual(suggestion.category, NSFWCategory.NUDITY)
        self.assertEqual(suggestion.evidence_timestamps, [10.5, 11.5])

    def test_contract_rejects_unknown_fields_at_each_level(self):
        response_payload = {"suggestions": [self.valid_item], "raw_output": "hidden"}
        item_payload = copy.deepcopy(self.valid_item)
        item_payload["raw_frame"] = "frame bytes"

        with self.assertRaises(ValidationError):
            VLMReviewResponse.model_validate_json(json.dumps(response_payload))
        with self.assertRaises(ValidationError):
            VLMReviewResponse.model_validate_json(
                json.dumps({"suggestions": [item_payload]})
            )

    def test_contract_rejects_coercion_missing_fields_and_unknown_categories(self):
        invalid_changes = (
            {"confidence": "0.91"},
            {"needs_review": 1},
            {"needs_review": False},
            {"category": "graphic_content"},
            {"reason": "   "},
        )

        for changes in invalid_changes:
            with self.subTest(changes=changes):
                item = {**self.valid_item, **changes}
                with self.assertRaises(ValidationError):
                    VLMReviewResponse.model_validate_json(
                        json.dumps({"suggestions": [item]})
                    )

        missing_field = copy.deepcopy(self.valid_item)
        del missing_field["needs_review"]
        with self.assertRaises(ValidationError):
            VLMReviewResponse.model_validate_json(
                json.dumps({"suggestions": [missing_field]})
            )

    def test_contract_rejects_invalid_intervals_and_evidence_outside_them(self):
        invalid_changes = (
            {"start_seconds": 12.0, "end_seconds": 12.0},
            {"evidence_timestamps": [8.0]},
            {"evidence_timestamps": [float("nan")]},
            {"confidence": 1.01},
        )

        for changes in invalid_changes:
            with self.subTest(changes=changes):
                item = {**self.valid_item, **changes}
                with self.assertRaises(ValidationError):
                    VLMReviewResponse.model_validate_json(
                        json.dumps({"suggestions": [item]})
                    )

    def test_provider_extracts_json_and_rejects_values_outside_exact_batch(self):
        response = _validate_output(
            "model preamble\n```json\n"
            + json.dumps({"suggestions": [self.valid_item]})
            + "\n```"
        )
        batch = VisualBatch(
            batch_id="batch-1",
            start_seconds=9.5,
            end_seconds=12.0,
            frames=[
                SampledFrame(
                    timestamp_seconds=10.0,
                    path=Path("frame.jpg"),
                    source="interval",
                )
            ],
        )

        _validate_batch_bounds(response, batch)

        outside_item = {**self.valid_item, "evidence_timestamps": [12.25]}
        outside_response = VLMReviewResponse.model_validate(
            {"suggestions": [outside_item]}
        )
        with self.assertRaisesRegex(VLMProviderError, "outside"):
            _validate_batch_bounds(outside_response, batch)

    def test_single_frame_batch_has_a_nonzero_media_window(self):
        batches = _build_batches(
            [
                SampledFrame(
                    timestamp_seconds=0.0,
                    path=Path("frame.jpg"),
                    source="interval",
                )
            ],
            batch_size=8,
            duration_seconds=0.3,
        )

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].start_seconds, 0.0)
        self.assertEqual(batches[0].end_seconds, 0.3)


if __name__ == "__main__":
    unittest.main()
