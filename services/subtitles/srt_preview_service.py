import html
import re
from bisect import bisect_right
from pathlib import Path


SRT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1256", "cp1252", "latin-1")
TIMESTAMP_LINE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)
TAG_RE = re.compile(r"<[^>]+>")


def parse_srt_file(path: str | Path) -> list[dict]:
    subtitle_path = Path(path).expanduser()
    text = _read_subtitle_text(subtitle_path)
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    cues = []

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        timestamp_index = _timestamp_line_index(lines)
        if timestamp_index is None:
            continue

        match = TIMESTAMP_LINE_RE.search(lines[timestamp_index])
        if match is None:
            continue

        subtitle_lines = lines[timestamp_index + 1 :]
        if not subtitle_lines:
            continue

        cue_text = _clean_subtitle_text("\n".join(subtitle_lines))
        if not cue_text:
            continue

        start_ms = _parse_timestamp_ms(match.group("start"))
        end_ms = _parse_timestamp_ms(match.group("end"))
        if end_ms <= start_ms:
            continue

        cues.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": cue_text,
            }
        )

    return sorted(cues, key=lambda cue: cue["start_ms"])


def subtitle_text_at_position(cues: list[dict], position_ms: int | float) -> str:
    if not cues:
        return ""

    starts = [cue["start_ms"] for cue in cues]
    index = bisect_right(starts, int(position_ms)) - 1
    if index < 0:
        return ""

    cue = cues[index]
    if cue["start_ms"] <= int(position_ms) <= cue["end_ms"]:
        return cue["text"]
    return ""


def _read_subtitle_text(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in SRT_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return path.read_text()


def _timestamp_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines[:3]):
        if TIMESTAMP_LINE_RE.search(line):
            return index
    return None


def _parse_timestamp_ms(timestamp: str) -> int:
    hours_text, minutes_text, seconds_text = timestamp.replace(",", ".").split(":")
    seconds, milliseconds = seconds_text.split(".")
    milliseconds = (milliseconds + "000")[:3]
    return (
        int(hours_text) * 3_600_000
        + int(minutes_text) * 60_000
        + int(seconds) * 1000
        + int(milliseconds)
    )


def _clean_subtitle_text(text: str) -> str:
    without_tags = TAG_RE.sub("", text)
    return html.unescape(without_tags).strip()
