from pydantic import ValidationError


def format_validation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first_error = exc.errors()[0] if exc.errors() else {}
        return first_error.get("msg") or "Invalid fast cut request."
    return str(exc)


def start_status(export_mode) -> str:
    export_value = getattr(export_mode, "value", str(export_mode))
    operation = {
        "remove_intervals": "Removing selected intervals",
        "export_clips_separate": "Exporting selected clips",
        "export_clips_merged": "Merging selected clips",
    }.get(export_value, "Starting video export")
    return f"{operation} with FFmpeg stream copy"


def format_cut_details(result_payload) -> str:
    if not isinstance(result_payload, dict) or not result_payload:
        return ""

    lines = [
        f"Mode: {result_payload.get('export_mode', '')}",
        f"Cutting: {result_payload.get('cut_mode', '')}",
        f"Selected intervals: {len(result_payload.get('segments') or [])}",
        f"Input duration: {duration_text(result_payload.get('input_duration_seconds'))}",
        f"Expected duration: {duration_text(result_payload.get('expected_output_duration_seconds'))}",
        f"Actual duration: {duration_text(result_payload.get('actual_output_duration_seconds'))}",
        f"Difference: {duration_text(result_payload.get('duration_difference_seconds'))}",
    ]
    normalized_intervals = result_payload.get("normalized_intervals") or []
    kept_intervals = result_payload.get("kept_intervals") or []
    if normalized_intervals:
        lines.append(f"Intervals: {normalized_intervals}")
    if kept_intervals:
        lines.append(f"Kept ranges: {kept_intervals}")
    commands = result_payload.get("ffmpeg_commands") or []
    lines.append(f"FFmpeg commands: {len(commands)}")
    if commands:
        lines.append(f"Final FFmpeg command: {' '.join(str(part) for part in commands[-1])}")
    return "\n".join(lines)


def duration_text(value) -> str:
    if value in (None, ""):
        return "-"
    return f"{float(value):.3f}s"
