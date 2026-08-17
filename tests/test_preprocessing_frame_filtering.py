import unittest

from PIL import Image, ImageDraw

from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.frame_filtering import SequentialFrameFilter
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    PreprocessingConfig,
    SampleReason,
)


class SequentialFrameFilterTests(unittest.TestCase):
    def setUp(self):
        self.config = PreprocessingConfig(
            target_width=32,
            target_height=32,
            static_suppression_limit_seconds=3.0,
        )
        self.filter = SequentialFrameFilter(self.config)

    def test_pure_black_frame_is_removed(self):
        decision = self.filter.process(_solid_frame("black"), owning_chunk_index=0)

        self.assertEqual(decision.disposition, FrameDisposition.BLACK)
        self.assertEqual(decision.black_fraction, 1.0)

    def test_dark_but_visible_frame_is_retained(self):
        image = Image.new("RGB", (32, 32), (5, 5, 5))
        ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill=(35, 35, 35))

        decision = self.filter.process(_frame(image), owning_chunk_index=0)

        self.assertEqual(decision.disposition, FrameDisposition.REPRESENTATIVE)

    def test_black_padding_is_not_treated_as_source_blackness(self):
        image = Image.new("RGB", (32, 32), "black")
        ImageDraw.Draw(image).rectangle((0, 8, 31, 23), fill="white")
        frame = _frame(image, content_rect=(0, 8, 32, 16))

        decision = self.filter.process(frame, owning_chunk_index=0)

        self.assertEqual(decision.disposition, FrameDisposition.REPRESENTATIVE)

    def test_duplicate_frames_collapse_but_first_is_retained(self):
        first = self.filter.process(_solid_frame("red", timestamp_us=0), 0)
        second = self.filter.process(_solid_frame("red", timestamp_us=1_000_000), 0)

        self.assertEqual(first.disposition, FrameDisposition.REPRESENTATIVE)
        self.assertEqual(second.disposition, FrameDisposition.STATIC_SUPPRESSED)
        self.assertEqual(second.duplicate_of_timestamp_us, first.timestamp_us)

    def test_changed_frame_is_retained(self):
        first_image = Image.new("RGB", (32, 32), "red")
        second_image = Image.new("RGB", (32, 32), "blue")

        self.filter.process(_frame(first_image, timestamp_us=0), 0)
        changed = self.filter.process(_frame(second_image, timestamp_us=1_000_000), 0)

        self.assertEqual(changed.disposition, FrameDisposition.REPRESENTATIVE)

    def test_long_static_run_obeys_maximum_suppression_span(self):
        decisions = [
            self.filter.process(_solid_frame("red", timestamp_us=second * 1_000_000), 0)
            for second in range(7)
        ]

        retained_times = [
            decision.timestamp_us
            for decision in decisions
            if decision.disposition is FrameDisposition.REPRESENTATIVE
        ]
        self.assertEqual(retained_times, [0, 3_000_000, 6_000_000])

    def test_scene_boundary_prevents_unsafe_static_collapse(self):
        self.filter.process(_solid_frame("red", timestamp_us=0), 0)
        boundary = self.filter.process(
            _solid_frame(
                "red",
                timestamp_us=1_000_000,
                reasons=frozenset({SampleReason.SCENE_TRANSITION}),
            ),
            0,
        )

        self.assertEqual(boundary.disposition, FrameDisposition.REPRESENTATIVE)

    def test_persistent_logo_does_not_hide_underlying_change(self):
        before = Image.new("RGB", (32, 32), "navy")
        after = Image.new("RGB", (32, 32), "orange")
        for image in (before, after):
            ImageDraw.Draw(image).rectangle((0, 0, 7, 7), fill="white")

        self.filter.process(_frame(before, timestamp_us=0), 0)
        changed = self.filter.process(_frame(after, timestamp_us=1_000_000), 0)

        self.assertEqual(changed.disposition, FrameDisposition.REPRESENTATIVE)

    def test_visually_equal_overlap_samples_collapse(self):
        self.filter.process(_solid_frame("red", timestamp_us=3_999_999, chunk_index=0), 0)
        duplicate = self.filter.process(
            _solid_frame("red", timestamp_us=4_000_000, chunk_index=1),
            1,
        )

        self.assertEqual(duplicate.disposition, FrameDisposition.NEAR_DUPLICATE)

    def test_duplicate_scene_detection_in_overlap_still_collapses(self):
        self.filter.process(
            _solid_frame(
                "red",
                timestamp_us=3_999_999,
                chunk_index=0,
                reasons=frozenset({SampleReason.SCENE_TRANSITION}),
            ),
            0,
        )
        duplicate = self.filter.process(
            _solid_frame(
                "red",
                timestamp_us=4_000_000,
                chunk_index=1,
                reasons=frozenset({SampleReason.SCENE_TRANSITION}),
            ),
            1,
        )

        self.assertEqual(duplicate.disposition, FrameDisposition.NEAR_DUPLICATE)

    def test_close_but_visually_different_overlap_samples_are_retained(self):
        self.filter.process(_solid_frame("red", timestamp_us=3_999_999, chunk_index=0), 0)
        changed = self.filter.process(
            _solid_frame("blue", timestamp_us=4_000_000, chunk_index=1),
            1,
        )

        self.assertEqual(changed.disposition, FrameDisposition.REPRESENTATIVE)


def _solid_frame(
    color: str,
    *,
    timestamp_us: int = 0,
    chunk_index: int = 0,
    reasons: frozenset[SampleReason] = frozenset({SampleReason.TEMPORAL_SAFETY}),
) -> ExtractedFrame:
    return _frame(
        Image.new("RGB", (32, 32), color),
        timestamp_us=timestamp_us,
        chunk_index=chunk_index,
        reasons=reasons,
    )


def _frame(
    image: Image.Image,
    *,
    timestamp_us: int = 0,
    chunk_index: int = 0,
    reasons: frozenset[SampleReason] = frozenset({SampleReason.TEMPORAL_SAFETY}),
    content_rect: tuple[int, int, int, int] = (0, 0, 32, 32),
) -> ExtractedFrame:
    return ExtractedFrame(
        timestamp_us=timestamp_us,
        source_pts=timestamp_us,
        source_time_base="1/1000000",
        processing_chunk_index=chunk_index,
        sample_reasons=reasons,
        width=image.width,
        height=image.height,
        content_rect=content_rect,
        scene_score=None,
        rgb_bytes=image.tobytes(),
    )


if __name__ == "__main__":
    unittest.main()
