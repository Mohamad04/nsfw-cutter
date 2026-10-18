import unittest

from services.export.video_packet_index import (
    VideoPacket,
    VideoPacketIndexError,
    copyable_range,
    is_clean_cut_point,
    kept_frame_durations,
    nearest_keyframes,
    packets_in_range,
    parse_packet_csv,
    timeline_mismatch,
)


def _closed_gop_packets() -> list[VideoPacket]:
    # 25 fps, GOP of 6 frames, two B-frames: decode order I P B B P B | I P B B P B
    order = [0, 3, 1, 2, 5, 4, 6, 9, 7, 8, 11, 10]
    return [VideoPacket(index / 25, index % 6 == 0, f"h{index}") for index in order]


def _open_gop_packets() -> list[VideoPacket]:
    # The second GOP's leading B-frames (4, 5) are decoded after its I-frame (6).
    order = [0, 3, 1, 2, 6, 4, 5, 9, 7, 8]
    return [VideoPacket(index / 25, index in (0, 6), f"h{index}") for index in order]


class VideoPacketIndexTests(unittest.TestCase):
    def test_parse_packet_csv_makes_pts_relative_to_format_start(self):
        packets = parse_packet_csv("1.400000,K__,murmur3:a\n1.520000,___,murmur3:b\n1.400000\n")

        self.assertEqual([packet.pts_seconds for packet in packets], [0.0, 0.12])
        self.assertEqual([packet.keyframe for packet in packets], [True, False])
        self.assertEqual(packets[1].data_hash, "murmur3:b")

    def test_parse_packet_csv_rejects_packets_without_pts(self):
        with self.assertRaises(VideoPacketIndexError):
            parse_packet_csv("N/A,K__,murmur3:a\n0.000000\n")

    def test_closed_gop_keyframe_is_a_clean_cut_point(self):
        packets = _closed_gop_packets()

        self.assertTrue(is_clean_cut_point(packets, 0.0))
        self.assertTrue(is_clean_cut_point(packets, 6 / 25))
        self.assertTrue(is_clean_cut_point(packets, 1.0))  # after the last frame
        self.assertFalse(is_clean_cut_point(packets, 2 / 25))  # not a keyframe
        self.assertFalse(is_clean_cut_point(packets, 6 / 25 + 0.001))

    def test_open_gop_keyframe_is_not_a_clean_cut_point(self):
        packets = _open_gop_packets()

        self.assertFalse(is_clean_cut_point(packets, 6 / 25))
        self.assertIsNone(copyable_range(packets, 0.0, 6 / 25))

    def test_copyable_range_lists_exactly_the_packets_presented_in_range(self):
        packets = _closed_gop_packets()

        selected = copyable_range(packets, 0.0, 6 / 25)

        self.assertEqual([packet.data_hash for packet in selected], ["h0", "h3", "h1", "h2", "h5", "h4"])
        self.assertIsNone(copyable_range(packets, 0.0, 5 / 25))

    def test_packets_in_range_is_half_open(self):
        packets = _closed_gop_packets()

        selected = packets_in_range(packets, 2 / 25, 6 / 25)

        self.assertEqual(sorted(round(packet.pts_seconds * 25) for packet in selected), [2, 3, 4, 5])

    def test_nearest_keyframes(self):
        packets = _closed_gop_packets()

        self.assertEqual(nearest_keyframes(packets, 0.1), (0.0, 0.24))
        self.assertEqual(nearest_keyframes(packets, 0.24), (0.24, 0.24))
        self.assertEqual(nearest_keyframes(packets, 0.3), (0.24, None))

    def test_timeline_check_accepts_exact_spacing_across_a_splice(self):
        source = [VideoPacket(index / 25, index % 6 == 0, f"h{index}") for index in range(12)]
        durations = kept_frame_durations(source, [(0.0, 0.12), (0.2, 1.0)])
        joined = [VideoPacket(index / 25, False, "x") for index in range(len(durations))]

        self.assertIsNone(timeline_mismatch(joined, durations, 0.0021))

    def test_timeline_check_reports_a_gap_or_a_squeezed_frame(self):
        source = [VideoPacket(index / 25, index % 6 == 0, f"h{index}") for index in range(12)]
        durations = kept_frame_durations(source, [(0.0, 1.0)])
        gap = [VideoPacket(t, False, "x") for t in [0.0, 0.04, 0.12] + [0.16 + k / 25 for k in range(9)]]

        self.assertIn("80.0 ms instead of 40.0 ms", timeline_mismatch(gap, durations, 0.0021))
        self.assertIn("frames instead of", timeline_mismatch(gap[:-1], durations, 0.0021))


if __name__ == "__main__":
    unittest.main()
