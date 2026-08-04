import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pysubs2
import pytest

from schemas.video_cut_schema import VideoCutRequest, VideoCutSegment
from services.editing.cut_execution_service import CutExecutionService
from services.export.media_probe_service import MediaProbeService
from services.export.smart_cutting_export_service import SmartCuttingExportService
from services.infrastructure.ffmpeg.paths import get_ffmpeg_path, get_ffprobe_path
from services.subtitles.processing_service import SubtitleService
from services.subtitles.subtitle_loader_service import load_subtitle_events, subtitle_text_at_position


pytestmark = pytest.mark.e2e

SOURCE_DURATION_SECONDS = 8.0
FAST_DELETE_INTERVAL = (2.0, 4.0)
SMART_DELETE_INTERVAL = (2.35, 4.65)
DURATION_TOLERANCE_SECONDS = 0.75
FAST_DURATION_TOLERANCE_SECONDS = 2.0
SUBTITLE_TOLERANCE_MS = 120


@dataclass(frozen=True)
class MediaFixtures:
    root: Path
    ffmpeg: Path
    ffprobe: Path
    internal_video: Path
    external_video: Path
    external_subtitle: Path


@pytest.fixture(scope="session")
def media_fixtures(tmp_path_factory) -> MediaFixtures:
    root = tmp_path_factory.mktemp("media_e2e")
    ffmpeg = get_ffmpeg_path()
    ffprobe = get_ffprobe_path()
    base_video = root / "base.mp4"
    subtitle_source = root / "captions.srt"
    internal_video = root / "internal_source.mkv"
    external_video = root / "external_source.mp4"
    external_subtitle = root / "external_source.eng.srt"

    subtitle_source.write_text(
        """1
00:00:00,500 --> 00:00:01,500
Before cut

2
00:00:02,600 --> 00:00:03,400
Removed cue

3
00:00:04,000 --> 00:00:05,000
Crossing boundary

4
00:00:06,000 --> 00:00:07,000
After cut
""",
        encoding="utf-8",
    )

    _run_media_command(
        [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=25:duration=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=8",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "25",
            "-keyint_min",
            "25",
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-shortest",
            str(base_video),
        ]
    )
    _run_media_command(
        [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-i",
            str(base_video),
            "-i",
            str(subtitle_source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "srt",
            "-metadata:s:s:0",
            "language=eng",
            "-metadata:s:s:0",
            "title=English",
            str(internal_video),
        ]
    )
    shutil.copy2(base_video, external_video)
    shutil.copy2(subtitle_source, external_subtitle)

    return MediaFixtures(
        root=root,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        internal_video=internal_video,
        external_video=external_video,
        external_subtitle=external_subtitle,
    )


def test_internal_and_external_subtitles_are_discovered_and_readable(media_fixtures):
    subtitle_service = SubtitleService()

    internal_candidates = subtitle_service.discover_subtitles(media_fixtures.internal_video)
    external_candidates = subtitle_service.discover_subtitles(media_fixtures.external_video)

    assert len(internal_candidates) == 1
    assert internal_candidates[0]["source"] == "embedded"
    assert internal_candidates[0]["is_text_readable"] is True
    assert internal_candidates[0]["language_code"] == "eng"

    assert len(external_candidates) == 1
    assert external_candidates[0]["source"] == "external"
    assert external_candidates[0]["is_text_readable"] is True
    assert Path(external_candidates[0]["file_path"]).samefile(media_fixtures.external_subtitle)

    external_cues = load_subtitle_events(media_fixtures.external_subtitle)
    assert subtitle_text_at_position(external_cues, 1_000) == "Before cut"
    assert subtitle_text_at_position(external_cues, 3_000) == "Removed cue"


def test_quick_cut_removes_interval_and_preserves_internal_streams(media_fixtures, tmp_path):
    input_duration = MediaProbeService().probe(media_fixtures.internal_video).duration_seconds
    expected_duration = input_duration - (FAST_DELETE_INTERVAL[1] - FAST_DELETE_INTERVAL[0])
    request = VideoCutRequest(
        input_path=media_fixtures.internal_video,
        output_dir=tmp_path / "quick_output",
        export_mode="remove_intervals",
        cut_mode="stream_copy",
        segments=[
            VideoCutSegment(
                index=1,
                start_seconds=FAST_DELETE_INTERVAL[0],
                end_seconds=FAST_DELETE_INTERVAL[1],
                requested_start_seconds=FAST_DELETE_INTERVAL[0],
                requested_end_seconds=FAST_DELETE_INTERVAL[1],
            )
        ],
    )

    result = CutExecutionService(cache_dir=tmp_path / "quick_cache").export_segments(request)
    output_path = result.merged_output_path
    assert output_path is not None and output_path.is_file()
    assert result.cut_mode == "stream_copy"
    assert result.kept_intervals[0] == (0.0, 2.0)
    assert result.kept_intervals[1][0] == 4.0
    assert result.kept_intervals[1][1] == pytest.approx(input_duration, abs=0.001)
    assert result.expected_output_duration_seconds == pytest.approx(expected_duration, abs=0.001)
    assert abs(result.actual_output_duration_seconds - expected_duration) <= FAST_DURATION_TOLERANCE_SECONDS
    assert result.duration_warning is None
    assert all("copy" in command for command in result.ffmpeg_commands)

    output_info = MediaProbeService().probe(output_path)
    assert output_info.video_streams
    assert output_info.audio_streams
    assert output_info.subtitle_streams

    subtitles = _extract_subtitles(media_fixtures, output_path, tmp_path / "quick_output.srt")
    assert _find_subtitle(subtitles, "Before cut") is not None
    assert _find_subtitle(subtitles, "After cut") is not None


def test_smart_cut_rebuilds_external_subtitles_at_exact_timestamps(media_fixtures, tmp_path):
    output_path, result = _run_smart_cut(
        media_fixtures,
        media_fixtures.external_video,
        tmp_path,
    )

    assert result["cut_mode"] == "smart_cutting"
    assert result["normalized_intervals"] == [SMART_DELETE_INTERVAL]
    assert abs(result["actual_output_duration_seconds"] - 5.7) <= DURATION_TOLERANCE_SECONDS
    assert {segment["type"] for segment in result["plan"]["segments"]} >= {
        "copy",
        "delete",
        "reencode",
    }
    assert any(
        status.get("source") == "external" and status.get("status") == "rebuilt"
        for status in result["subtitles"]
    )
    _assert_complete_smart_output(media_fixtures, output_path, tmp_path / "external_result.srt")


def test_smart_cut_rebuilds_internal_subtitles_at_exact_timestamps(media_fixtures, tmp_path):
    output_path, result = _run_smart_cut(
        media_fixtures,
        media_fixtures.internal_video,
        tmp_path,
    )

    assert any(
        status.get("source") == "embedded" and status.get("status") == "rebuilt"
        for status in result["subtitles"]
    )
    _assert_complete_smart_output(media_fixtures, output_path, tmp_path / "internal_result.srt")


def _run_smart_cut(media_fixtures: MediaFixtures, input_path: Path, tmp_path: Path):
    service = SmartCuttingExportService(cache_dir=tmp_path / "smart_cache")
    response = service.export(
        {
            "input_path": str(input_path),
            "output_dir": str(tmp_path / "smart_output"),
            "export_mode": "remove_intervals",
            "segments": [
                {
                    "start_seconds": SMART_DELETE_INTERVAL[0],
                    "end_seconds": SMART_DELETE_INTERVAL[1],
                    "requested_start_seconds": SMART_DELETE_INTERVAL[0],
                    "requested_end_seconds": SMART_DELETE_INTERVAL[1],
                }
            ],
        }
    )
    result = response["result"]
    output_path = Path(result["merged_output_path"])
    assert output_path.is_file()
    return output_path, result


def _assert_complete_smart_output(media_fixtures: MediaFixtures, output_path: Path, extracted_path: Path):
    output_info = MediaProbeService().probe(output_path)
    assert output_info.video_streams
    assert output_info.audio_streams
    assert output_info.subtitle_streams
    assert abs(output_info.duration_seconds - 5.7) <= DURATION_TOLERANCE_SECONDS

    subtitles = _extract_subtitles(media_fixtures, output_path, extracted_path)
    before = _find_subtitle(subtitles, "Before cut")
    crossing = _find_subtitle(subtitles, "Crossing boundary")
    after = _find_subtitle(subtitles, "After cut")

    assert before is not None
    assert crossing is not None
    assert after is not None
    assert _find_subtitle(subtitles, "Removed cue") is None
    _assert_subtitle_times(before, 500, 1_500)
    _assert_subtitle_times(crossing, 2_350, 2_700)
    _assert_subtitle_times(after, 3_700, 4_700)


def _extract_subtitles(media_fixtures: MediaFixtures, media_path: Path, output_path: Path):
    _run_media_command(
        [
            str(media_fixtures.ffmpeg),
            "-y",
            "-hide_banner",
            "-i",
            str(media_path),
            "-map",
            "0:s:0",
            "-c:s",
            "srt",
            str(output_path),
        ]
    )
    return pysubs2.load(str(output_path)).events


def _find_subtitle(events, expected_text: str):
    for event in events:
        normalized_text = event.text.replace("\\N", "\n").strip()
        if normalized_text == expected_text:
            return event
    return None


def _assert_subtitle_times(event, expected_start_ms: int, expected_end_ms: int):
    assert abs(event.start - expected_start_ms) <= SUBTITLE_TOLERANCE_MS
    assert abs(event.end - expected_end_ms) <= SUBTITLE_TOLERANCE_MS


def _run_media_command(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Media fixture command failed with exit code {completed.returncode}:\n"
            f"{' '.join(command)}\n{completed.stderr}"
        )
