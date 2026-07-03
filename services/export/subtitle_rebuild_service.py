from __future__ import annotations

import copy
import logging
import subprocess
from pathlib import Path

from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)


class SubtitleRebuildError(RuntimeError):
    pass


class EmbeddedSubtitleExtractError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__("Smart Cutting failed while extracting embedded subtitles.")


class EmbeddedSubtitleExtractService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        command_runner=None,
    ):
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.command_runner = command_runner or subprocess.run
        self.commands: list[list[str]] = []
        self.stderr: list[str] = []

    def reset_diagnostics(self) -> None:
        self.commands = []
        self.stderr = []

    def extract_text_subtitle(
        self,
        input_path: str | Path,
        stream_index: int,
        output_path: str | Path,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_extract_command(Path(input_path), stream_index, output_path)
        self._run_command(command)
        return output_path

    def build_extract_command(self, input_path: Path, stream_index: int, output_path: Path) -> list[str]:
        return [
            str(self.ffmpeg_service.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-i",
            str(input_path),
            "-map",
            f"0:{int(stream_index)}",
            str(output_path),
        ]

    def _run_command(self, command: list[str]) -> None:
        logger.info("Running Smart Cutting subtitle extract command: %s", command)
        completed = self.command_runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.commands.append(list(command))
        self.stderr.append(completed.stderr or "")
        if completed.returncode != 0:
            raise EmbeddedSubtitleExtractError(command, completed.returncode, completed.stderr or "")


class SubtitleRebuildService:
    def rebuild_external_subtitle(
        self,
        subtitle_path: str | Path,
        delete_ranges: list[tuple[float, float]],
        output_path: str | Path,
    ) -> Path:
        try:
            import pysubs2
        except ImportError as exc:
            raise SubtitleRebuildError("pysubs2 is not installed, so text subtitles cannot be rebuilt.") from exc

        source_path = Path(subtitle_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subtitles = pysubs2.load(str(source_path))
        delete_ranges_ms = normalize_delete_ranges_to_ms(delete_ranges)

        rebuilt_events = []
        for event in subtitles.events:
            for start_ms, end_ms in process_subtitle_event(event.start, event.end, delete_ranges_ms):
                rebuilt_event = copy.copy(event)
                rebuilt_event.start = start_ms
                rebuilt_event.end = end_ms
                rebuilt_events.append(rebuilt_event)

        subtitles.events = rebuilt_events
        subtitles.save(str(output_path))
        return output_path


def normalize_delete_ranges_to_ms(delete_ranges: list[tuple[float, float]]) -> list[tuple[int, int]]:
    normalized = []
    for start_seconds, end_seconds in sorted(delete_ranges):
        start_ms = int(round(float(start_seconds) * 1000))
        end_ms = int(round(float(end_seconds) * 1000))
        if end_ms > start_ms:
            normalized.append((start_ms, end_ms))
    return normalized


def process_subtitle_event(
    start_ms: int,
    end_ms: int,
    delete_ranges_ms: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    visible_ranges = [(int(start_ms), int(end_ms))]
    for delete_start, delete_end in delete_ranges_ms:
        next_visible = []
        for visible_start, visible_end in visible_ranges:
            if visible_end <= delete_start or visible_start >= delete_end:
                next_visible.append((visible_start, visible_end))
                continue
            if visible_start < delete_start:
                next_visible.append((visible_start, delete_start))
            if delete_end < visible_end:
                next_visible.append((delete_end, visible_end))
        visible_ranges = next_visible
        if not visible_ranges:
            return []

    rebuilt = []
    for visible_start, visible_end in visible_ranges:
        mapped_start = map_original_timestamp_to_final(visible_start, delete_ranges_ms)
        mapped_end = map_original_timestamp_to_final(visible_end, delete_ranges_ms)
        if mapped_end > mapped_start:
            rebuilt.append((mapped_start, mapped_end))
    return rebuilt


def map_original_timestamp_to_final(timestamp_ms: int, delete_ranges_ms: list[tuple[int, int]]) -> int:
    timestamp = int(timestamp_ms)
    removed_before = 0
    for delete_start, delete_end in delete_ranges_ms:
        if timestamp <= delete_start:
            break
        if timestamp >= delete_end:
            removed_before += delete_end - delete_start
            continue
        removed_before += timestamp - delete_start
        break
    return max(0, timestamp - removed_before)
