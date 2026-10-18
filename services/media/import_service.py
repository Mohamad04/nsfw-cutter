import threading
from collections.abc import Callable
from pathlib import Path

from database.session import get_db_session
from repositories.user_repository import create_user, get_user_by_email
from repositories.video_repository import add_video
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
        # Files that passed validate_video_file, with the (size, mtime) seen then. Validation runs in a
        # worker thread and registration on the GUI thread, hence the lock.
        self._validated: dict[Path, tuple[int, int]] = {}
        self._validated_lock = threading.Lock()

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
        with self._validated_lock:
            self._validated[resolved] = _file_stamp(resolved)
        return video_path

    def build_video_listing_for_file(self, file_path: str | Path, cancel_token=None) -> dict:
        return self._build_video_listing(self.validate_video_file(file_path, cancel_token))

    def import_video_file(self, file_path: str | Path, user_id: int | None = None) -> dict:
        return self.register_video_file(self.validate_video_file(file_path), user_id)

    def register_video_file(self, video_path: str | Path, user_id: int | None = None) -> dict:
        """Record a video that passed ``validate_video_file`` and has not changed since (no new probe).

        A file that was never validated, or was modified or replaced after its check, is refused, so
        the D9 validation cannot be skipped by calling this method directly.
        """
        video_path = Path(video_path).resolve()
        with self._validated_lock:
            stamp = self._validated.pop(video_path, None)
        try:
            current = _file_stamp(video_path)
        except OSError:
            current = None
        if stamp is None or stamp != current:
            raise ValueError(
                f"\"{video_path.name}\" must be checked again before it is opened: it was not checked, "
                "or it changed after the check."
            )
        subtitle_path = self.subtitle_service.find_subtitle_for_video(video_path)

        with self.db_session_factory() as db:
            if user_id is None:
                user = self.get_or_create_local_user(db)
                user_id = user.user_id

            video = add_video(
                db,
                user_id=user_id,
                video_name=video_path.name,
                video_path=str(video_path),
                file_size_bytes=video_path.stat().st_size,
                format=video_path.suffix.lower().lstrip("."),
            )

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
