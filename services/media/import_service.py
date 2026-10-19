import threading
from collections.abc import Callable
from pathlib import Path

from database.session import get_db_session
from repositories.user_repository import create_user, get_user_by_email
from repositories.video_repository import add_video, find_video_for_path
from services.media.discovery_service import VideoDiscoveryService
from services.media.media_validation import validate_media_file
from services.subtitles.processing_service import SubtitleService


LOCAL_USER_EMAIL = "local@example.local"
LOCAL_USER_NAME = "local_user"
LOCAL_USER_PASSWORD = "local-placeholder-password"


class VideoImportService:
    def __init__(
        self,
        db_session_factory: Callable | None = None,
        video_discovery_service: VideoDiscoveryService | None = None,
        subtitle_service: SubtitleService | None = None,
        media_validator: Callable | None = None,
    ):
        self.db_session_factory = db_session_factory or get_db_session
        # Probes the real container and video stream before a file is listed or loaded (D9).
        self.media_validator = media_validator or validate_media_file
        self.video_discovery_service = video_discovery_service or VideoDiscoveryService()
        self.subtitle_service = subtitle_service or SubtitleService()
        # Files that passed validate_video_file: (size, mtime) seen then, and how many registrations those
        # checks still allow. Validation runs in a worker thread and registration on the GUI thread,
        # hence the lock.
        self._validated: dict[Path, tuple[tuple[int, int], int]] = {}
        self._validated_lock = threading.Lock()
        # Find-or-create must not interleave within this process (see register_video_file).
        self._register_lock = threading.Lock()

    def list_importable_videos(self, folder: str | Path) -> list[dict]:
        videos = self.video_discovery_service.find_videos_in_folder(folder)
        return [self._build_video_listing(video_path) for video_path in videos]

    def validate_video_file(self, file_path: str | Path, cancel_token=None) -> Path:
        """Extension check, then the ffprobe media checks; slow, so the GUI runs it in a worker thread."""
        video_path = self.video_discovery_service.validate_video_file(file_path)
        if cancel_token is None:
            self.media_validator(video_path)
        else:
            self.media_validator(video_path, cancel_token=cancel_token)
        resolved = video_path.resolve()
        stamp = _file_stamp(resolved)
        with self._validated_lock:
            previous_stamp, allowed = self._validated.get(resolved, (None, 0))
            self._validated[resolved] = (stamp, allowed + 1 if previous_stamp == stamp else 1)
        return video_path

    def build_video_listing_for_file(self, file_path: str | Path, cancel_token=None) -> dict:
        return self._build_video_listing(self.validate_video_file(file_path, cancel_token))

    def import_video_file(self, file_path: str | Path, user_id: int | None = None) -> dict:
        return self.register_video_file(self.validate_video_file(file_path), user_id)

    def register_video_file(self, video_path: str | Path, user_id: int | None = None) -> dict:
        """Record a video that passed ``validate_video_file`` and has not changed since (no new probe).

        A file that was never validated, or was modified or replaced after its check, is refused, so
        the D9 validation cannot be skipped by calling this method directly.

        Reopening a file reuses the oldest Video row of the same user for the same path (case-insensitive
        on Windows) and refreshes its file metadata, so its id and related records are kept. Older
        duplicate rows are left untouched. A moved file gets a new row. The reuse is serialized within
        this process only: the table has no unique index, so two application instances importing the
        same file at the same moment could still create two rows.
        """
        video_path = Path(video_path).resolve()
        try:
            current = _file_stamp(video_path)
        except OSError:
            current = None
        with self._validated_lock:
            stamp, allowed = self._validated.pop(video_path, (None, 0))
            if stamp == current and allowed > 1:
                self._validated[video_path] = (stamp, allowed - 1)
        if stamp is None or stamp != current:
            raise ValueError(
                f"\"{video_path.name}\" must be checked again before it is opened: it was not checked, "
                "or it changed after the check."
            )
        subtitle_path = self.subtitle_service.find_subtitle_for_video(video_path)

        with self._register_lock, self.db_session_factory() as db:
            if user_id is None:
                user = self.get_or_create_local_user(db)
                user_id = user.user_id

            file_metadata = {
                "video_name": video_path.name,
                "video_path": str(video_path),
                "file_size_bytes": video_path.stat().st_size,
                "format": video_path.suffix.lower().lstrip("."),
            }
            video = find_video_for_path(db, user_id=user_id, video_path=str(video_path))
            if video is None:
                video = add_video(db, user_id=user_id, **file_metadata)
            else:
                for field, value in file_metadata.items():
                    setattr(video, field, value)
                db.flush()

            return {
                "video_id": video.video_id,
                "video_name": video.video_name,
                "video_path": video.video_path,
                "video_url": Path(video.video_path).as_uri(),
                "subtitle_found": subtitle_path is not None,
                "subtitle_name": subtitle_path.name if subtitle_path else None,
                "status": "Video loaded",
            }

    def get_or_create_local_user(self, db):
        user = get_user_by_email(db, LOCAL_USER_EMAIL)
        if user is not None:
            return user

        return create_user(
            db,
            username=LOCAL_USER_NAME,
            email=LOCAL_USER_EMAIL,
            password=LOCAL_USER_PASSWORD,
        )

    def _build_video_listing(self, video_path: Path) -> dict:
        subtitle_path = self.subtitle_service.find_subtitle_for_video(video_path)
        resolved_path = video_path.resolve()
        return {
            "name": resolved_path.name,
            "path": str(resolved_path),
            "extension": resolved_path.suffix.lower(),
            "file_size_bytes": resolved_path.stat().st_size,
            "subtitle_found": subtitle_path is not None,
            "subtitle_name": subtitle_path.name if subtitle_path else None,
        }


def _file_stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns
