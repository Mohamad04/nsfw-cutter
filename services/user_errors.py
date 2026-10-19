"""User-facing error messages shared by opening, analysis and export (D8).

``describe_error`` turns an exception into a short message for the interface and a category;
``technical_details`` keeps everything a developer needs (type, message, FFmpeg command and stderr,
cause chain) for the log. Messages that the application already writes for users (validation
refusals, Fast/Smart Cutting refusals) are passed through; raw FFmpeg output, OS error codes and
programming errors are translated. An unknown failure is never hidden: its own first line is shown.

Messages with a stable code (``services.user_messages``) are shown in the interface language;
``technical_details`` and the log stay in English.
"""

import errno
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from services.infrastructure.ffmpeg.bounded_runner import ExportCancelledError, FFmpegTimeoutError
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError
from services.media.media_validation import MediaValidationError
from services.user_messages import TEMPLATES, english, localized_text, translated


@dataclass(frozen=True)
class UserError:
    category: str
    message: str


CORRUPTION_MARKERS = (
    "moov atom not found",
    "invalid data found when processing input",
    "partial file",
    "file ended prematurely",
    "ebml header parsing failed",
    "error while decoding",
    "invalid nal unit size",
)
UNSUPPORTED_MARKERS = (
    "unknown encoder",
    "encoder not found",
    "decoder not found",
    "not currently supported in container",
    "could not find tag for codec",
    "unsupported codec",
)
INCOMPATIBLE_FFMPEG_MARKERS = ("unrecognized option", "option not found")
DISK_FULL_MARKERS = ("no space left on device", "not enough space on the disk")
ACCESS_MARKERS = ("permission denied",)
MISSING_MARKERS = ("no such file or directory",)
DISK_FULL_WINERRORS = {39, 112}
PROGRAMMING_ERRORS = (AttributeError, KeyError, IndexError, TypeError, NameError, AssertionError, ZeroDivisionError)
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[^\s'\"<>|]*")
_FFMPEG_CONTEXT = re.compile(r"\[[^\]]+ @ (?:0x)?[0-9A-Fa-f]+\]\s*")

MESSAGES = {
    category: english(f"errors.{category}")
    for category in (
        "cancelled", "corrupted_media", "unsupported_media", "ffmpeg_unavailable", "ffmpeg_incompatible", "disk_full",
    )
}


def _coded(category: str, message_code: str, /, **params) -> UserError:
    return UserError(category, translated(message_code, **params))


def describe_error(exc: BaseException) -> UserError:
    chain = _chain(exc)
    if any(isinstance(item, ExportCancelledError) for item in chain):
        return _coded("cancelled", "errors.cancelled")
    timeout = next((item for item in chain if isinstance(item, FFmpegTimeoutError)), None)
    if timeout is not None:
        return _coded("timeout", "errors.timeout", reason=timeout.reason)
    if any(isinstance(item, FFmpegNotFoundError) for item in chain):
        return _coded("ffmpeg_unavailable", "errors.ffmpeg_unavailable")
    if isinstance(exc, MediaValidationError):
        return UserError(exc.category, localized_text(exc))
    if getattr(exc, "message_code", "") in TEMPLATES:
        return UserError("invalid_request" if isinstance(exc, ValueError) else "unexpected", localized_text(exc))
    if isinstance(exc, ValidationError):
        return UserError("invalid_request", format_validation_error(exc))
    # Only explicit causes: an OSError met and handled while raising a curated error must not replace it.
    os_error = next((item for item in _chain(exc, causes_only=True) if isinstance(item, OSError)), None)
    if os_error is not None:
        return _describe_os_error(os_error)

    text = _diagnostic_text(exc)
    for category, markers in (
        ("disk_full", DISK_FULL_MARKERS),
        ("ffmpeg_incompatible", INCOMPATIBLE_FFMPEG_MARKERS),
        ("corrupted_media", CORRUPTION_MARKERS),
        ("unsupported_media", UNSUPPORTED_MARKERS),
    ):
        if any(marker in text for marker in markers):
            return _coded(category, f"errors.{category}")
    if any(marker in text for marker in ACCESS_MARKERS):
        return _coded("access_denied", "errors.access_denied")
    if any(marker in text for marker in MISSING_MARKERS):
        return _coded("missing_file", "errors.missing_file")

    return_code = getattr(exc, "return_code", None)
    if return_code is not None and getattr(exc, "stderr", None) is not None:
        return _coded("ffmpeg_failed", "errors.ffmpeg_failed", code=return_code)
    if isinstance(exc, PROGRAMMING_ERRORS):
        return _coded("unexpected", "errors.unexpected", type=type(exc).__name__)
    category = "invalid_request" if isinstance(exc, ValueError) else "unexpected"
    return UserError(category, _first_line(exc) or f"{type(exc).__name__} (see {_log_hint()})")


def user_message(exc: BaseException) -> str:
    return describe_error(exc).message


def is_cancellation(exc: BaseException) -> bool:
    return describe_error(exc).category == "cancelled"


def format_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid video cut request."
    first = errors[0]
    if first.get("type") == "enum" and "export_mode" in first.get("loc", ()):
        return (
            f"Unsupported export mode \"{first.get('input')}\". Choose removing intervals, "
            "separate clips or merged clips."
        )
    message = str(first.get("msg") or "Invalid video cut request.")
    return message.removeprefix("Value error, ")


def technical_details(exc: BaseException) -> str:
    lines = []
    for item in _chain(exc):
        lines.append(f"{type(item).__name__}: {item}")
        command = getattr(item, "command", None)
        if command:
            lines.append(f"  command: {' '.join(str(part) for part in command)}")
        if getattr(item, "return_code", None) is not None:
            lines.append(f"  return code: {item.return_code}")
        stderr = getattr(item, "stderr", None)
        if stderr:
            lines.append(f"  stderr (last 2000 chars): {str(stderr)[-2000:]}")
        detail = getattr(item, "detail", None)
        if detail:
            lines.append(f"  detail: {detail}")
    return "\n".join(lines)


def _describe_os_error(exc: OSError) -> UserError:
    name = Path(exc.filename).name if exc.filename else ""
    named = "named" if name else "unnamed"
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.ENOSPC or winerror in DISK_FULL_WINERRORS:
        return _coded("disk_full", "errors.disk_full")
    if isinstance(exc, (FileExistsError, NotADirectoryError)):
        if exc.filename and Path(exc.filename).is_file():
            return _coded("invalid_output_location", "export.output_not_a_folder", name=name)
        return _coded("output_exists", f"errors.output_exists_{named}", name=name)
    if isinstance(exc, FileNotFoundError):
        return _coded("missing_file", f"errors.missing_file_{named}", name=name)
    if isinstance(exc, PermissionError):
        return _coded("access_denied", f"errors.access_denied_{named}", name=name)
    return _coded("file_error", f"errors.file_error_{named}", name=name, reason=exc.strerror or type(exc).__name__)


def _chain(exc: BaseException, causes_only: bool = False) -> list[BaseException]:
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        chain.append(exc)
        seen.add(id(exc))
        exc = exc.__cause__ if causes_only else (exc.__cause__ or exc.__context__)
    return chain


def _diagnostic_text(exc: BaseException) -> str:
    return " ".join(f"{item} {getattr(item, 'stderr', '') or ''}" for item in _chain(exc)).casefold()


def _first_line(exc: BaseException) -> str:
    text = _FFMPEG_CONTEXT.sub("", str(exc)).strip()
    text = _WINDOWS_PATH.sub(lambda match: Path(match.group(0).rstrip(".,:;")).name, text)
    first = text.splitlines()[0] if text else ""
    return first[:300]


def _log_hint() -> str:
    return "the application log (logs/video-cut.log)"
