import unittest

from services.analysis.chunking import owning_chunk_index, plan_processing_chunks
from services.analysis.preprocessing_contracts import PreprocessingConfig


SECOND = 1_000_000


class ProcessingChunkPlannerTests(unittest.TestCase):
    def setUp(self):
        self.config = PreprocessingConfig(
            chunk_duration_seconds=4.0,
            chunk_overlap_seconds=0.5,
        )

    def test_short_video_produces_one_clamped_chunk(self):
        chunks = plan_processing_chunks(2 * SECOND, self.config)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].core_start_us, 0)
        self.assertEqual(chunks[0].core_end_us, 2 * SECOND)
        self.assertEqual(chunks[0].decode_start_us, 0)
        self.assertEqual(chunks[0].decode_end_us, 2 * SECOND)

    def test_exact_boundary_has_no_empty_final_chunk(self):
        chunks = plan_processing_chunks(8 * SECOND, self.config)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[-1].core_end_us, 8 * SECOND)

    def test_multiple_chunks_have_gap_free_non_overlapping_cores(self):
        chunks = plan_processing_chunks(12 * SECOND, self.config)

        self.assertEqual(len(chunks), 3)
        for left, right in zip(chunks[:-1], chunks[1:], strict=True):
            self.assertEqual(left.core_end_us, right.core_start_us)

    def test_final_partial_chunk_is_clamped(self):
        chunks = plan_processing_chunks(9_250_000, self.config)

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[-1].core_start_us, 8 * SECOND)
        self.assertEqual(chunks[-1].core_end_us, 9_250_000)
        self.assertEqual(chunks[-1].decode_end_us, 9_250_000)

    def test_decode_overlap_is_symmetric_and_clamped(self):
        chunks = plan_processing_chunks(10 * SECOND, self.config)

        self.assertEqual(chunks[0].decode_start_us, 0)
        self.assertEqual(chunks[0].decode_end_us, 4_250_000)
        self.assertEqual(chunks[1].decode_start_us, 3_750_000)
        self.assertEqual(chunks[1].decode_end_us, 8_250_000)
        self.assertEqual(chunks[-1].decode_start_us, 7_750_000)
        self.assertEqual(chunks[-1].decode_end_us, 10 * SECOND)

    def test_every_timestamp_has_deterministic_core_ownership(self):
        chunks = plan_processing_chunks(9_250_000, self.config)

        expected = {
            0: 0,
            3_999_999: 0,
            4_000_000: 1,
            7_999_999: 1,
            8_000_000: 2,
            9_250_000: 2,
        }
        for timestamp_us, chunk_index in expected.items():
            with self.subTest(timestamp_us=timestamp_us):
                self.assertEqual(owning_chunk_index(chunks, timestamp_us), chunk_index)

    def test_non_positive_duration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            plan_processing_chunks(0, self.config)


if __name__ == "__main__":
    unittest.main()
