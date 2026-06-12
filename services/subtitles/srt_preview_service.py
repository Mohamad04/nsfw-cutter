from pathlib import Path

from services.subtitles.subtitle_loader_service import (
    load_subtitle_events,
    subtitle_text_at_position,
)


def parse_srt_file(path: str | Path) -> list[dict]:
    return load_subtitle_events(path)
