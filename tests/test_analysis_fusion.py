import unittest

from services.analysis.contracts import (
    AnalysisSettings,
    NSFWCategory,
    TextEvidence,
    VisualEvidence,
)
from services.analysis.fusion import fuse_evidence, merge_time_ranges


class AnalysisIntervalTests(unittest.TestCase):
    def test_context_padding_clips_to_video_bounds(self):
        ranges = merge_time_ranges(
            [(0.2, 1.0), (8.75, 9.8)],
            merge_gap_seconds=0.0,
            context_padding_seconds=0.5,
            duration_seconds=10.0,
        )

        self.assertEqual(ranges, [(0.0, 1.5), (8.25, 10.0)])

    def test_padded_ranges_merge_when_the_remaining_gap_is_within_threshold(self):
        ranges = merge_time_ranges(
            [(1.0, 2.0), (3.2, 4.0), (8.0, 9.0)],
            merge_gap_seconds=0.75,
            context_padding_seconds=0.25,
            duration_seconds=10.0,
        )

        self.assertEqual(ranges, [(0.75, 4.25), (7.75, 9.25)])


class EvidenceFusionTests(unittest.TestCase):
    def setUp(self):
        self.settings = AnalysisSettings(
            use_gpu=False,
            visual_confidence_threshold=0.55,
            text_confidence_threshold=0.35,
            merge_gap_seconds=0.0,
            context_padding_seconds=0.0,
        )

    def test_text_evidence_cannot_create_a_suggestion_without_visual_evidence(self):
        text = TextEvidence(
            start_seconds=10.0,
            end_seconds=12.0,
            category=NSFWCategory.SEXUAL_ACTIVITY,
            confidence=0.99,
            excerpt="supporting dialogue",
            source="subtitle",
        )

        suggestions = fuse_evidence(
            [],
            [text],
            self.settings,
            duration_seconds=30.0,
            video_fingerprint="sha256:text-only",
        )

        self.assertEqual(suggestions, [])

    def test_text_does_not_rescue_visual_evidence_below_the_visual_threshold(self):
        visual = self._visual(confidence=0.54)
        text = self._text(confidence=1.0)

        suggestions = fuse_evidence(
            [visual],
            [text],
            self.settings,
            duration_seconds=30.0,
            video_fingerprint="sha256:below-threshold",
        )

        self.assertEqual(suggestions, [])

    def test_matching_text_only_provides_a_small_boost_to_the_visual_result(self):
        visual = self._visual(confidence=0.9, category=NSFWCategory.NUDITY)
        text = self._text(
            confidence=0.99,
            category=NSFWCategory.SEXUAL_ACTIVITY,
        )

        without_text = fuse_evidence(
            [visual],
            [],
            self.settings,
            duration_seconds=30.0,
            video_fingerprint="sha256:visual-primary",
        )[0]
        with_text = fuse_evidence(
            [visual],
            [text],
            self.settings,
            duration_seconds=30.0,
            video_fingerprint="sha256:visual-primary",
        )[0]

        self.assertEqual(with_text.category, NSFWCategory.NUDITY)
        self.assertEqual(with_text.visual_confidence, 0.9)
        self.assertEqual(with_text.text_confidence, 0.99)
        self.assertGreater(with_text.final_confidence, without_text.final_confidence)
        self.assertLess(with_text.final_confidence, 0.93)
        self.assertTrue(with_text.needs_review)

    def test_nearby_visual_candidates_merge_with_strongest_category_and_stable_id(self):
        settings = self.settings.model_copy(
            update={"merge_gap_seconds": 0.5, "context_padding_seconds": 0.25}
        )
        visual_items = [
            VisualEvidence(
                batch_id="batch-1",
                category=NSFWCategory.NUDITY,
                confidence=0.7,
                start_seconds=10.0,
                end_seconds=11.0,
                evidence_timestamps=[10.5],
                reason="First visual interval",
            ),
            VisualEvidence(
                batch_id="batch-2",
                category=NSFWCategory.SEXUAL_ACTIVITY,
                confidence=0.9,
                start_seconds=12.0,
                end_seconds=14.0,
                evidence_timestamps=[12.5, 13.5],
                reason="Stronger visual interval",
            ),
        ]

        first = fuse_evidence(
            visual_items,
            [],
            settings,
            duration_seconds=30.0,
            video_fingerprint="sha256:merged",
        )
        second = fuse_evidence(
            visual_items,
            [],
            settings,
            duration_seconds=30.0,
            video_fingerprint="sha256:merged",
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].start_seconds, 9.75)
        self.assertEqual(first[0].end_seconds, 14.25)
        self.assertEqual(first[0].category, NSFWCategory.SEXUAL_ACTIVITY)
        self.assertEqual(first[0].evidence_timestamps, [10.5, 12.5, 13.5])
        self.assertEqual(first[0].id, second[0].id)

    @staticmethod
    def _visual(
        *,
        confidence: float,
        category: NSFWCategory = NSFWCategory.NUDITY,
    ) -> VisualEvidence:
        return VisualEvidence(
            batch_id="batch-1",
            category=category,
            confidence=confidence,
            start_seconds=10.0,
            end_seconds=12.0,
            evidence_timestamps=[10.5, 11.5],
            reason="Visual evidence requiring review",
        )

    @staticmethod
    def _text(
        *,
        confidence: float,
        category: NSFWCategory = NSFWCategory.SEXUAL_ACTIVITY,
    ) -> TextEvidence:
        return TextEvidence(
            start_seconds=10.25,
            end_seconds=11.75,
            category=category,
            confidence=confidence,
            excerpt="supporting dialogue",
            source="subtitle",
        )


if __name__ == "__main__":
    unittest.main()
