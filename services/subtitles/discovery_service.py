from pathlib import Path

from services.media.validation_service import validate_input_video


SUPPORTED_SUBTITLE_EXTENSIONS = [".srt"]


def find_matching_external_subtitles(video_path: str | Path) -> list[dict]:
    resolved_path = validate_input_video(video_path)
    matches = []
    for extension in SUPPORTED_SUBTITLE_EXTENSIONS:
        subtitle_path = resolved_path.with_suffix(extension)
        if subtitle_path.is_file():
            matches.append(
                {
                    "path": str(subtitle_path.resolve()),
                    "filename": subtitle_path.name,
                    "extension": subtitle_path.suffix.lower(),
                    "detected_by": "same_stem_sidecar",
                }
            )
    return matches
