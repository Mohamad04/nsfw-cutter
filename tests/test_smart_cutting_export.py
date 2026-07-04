import unittest
from pathlib import Path

from services.export.audio_rebuild_service import AudioRebuildService
from services.export.export_router_service import (
    FAST_CUTTING_MODE,
    SMART_CUTTING_MODE,
    ExportRouterService,
)
from services.export.export_validation_service import validate_keyframes
from services.export.smart_cut_planner import (
    COPY_SEGMENT,
    DELETE_SEGMENT,
    REENCODE_SEGMENT,
    SmartCutPlanner,
)
from services.export.subtitle_rebuild_service import (
    EmbeddedSubtitleExtractService,
    map_original_timestamp_to_final,
    process_subtitle_event,
)
from services.export.video_segment_renderer import VideoSegmentRenderer


class SmartCutPlannerTests(unittest.TestCase):
    def test_keyframe_aligned_cut_uses_copy_segments_and_exact_delete_interval(self):
        plan = SmartCutPlanner().build_plan([(12.0, 23.0)], [0.0, 12.0, 23.0, 40.0], 40.0)

        self.assertEqual(plan.delete_intervals, [(12.0, 23.0)])
        self.assertEqual(
            [(segment.type, segment.start_seconds, segment.end_seconds) for segment in plan.segments],
            [
                (COPY_SEGMENT, 0.0, 12.0),
                (DELETE_SEGMENT, 12.0, 23.0),
                (COPY_SEGMENT, 23.0, 40.0),
            ],
        )

    def test_non_keyframe_cut_reencodes_only_boundary_chunks_without_expanding_delete(self):
        plan = SmartCutPlanner().build_plan([(12.0, 23.0)], [0.0, 10.0, 25.0, 40.0], 40.0)

        self.assertEqual(plan.delete_intervals, [(12.0, 23.0)])
        self.assertEqual(
            [(segment.type, segment.start_seconds, segment.end_seconds) for segment in plan.segments],
            [
                (COPY_SEGMENT, 0.0, 10.0),
                (REENCODE_SEGMENT, 10.0, 12.0),
                (DELETE_SEGMENT, 12.0, 23.0),
                (REENCODE_SEGMENT, 23.0, 25.0),
                (COPY_SEGMENT, 25.0, 40.0),
            ],
        )
        reencoded = [segment for segment in plan.segments if segment.type == REENCODE_SEGMENT]
        self.assertEqual([segment.decode_start_seconds for segment in reencoded], [10.0, 10.0])

    def test_multiple_cuts_keep_exact_delete_intervals(self):
        plan = SmartCutPlanner().build_plan(
            [(12.0, 23.0), (31.5, 33.0)],
            [0.0, 10.0, 25.0, 30.0, 35.0, 40.0],
            40.0,
        )

        self.assertEqual(plan.delete_intervals, [(12.0, 23.0), (31.5, 33.0)])
        self.assertIn((DELETE_SEGMENT, 12.0, 23.0), _segment_tuples(plan))
        self.assertIn((DELETE_SEGMENT, 31.5, 33.0), _segment_tuples(plan))
        self.assertIn((REENCODE_SEGMENT, 23.0, 25.0), _segment_tuples(plan))
        self.assertIn((REENCODE_SEGMENT, 30.0, 31.5), _segment_tuples(plan))
        self.assertIn((REENCODE_SEGMENT, 33.0, 35.0), _segment_tuples(plan))


class SmartCutCommandTests(unittest.TestCase):
    def test_reencode_video_chunk_is_video_only(self):
        renderer = VideoSegmentRenderer(ffmpeg_service=_FakeFFmpegService())

        command = renderer.build_reencode_command(Path("in.mkv"), Path("out.mp4"), 10.0, 12.0, 13.5)

        self.assertIn("-an", command)
        self.assertIn("-sn", command)
        self.assertIn("-c:v", command)
        self.assertIn("libx264", command)
        self.assertNotIn("-c:a", command)

    def test_copy_video_chunk_is_stream_copy_video_only(self):
        renderer = VideoSegmentRenderer(ffmpeg_service=_FakeFFmpegService())

        command = renderer.build_copy_command(Path("in.mkv"), Path("out.mp4"), 0.0, 10.0)

        self.assertIn("-an", command)
        self.assertIn("-sn", command)
        self.assertEqual(command[command.index("-c:v") + 1], "copy")

    def test_audio_rebuild_uses_kept_ranges_and_concat_filter(self):
        service = AudioRebuildService(ffmpeg_service=_FakeFFmpegService())

        filter_graph, output_label = service.build_filter_graph([(0.0, 12.0), (23.0, 40.0)])

        self.assertEqual(output_label, "[a]")
        self.assertIn("atrim=start=0.000:end=12.000", filter_graph)
        self.assertIn("atrim=start=23.000:end=40.000", filter_graph)
        self.assertIn("concat=n=2:v=0:a=1[a]", filter_graph)


class SmartSubtitleTests(unittest.TestCase):
    def test_embedded_subtitle_extract_maps_stream_index(self):
        service = EmbeddedSubtitleExtractService(ffmpeg_service=_FakeFFmpegService())

        command = service.build_extract_command(Path("in.mkv"), 3, Path("embedded.srt"))

        self.assertEqual(command[command.index("-map") + 1], "0:3")
        self.assertEqual(command[-1], "embedded.srt")

    def test_subtitle_after_removed_interval_is_shifted(self):
        mapped = map_original_timestamp_to_final(25000, [(12000, 23000)])

        self.assertEqual(mapped, 14000)

    def test_subtitle_inside_removed_interval_is_removed(self):
        rebuilt = process_subtitle_event(13000, 15000, [(12000, 23000)])

        self.assertEqual(rebuilt, [])

    def test_subtitle_spanning_removed_interval_is_clipped_and_shifted(self):
        rebuilt = process_subtitle_event(11000, 24000, [(12000, 23000)])

        self.assertEqual(rebuilt, [(11000, 12000), (12000, 13000)])


class SmartRouterTests(unittest.TestCase):
    def test_smart_route_keeps_raw_requested_segments_for_hybrid_pipeline(self):
        calls = []
        router = ExportRouterService(
            fast_export_start=lambda *args: self.fail("Fast export should not be called."),
            smart_export_start=lambda *args: calls.append(args) or True,
            fast_segment_mapper=lambda *_args: self.fail("Smart export should not use the fast mapper."),
        )
        raw_segment = {"start": "00:00:12", "end": "00:00:23"}

        self.assertTrue(router.start(SMART_CUTTING_MODE, "in.mkv", [raw_segment], "out", "remove_intervals", None))

        self.assertEqual(calls[0][1], [raw_segment])

    def test_fast_route_uses_existing_fast_segment_mapper(self):
        calls = []
        router = ExportRouterService(
            fast_export_start=lambda *args: calls.append(args) or True,
            smart_export_start=lambda *args: self.fail("Smart export should not be called."),
            fast_segment_mapper=lambda index, segment: {"index": index, "mapped": segment["start"]},
        )

        self.assertTrue(
            router.start(
                FAST_CUTTING_MODE,
                "in.mkv",
                [{"start": "00:00:12"}],
                "out",
                "remove_intervals",
                None,
            )
        )

        self.assertEqual(calls[0][1], [{"index": 1, "mapped": "00:00:12"}])


class SmartFailureTests(unittest.TestCase):
    def test_no_keyframes_fails_gracefully(self):
        with self.assertRaisesRegex(ValueError, "keyframes are unavailable"):
            validate_keyframes([], 40.0)


def _segment_tuples(plan):
    return [(segment.type, segment.start_seconds, segment.end_seconds) for segment in plan.segments]


class _FakeFFmpegService:
    ffmpeg_path = Path("ffmpeg")
    ffprobe_path = Path("ffprobe")


if __name__ == "__main__":
    unittest.main()
