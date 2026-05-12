from sqlalchemy.orm import Session

from models.video_subtitle import VideoSubtitle


def add_subtitle_segment(
    db: Session,
    *,
    video_id: int,
    start_ms: int,
    end_ms: int,
    text: str | None = None,
    language: str | None = "und",
) -> VideoSubtitle:
    subtitle = VideoSubtitle(video_id=video_id, start_ms=start_ms, end_ms=end_ms, text=text, language=language)
    db.add(subtitle)
    db.flush()
    return subtitle


def get_subtitles_for_video(db: Session, video_id: int) -> list[VideoSubtitle]:
    return db.query(VideoSubtitle).filter(VideoSubtitle.video_id == video_id).order_by(VideoSubtitle.start_ms).all()


def delete_subtitle_segment(db: Session, subtitle_id: int) -> bool:
    subtitle = db.get(VideoSubtitle, subtitle_id)
    if subtitle is None:
        return False
    db.delete(subtitle)
    db.flush()
    return True
