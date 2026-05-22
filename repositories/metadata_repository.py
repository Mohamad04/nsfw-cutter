from sqlalchemy.orm import Session

from models.video_metadata import VideoMetadata


def create_video_metadata(db: Session, video_file_id: int, metadata: dict) -> VideoMetadata:
    video = metadata.get("video") or {}
    audio = metadata.get("audio") or {}
    record = VideoMetadata(
        video_file_id=video_file_id,
        duration_seconds=metadata.get("duration_seconds"),
        format_name=metadata.get("format_name"),
        format_long_name=metadata.get("format_long_name"),
        bit_rate=metadata.get("bit_rate"),
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name"),
        width=video.get("width"),
        height=video.get("height"),
        fps=video.get("fps"),
        raw_json=metadata.get("raw_ffprobe") or {},
    )
    db.add(record)
    db.flush()
    return record
