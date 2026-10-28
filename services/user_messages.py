"""Stable codes for the error messages shown to users, with their English text and translations.

An error that carries a code (``message_code`` and ``message_params``) keeps its English text in
``str()``, so the log and the technical details stay in English. ``localized_text`` renders the same
message in the interface language through the application's Qt catalogs (context ``UserMessages``,
extracted by ``pyside6-lupdate`` from the ``QT_TRANSLATE_NOOP`` entries below). The code, not the
English wording, selects the translation; an error without a code is shown as it is.
"""

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

CONTEXT = "UserMessages"

TEMPLATES = {
    # Opening a video (services/media/media_validation.py)
    "media.missing_file": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" cannot be found. It may have been moved, renamed or deleted."),
    "media.not_a_file": QT_TRANSLATE_NOOP("UserMessages", "\"{name}\" is a folder, not a video file."),
    "media.unsupported_extension": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" is not a supported video. Open an MP4 or MKV file."),
    "media.access_denied": QT_TRANSLATE_NOOP(
        "UserMessages",
        "\"{name}\" cannot be read. Check that you have access to it and that no other program is locking it."),
    "media.empty": QT_TRANSLATE_NOOP("UserMessages", "\"{name}\" is empty (0 bytes). It is not a usable video."),
    "media.ffmpeg_unavailable": QT_TRANSLATE_NOOP(
        "UserMessages",
        "FFmpeg is not available, so the video cannot be checked. Reinstall the application "
        "or run scripts/prepare_ffmpeg.ps1."),
    "media.ffmpeg_not_started": QT_TRANSLATE_NOOP(
        "UserMessages",
        "FFmpeg could not be started, so the video cannot be checked. Reinstall the application "
        "or run scripts/prepare_ffmpeg.ps1."),
    "media.damaged": QT_TRANSLATE_NOOP(
        "UserMessages",
        "\"{name}\" is damaged or incomplete and cannot be opened (for example after an interrupted "
        "download or copy)."),
    "media.wrong_extension": QT_TRANSLATE_NOOP(
        "UserMessages",
        "\"{name}\" is actually an {label} video, not {suffix}. "
        "Rename it with the {extension} extension, then open it again."),
    "media.unsupported_container": QT_TRANSLATE_NOOP(
        "UserMessages",
        "\"{name}\" is not an MP4 or MKV video (FFmpeg reads it as \"{container}\"). Open an MP4 or MKV file."),
    "media.no_video_cover": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" has no video to edit: it contains only a still cover picture."),
    "media.no_video_audio_only": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" has no video to edit: it contains only audio."),
    "media.no_video_empty": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" has no video to edit: it contains no audio or video."),
    "media.unknown_codec": QT_TRANSLATE_NOOP(
        "UserMessages",
        "\"{name}\" uses a video codec that FFmpeg cannot identify, so it cannot be played or edited."),
    "media.invalid_video_info": QT_TRANSLATE_NOOP(
        "UserMessages",
        "\"{name}\" has missing or invalid video information (frame size or duration). "
        "The file is probably damaged."),
    "media.undecodable": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" cannot be decoded: FFmpeg could not read its first video frame ({codec})."),
    "media.incomplete": QT_TRANSLATE_NOOP(
        "UserMessages",
        "\"{name}\" is incomplete: the end of the video is missing or damaged "
        "(for example after an interrupted download or copy)."),
    "media.timeout": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Checking \"{name}\" took too long (over {seconds} s). The drive may be very slow "
        "or the file may be damaged."),
    "media.recent_missing": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" no longer exists. It was removed from the recent files."),
    "media.could_not_open": QT_TRANSLATE_NOOP("UserMessages", "Could not open the video. {reason}"),
    "media.none_opened": QT_TRANSLATE_NOOP("UserMessages", "None of the selected files could be opened. {reason}"),
    # Export refusals (services/editing/cut_execution_service.py, controllers/video_cut)
    "fast.audio_removal": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Fast Cutting cannot remove audio exactly: stream copy keeps whole audio frames around each cut, "
        "so up to about 0.1 s of sound from every removed interval would remain. Nothing was exported. "
        "Use Smart Cutting, which rebuilds the audio exactly."),
    "fast.audio_merged": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Fast Cutting cannot merge clips with exact audio: stream copy keeps whole audio frames around each "
        "clip, so up to about 0.1 s of sound from outside the selected clips would be included. Nothing was "
        "exported. Use Smart Cutting, which rebuilds the audio exactly."),
    "fast.audio_clips": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Fast Cutting cannot export clips with exact audio: stream copy keeps whole audio frames around each "
        "clip, so up to about 0.1 s of sound from outside every clip would be included. Nothing was exported. "
        "Use Smart Cutting, which rebuilds the audio exactly."),
    "fast.keyframes_remove": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Fast Cutting cannot remove the selected intervals exactly: stream copy can only cut on a keyframe "
        "that starts an independent group of frames, and these cut boundaries are not on one: {details}. "
        "Nothing was exported and the cuts were not changed. Use Smart Cutting for frame-exact removal, "
        "or move these boundaries onto the listed keyframes."),
    "fast.keyframes_clips": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Fast Cutting cannot export the selected clips exactly: stream copy can only cut on a keyframe "
        "that starts an independent group of frames, and these cut boundaries are not on one: {details}. "
        "Nothing was exported and the cuts were not changed. Use Smart Cutting for frame-exact removal, "
        "or move these boundaries onto the listed keyframes."),
    "fast.boundary_open_gop": QT_TRANSLATE_NOOP(
        "UserMessages", "{time} (keyframe of an open GOP: earlier frames depend on it)"),
    "fast.boundary_one_keyframe": QT_TRANSLATE_NOOP("UserMessages", "{time} (nearest keyframes {first})"),
    "fast.boundary_two_keyframes": QT_TRANSLATE_NOOP(
        "UserMessages", "{time} (nearest keyframes {first} and {second})"),
    "export.output_not_a_folder": QT_TRANSLATE_NOOP(
        "UserMessages",
        "The output folder cannot be used: \"{name}\" is an existing file, not a folder. "
        "Choose another output folder."),
    "export.source_missing": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" can no longer be found. It may have been moved, renamed or deleted."),
    # Generic failures (services/user_errors.py)
    "errors.cancelled": QT_TRANSLATE_NOOP("UserMessages", "The operation was cancelled. No output was kept."),
    "errors.corrupted_media": QT_TRANSLATE_NOOP(
        "UserMessages",
        "The video file is damaged or incomplete (for example after an interrupted download or copy), "
        "so it cannot be processed. Try another copy of the file."),
    "errors.unsupported_media": QT_TRANSLATE_NOOP(
        "UserMessages",
        "This video uses a codec or format that this operation cannot handle. "
        "Try Smart Cutting, or convert the video to H.264 MP4 or MKV."),
    "errors.ffmpeg_unavailable": QT_TRANSLATE_NOOP(
        "UserMessages",
        "FFmpeg is missing, so videos cannot be processed. Reinstall the application or run "
        "scripts/prepare_ffmpeg.ps1 to restore the bundled FFmpeg."),
    "errors.ffmpeg_incompatible": QT_TRANSLATE_NOOP(
        "UserMessages",
        "The FFmpeg program in use does not support an option this application needs. The application "
        "expects the bundled FFmpeg 8.1.1; run scripts/prepare_ffmpeg.ps1 to restore it."),
    "errors.disk_full": QT_TRANSLATE_NOOP(
        "UserMessages",
        "There is not enough free disk space to finish. Free some space or choose another output folder."),
    "errors.timeout": QT_TRANSLATE_NOOP(
        "UserMessages",
        "FFmpeg stopped responding ({reason}), so it was stopped. No output was kept. "
        "Try again; if it happens again, try the other cutting mode."),
    "errors.access_denied": QT_TRANSLATE_NOOP(
        "UserMessages", "Access to a file was denied. Check that it is not open in another program."),
    "errors.access_denied_named": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Access to \"{name}\" was denied. Check that it is not open in another program and that you "
        "are allowed to write to the output folder."),
    "errors.access_denied_unnamed": QT_TRANSLATE_NOOP(
        "UserMessages",
        "Access to a file was denied. Check that it is not open in another program and that you "
        "are allowed to write to the output folder."),
    "errors.missing_file": QT_TRANSLATE_NOOP(
        "UserMessages", "A required file can no longer be found. It may have been moved or deleted."),
    "errors.missing_file_named": QT_TRANSLATE_NOOP(
        "UserMessages", "\"{name}\" can no longer be found. It may have been moved, renamed or deleted."),
    "errors.missing_file_unnamed": QT_TRANSLATE_NOOP(
        "UserMessages", "A file can no longer be found. It may have been moved, renamed or deleted."),
    "errors.output_exists_named": QT_TRANSLATE_NOOP(
        "UserMessages",
        "A file named \"{name}\" already exists, so nothing was overwritten. Choose another name or folder."),
    "errors.output_exists_unnamed": QT_TRANSLATE_NOOP(
        "UserMessages",
        "A file named a file already exists, so nothing was overwritten. Choose another name or folder."),
    "errors.file_error_named": QT_TRANSLATE_NOOP(
        "UserMessages",
        "A file operation on \"{name}\" failed ({reason}). "
        "Technical details were written to the application log (logs/video-cut.log)."),
    "errors.file_error_unnamed": QT_TRANSLATE_NOOP(
        "UserMessages",
        "A file operation on a file failed ({reason}). "
        "Technical details were written to the application log (logs/video-cut.log)."),
    "errors.ffmpeg_failed": QT_TRANSLATE_NOOP(
        "UserMessages",
        "FFmpeg could not process this video (exit code {code}). No output was kept. "
        "Technical details were written to the application log (logs/video-cut.log)."),
    "errors.unexpected": QT_TRANSLATE_NOOP(
        "UserMessages",
        "An unexpected internal error occurred ({type}). "
        "Technical details were written to the application log (logs/video-cut.log)."),
}


def english(code: str, /, **params) -> str:
    """The English message for ``code``: what ``str()`` of a coded error and the log show."""
    return TEMPLATES[code].format(**{key: english_param(value) for key, value in params.items()})


def translated(code: str, /, **params) -> str:
    """The message for ``code`` in the interface language (English when no catalog is installed).

    A parameter given as a ``(code, params)`` pair, or a list of them, is itself translated first;
    a list is joined with "; ".
    """
    rendered = {key: _render_param(value) for key, value in params.items()}
    template = QCoreApplication.translate(CONTEXT, TEMPLATES[code])
    try:
        return template.format(**rendered)
    except (KeyError, IndexError, ValueError):
        # A damaged translation must never hide the error itself.
        return english(code, **params)


def coded(error: BaseException, code: str, /, **params) -> BaseException:
    """Attach ``code`` and ``params`` to ``error`` (whose ``str()`` is the English text) and return it."""
    error.message_code = code
    error.message_params = params
    return error


def localized_text(error: BaseException) -> str:
    """The message to show for ``error``: translated when it carries a code, otherwise ``str(error)``."""
    code = getattr(error, "message_code", "")
    if code in TEMPLATES:
        return translated(code, **getattr(error, "message_params", {}))
    return str(error)


def _render_param(value):
    if isinstance(value, list):
        return "; ".join(str(_render_param(item)) for item in value)
    if isinstance(value, tuple) and len(value) == 2 and value[0] in TEMPLATES and isinstance(value[1], dict):
        return translated(value[0], **value[1])
    return value


def english_param(value):
    """English rendering of a parameter that ``translated`` would translate (for ``str()`` and the log)."""
    if isinstance(value, list):
        return "; ".join(str(english_param(item)) for item in value)
    if isinstance(value, tuple) and len(value) == 2 and value[0] in TEMPLATES and isinstance(value[1], dict):
        return english(value[0], **value[1])
    return value
