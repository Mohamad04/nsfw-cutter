import re
from datetime import datetime, timezone
from pathlib import Path


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_JOB_STATUSES = {"pending", "processing", "completed", "failed", "cancelled"}
LANGUAGE_RE = re.compile(r"^[a-zA-Z]{2,8}(-[a-zA-Z0-9]{2,8})?$|^und$")


def utc_now():
    return datetime.now(timezone.utc)


def clean_string(value: str | None, field_name: str, *, min_length: int = 0, max_length: int | None = None, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None

    cleaned = str(value).strip()
    if required and not cleaned:
        raise ValueError(f"{field_name} is required")
    if cleaned and len(cleaned) < min_length:
        raise ValueError(f"{field_name} must be at least {min_length} characters")
    if max_length is not None and len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return cleaned


def validate_email(value: str) -> str:
    email = clean_string(value, "email", max_length=255, required=True)
    if not EMAIL_RE.match(email):
        raise ValueError("Invalid email address")
    return email.lower()


def validate_non_negative(value: int, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if int(value) < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return int(value)


def validate_time_range(start_ms: int, end_ms: int, *, start_name: str = "start_ms", end_name: str = "end_ms") -> None:
    if start_ms is None or end_ms is None:
        return
    if int(start_ms) < 0:
        raise ValueError(f"{start_name} must be non-negative")
    if int(end_ms) <= int(start_ms):
        raise ValueError(f"{end_name} must be greater than {start_name}")


def validate_language(value: str | None) -> str | None:
    language = clean_string(value, "language", max_length=16)
    if language is None or language == "":
        return language
    if not LANGUAGE_RE.match(language):
        raise ValueError("language must be a short safe language code")
    return language.lower()


def validate_video_path(value: str) -> str:
    cleaned = clean_string(value, "video_path", max_length=1024, required=True)
    if "\x00" in cleaned:
        raise ValueError("video_path contains invalid characters")

    path = Path(cleaned).expanduser()
    if any(part == ".." for part in path.parts):
        raise ValueError("video_path must not contain path traversal")

    return str(path.resolve(strict=False))
