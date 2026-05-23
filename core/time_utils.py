from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def parse_fraction_to_float(value: str | None) -> float | None:
    if value is None:
        return None

    try:
        text = str(value).strip()
        if not text:
            return None
        if "/" not in text:
            return float(text)

        numerator, denominator = text.split("/", 1)
        numerator_float = float(numerator)
        denominator_float = float(denominator)
        if denominator_float == 0:
            return None
        return numerator_float / denominator_float
    except (TypeError, ValueError):
        return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def seconds_to_ffmpeg_time(seconds: float) -> str:
    total_milliseconds = _seconds_to_milliseconds(seconds)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def duration_seconds(start_seconds: float, end_seconds: float) -> float:
    start_milliseconds = _seconds_to_milliseconds(start_seconds)
    end_milliseconds = _seconds_to_milliseconds(end_seconds)
    if end_milliseconds <= start_milliseconds:
        raise ValueError("Segment end must be greater than segment start.")
    return float(Decimal(end_milliseconds - start_milliseconds) / Decimal(1_000))


def timecode_to_seconds(value: str) -> float:
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError("Cut times must use HH:MM:SS or HH:MM:SS.mmm.")

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = Decimal(parts[2])
    except (ValueError, ArithmeticError) as exc:
        raise ValueError("Cut times must use HH:MM:SS or HH:MM:SS.mmm.") from exc

    if hours < 0 or minutes < 0 or minutes > 59 or seconds < 0 or seconds >= 60:
        raise ValueError("Cut times must use HH:MM:SS or HH:MM:SS.mmm.")

    total_seconds = Decimal(hours * 3_600 + minutes * 60) + seconds
    return float(total_seconds.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _seconds_to_milliseconds(seconds: float) -> int:
    value = Decimal(str(seconds))
    if value < 0:
        raise ValueError("Seconds must be non-negative.")
    return int((value * Decimal(1_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
