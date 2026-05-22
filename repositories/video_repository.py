from sqlalchemy.orm import Session

from models.video import Video
from models.video_file import VideoFile


def add_video(
    db: Session,
    *,
    user_id: int,
    video_name: str,
    video_path: str,
    duration_ms: int | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
    file_size_bytes: int | None = None,
    format: str | None = None,
) -> Video:
    video = Video(
        user_id=user_id,
        video_name=video_name,
        video_path=video_path,
        duration_ms=duration_ms,
        fps=fps,
        width=width,
        height=height,
        file_size_bytes=file_size_bytes,
        format=format,
    )
    db.add(video)
    db.flush()
    return video


def get_video_by_id(db: Session, video_id: int) -> Video | None:
    return db.get(Video, video_id)


def get_videos_by_user(db: Session, user_id: int) -> list[Video]:
    return db.query(Video).filter(Video.user_id == user_id).order_by(Video.created_at.desc()).all()


def delete_video(db: Session, video_id: int) -> bool:
    video = get_video_by_id(db, video_id)
    if video is None:
        return False
    db.delete(video)
    db.flush()
    return True


def update_video_metadata(db: Session, video_id: int, **metadata) -> Video | None:
    allowed_fields = {"video_name", "video_path", "duration_ms", "fps", "width", "height", "file_size_bytes", "format"}
    video = get_video_by_id(db, video_id)
    if video is None:
        return None

    for field, value in metadata.items():
        if field in allowed_fields:
            setattr(video, field, value)
    db.flush()
    return video


def update_video_rows_for_metadata(db: Session, metadata: dict) -> list[Video]:
    video_summary = metadata.get("video") or {}
    duration_seconds = metadata.get("duration_seconds")
    duration_ms = int(duration_seconds * 1000) if duration_seconds is not None else None

    videos = db.query(Video).filter(Video.video_path == metadata["path"]).all()
    for video in videos:
        video.duration_ms = duration_ms
        video.fps = video_summary.get("fps")
        video.width = video_summary.get("width")
        video.height = video_summary.get("height")
        video.file_size_bytes = metadata.get("file_size_bytes")
        video.format = metadata.get("extension", "").lstrip(".") or None

    db.flush()
    return videos


def upsert_video_file(db: Session, metadata: dict) -> VideoFile:
    video_file = db.query(VideoFile).filter(VideoFile.path == metadata["path"]).one_or_none()
    if video_file is None:
        video_file = VideoFile(
            path=metadata["path"],
            filename=metadata["filename"],
            stem=metadata["stem"],
            extension=metadata["extension"],
            file_size_bytes=metadata["file_size_bytes"],
        )
        db.add(video_file)
    else:
        video_file.filename = metadata["filename"]
        video_file.stem = metadata["stem"]
        video_file.extension = metadata["extension"]
        video_file.file_size_bytes = metadata["file_size_bytes"]

    db.flush()
    return video_file
