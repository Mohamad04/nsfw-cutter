"""User-facing error messages shared by opening, analysis and export (D8).

``describe_error`` turns an exception into a short message for the interface and a category;
``technical_details`` keeps everything a developer needs (type, message, FFmpeg command and stderr,
cause chain) for the log. Messages that the application already writes for users (validation
refusals, Fast/Smart Cutting refusals) are passed through; raw FFmpeg output, OS error codes and
programming errors are translated. An unknown failure is never hidden: its own first line is shown.
"""

import errno
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from services.infrastructure.ffmpeg.bounded_runner import ExportCancelledError, FFmpegTimeoutError
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError
from services.media.media_validation import MediaValidationError


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
    "cancelled": "The operation was cancelled. No output was kept.",
    "corrupted_media": (
        "The video file is damaged or incomplete (for example after an interrupted download or copy), "
        "so it cannot be processed. Try another copy of the file."
    ),
    "unsupported_media": (
        "This video uses a codec or format that this operation cannot handle. "
        "Try Smart Cutting, or convert the video to H.264 MP4 or MKV."
    ),
    "ffmpeg_unavailable": (
        "FFmpeg is missing, so videos cannot be processed. Reinstall the application or run "
        "scripts/prepare_ffmpeg.ps1 to restore the bundled FFmpeg."
    ),
    "ffmpeg_incompatible": (
        "The FFmpeg program in use does not support an option this application needs. The application "
        "expects the bundled FFmpeg 8.1.1; run scripts/prepare_ffmpeg.ps1 to restore it."
    ),
    "disk_full": "There is not enough free disk space to finish. Free some space or choose another output folder.",
}


def describe_error(exc: BaseException) -> UserError:
    chain = _chain(exc)
    if any(isinstance(item, ExportCancelledError) for item in chain):
        return UserError("cancelled", MESSAGES["cancelled"])
    timeout = next((item for item in chain if isinstance(item, FFmpegTimeoutError)), None)
    if timeout is not None:
        return UserError(
            "timeout",
            f"FFmpeg stopped responding ({timeout.reason}), so it was stopped. No output was kept. "
            "Try again; if it happens again, try the other cutting mode.",
        )
    if any(isinstance(item, FFmpegNotFoundError) for item in chain):
        return UserError("ffmpeg_unavailable", MESSAGES["ffmpeg_unavailable"])
    if isinstance(exc, MediaValidationError):
        return UserError(exc.category, str(exc))
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
            return UserError(category, MESSAGES[category])
    if any(marker in text for marker in ACCESS_MARKERS):
        return UserError("access_denied", "Access to a file was denied. Check that it is not open in another program.")
    if any(marker in text for marker in MISSING_MARKERS):
        return UserError("missing_file", "A required file can no longer be found. It may have been moved or deleted.")

    return_code = getattr(exc, "return_code", None)
    if return_code is not None and getattr(exc, "stderr", None) is not None:
        return UserError(
            "ffmpeg_failed",
            f"FFmpeg could not process this video (exit code {return_code}). No output was kept. "
            f"Technical details were written to {_log_hint()}.",
        )
    if isinstance(exc, PROGRAMMING_ERRORS):
        return UserError(
            "unexpected",
            f"An unexpected internal error occurred ({type(exc).__name__}). "
            f"Technical details were written to {_log_hint()}.",
        )
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
    target = f"\"{name}\"" if name else "a file"
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.ENOSPC or winerror in DISK_FULL_WINERRORS:
        return UserError("disk_full", MESSAGES["disk_full"])
    if isinstance(exc, (FileExistsError, NotADirectoryError)):
        if exc.filename and Path(exc.filename).is_file():
            return UserError(
                "invalid_output_location",
                f"The output folder cannot be used: {target} is an existing file, not a folder. "
                "Choose another output folder.",
            )
        return UserError(
            "output_exists",
            f"A file named {target} already exists, so nothing was overwritten. Choose another name or folder.",
        )
    if isinstance(exc, FileNotFoundError):
        return UserError("missing_file", f"{target[0].upper()}{target[1:]} can no longer be found. "
                                         "It may have been moved, renamed or deleted.")
    if isinstance(exc, PermissionError):
        return UserError(
            "access_denied",
            f"Access to {target} was denied. Check that it is not open in another program and that you "
            "are allowed to write to the output folder.",
        )
    return UserError(
        "file_error",
        f"A file operation on {target} failed ({exc.strerror or type(exc).__name__}). "
        f"Technical details were written to {_log_hint()}.",
    )


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
