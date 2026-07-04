from dataclasses import dataclass, field
from pathlib import Path

from core.time_utils import parse_fraction_to_float
from services.infrastructure.ffmpeg.probe import probe_media
from services.infrastructure.ffmpeg.runner import FFmpegService


@dataclass(frozen=True)
class VideoStreamInfo:
    index: int
    codec_name: str | None
    width: int | None
    height: int | None
    pix_fmt: str | None
    avg_frame_rate: float | None
    r_frame_rate: float | None
    time_base: str | None
    duration_seconds: float | None


@dataclass(frozen=True)
class AudioStreamInfo:
    index: int
    codec_name: str | None
    channels: int | None
    sample_rate: int | None
    duration_seconds: float | None


@dataclass(frozen=True)
class SubtitleStreamInfo:
    index: int
    codec_name: str | None
    language_code: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    format_name: str | None
    duration_seconds: float
    video_streams: list[VideoStreamInfo] = field(default_factory=list)
    audio_streams: list[AudioStreamInfo] = field(default_factory=list)
    subtitle_streams: list[SubtitleStreamInfo] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def video_stream(self) -> VideoStreamInfo | None:
        return self.video_streams[0] if self.video_streams else None

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_streams)

    @property
    def has_subtitles(self) -> bool:
        return bool(self.subtitle_streams)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "format_name": self.format_name,
            "duration_seconds": self.duration_seconds,
            "video_streams": [stream.__dict__ for stream in self.video_streams],
            "audio_streams": [stream.__dict__ for stream in self.audio_streams],
            "subtitle_streams": [stream.__dict__ for stream in self.subtitle_streams],
        }


class MediaProbeService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        probe_runner=None,
        media_probe=None,
    ):
        self.ffmpeg_service = ffmpeg_service
        self.probe_runner = probe_runner
        self.media_probe = media_probe or probe_media

    def probe(self, media_path: str | Path) -> MediaInfo:
        resolved_path = Path(media_path)
        payload = self.media_probe(
            resolved_path,
            ffmpeg_service=self.ffmpeg_service,
            probe_runner=self.probe_runner,
        )
        return media_info_from_ffprobe(resolved_path, payload)


def media_info_from_ffprobe(media_path: str | Path, payload: dict) -> MediaInfo:
    path = Path(media_path)
    format_data = payload.get("format") or {}
    streams = payload.get("streams") or []
    duration = _duration_from_format(format_data, streams)

    video_streams = []
    audio_streams = []
    subtitle_streams = []
    for stream in streams:
        stream_type = stream.get("codec_type")
        if stream_type == "video":
            video_streams.append(_video_stream(stream))
        elif stream_type == "audio":
            audio_streams.append(_audio_stream(stream))
        elif stream_type == "subtitle":
            subtitle_streams.append(_subtitle_stream(stream))

    return MediaInfo(
        path=path,
        format_name=format_data.get("format_name"),
        duration_seconds=duration,
        video_streams=video_streams,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        raw=payload,
    )


def _duration_from_format(format_data: dict, streams: list[dict]) -> float:
    duration = _float_or_none(format_data.get("duration"))
    if duration is not None and duration > 0:
        return duration
    for stream in streams:
        duration = _float_or_none(stream.get("duration"))
        if duration is not None and duration > 0:
            return duration
    raise ValueError("Unable to read a positive media duration.")


def _video_stream(stream: dict) -> VideoStreamInfo:
    return VideoStreamInfo(
        index=int(stream.get("index", 0)),
        codec_name=stream.get("codec_name"),
        width=_int_or_none(stream.get("width")),
        height=_int_or_none(stream.get("height")),
        pix_fmt=stream.get("pix_fmt"),
        avg_frame_rate=parse_fraction_to_float(stream.get("avg_frame_rate")),
        r_frame_rate=parse_fraction_to_float(stream.get("r_frame_rate")),
        time_base=stream.get("time_base"),
        duration_seconds=_float_or_none(stream.get("duration")),
    )


def _audio_stream(stream: dict) -> AudioStreamInfo:
    return AudioStreamInfo(
        index=int(stream.get("index", 0)),
        codec_name=stream.get("codec_name"),
        channels=_int_or_none(stream.get("channels")),
        sample_rate=_int_or_none(stream.get("sample_rate")),
        duration_seconds=_float_or_none(stream.get("duration")),
    )


def _subtitle_stream(stream: dict) -> SubtitleStreamInfo:
    tags = stream.get("tags") or {}
    return SubtitleStreamInfo(
        index=int(stream.get("index", 0)),
        codec_name=stream.get("codec_name"),
        language_code=tags.get("language"),
        title=tags.get("title"),
    )


def _float_or_none(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
