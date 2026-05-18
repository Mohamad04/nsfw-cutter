from collections.abc import Callable

from database.session import get_db_session
from repositories.video_cut_repository import add_cut_to_video, clear_cuts_for_video, delete_cut, get_cuts_for_video
from schemas.video_cut_schema import VideoCutCreateSchema


class CutService:
    def __init__(self, db_session_factory: Callable | None = None):
        self.db_session_factory = db_session_factory or get_db_session

    def create_cut(self, *, video_id: int, cut_start_ms: int, cut_end_ms: int, reason: str | None = None) -> dict:
        data = VideoCutCreateSchema(
            video_id=video_id,
            cut_start_ms=cut_start_ms,
            cut_end_ms=cut_end_ms,
            reason=reason,
        )
        with self.db_session_factory() as db:
            cut = add_cut_to_video(
                db,
                video_id=data.video_id,
                cut_start_ms=data.cut_start_ms,
                cut_end_ms=data.cut_end_ms,
                reason=data.reason,
            )
            return self._cut_to_dict(cut)

    def list_cuts(self, video_id: int) -> list[dict]:
        with self.db_session_factory() as db:
            return [self._cut_to_dict(cut) for cut in get_cuts_for_video(db, int(video_id))]

    def delete_cut(self, video_cut_id: int) -> bool:
        with self.db_session_factory() as db:
            return delete_cut(db, int(video_cut_id))

    def clear_cuts(self, video_id: int) -> int:
        with self.db_session_factory() as db:
            return clear_cuts_for_video(db, int(video_id))

    def _cut_to_dict(self, cut) -> dict:
        return {
            "video_cut_id": cut.video_cut_id,
            "video_id": cut.video_id,
            "cut_start_ms": cut.cut_start_ms,
            "cut_end_ms": cut.cut_end_ms,
            "cut_duration_ms": cut.cut_duration_ms,
            "reason": cut.reason,
        }
