from pathlib import Path

from services.infrastructure.ffmpeg.probe import extract_keyframes
from services.infrastructure.ffmpeg.runner import FFmpegService


class ExportKeyframeService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        probe_runner=None,
        keyframe_probe=None,
    ):
        self.ffmpeg_service = ffmpeg_service
        self.probe_runner = probe_runner
        self.keyframe_probe = keyframe_probe or extract_keyframes

    def extract_keyframes(self, input_path: str | Path) -> list[float]:
        return self.keyframe_probe(
            input_path,
            ffmpeg_service=self.ffmpeg_service,
            probe_runner=self.probe_runner,
        )

