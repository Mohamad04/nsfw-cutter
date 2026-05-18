from sqlalchemy.orm import Session

from models.video_cut import VideoCut


def add_cut_to_video(
    db: Session,
    *,
    video_id: int,
    cut_start_ms: int,
    cut_end_ms: int,
    reason: str | None = None,
    cut_duration_ms: int | None = None,
) -> VideoCut:
    cut = VideoCut(
        video_id=video_id,
        cut_start_ms=cut_start_ms,
        cut_end_ms=cut_end_ms,
        cut_duration_ms=cut_duration_ms,
        reason=reason,
    )
    db.add(cut)
    db.flush()
    return cut


def get_cuts_for_video(db: Session, video_id: int) -> list[VideoCut]:
    return db.query(VideoCut).filter(VideoCut.video_id == video_id).order_by(VideoCut.cut_start_ms).all()


def delete_cut(db: Session, video_cut_id: int) -> bool:
    cut = db.get(VideoCut, video_cut_id)
    if cut is None:
        return False
    db.delete(cut)
    db.flush()
    return True


def clear_cuts_for_video(db: Session, video_id: int) -> int:
    cuts = db.query(VideoCut).filter(VideoCut.video_id == video_id).all()
    count = len(cuts)
    for cut in cuts:
        db.delete(cut)
    db.flush()
    return count
