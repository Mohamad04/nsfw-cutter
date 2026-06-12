import html
import re
from bisect import bisect_right
from pathlib import Path

import pysubs2


SUBTITLE_ENCODINGS = ("utf-8-sig", "utf-8", "cp1256", "cp1252", "latin-1")
ASS_OVERRIDE_TAG_RE = re.compile(r"\{\\[^{}]*\}")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def load_subtitle_events(path: str | Path, fps: float | None = None) -> list[dict]:
    subtitle_path = Path(path).expanduser()
    last_error: Exception | None = None

    for encoding in SUBTITLE_ENCODINGS:
        try:
            cues = _load_subtitle_events_with_encoding(subtitle_path, encoding, fps)
        except OSError:
            raise
        except Exception as exc:
            last_error = exc
            continue

        if _contains_surrogateescape_text(cues) and encoding != SUBTITLE_ENCODINGS[-1]:
            continue

        return sorted(cues, key=lambda cue: cue["start_ms"])

    if last_error is not None:
        raise last_error
    return []


def subtitle_text_at_position(cues: list[dict], position_ms: int | float) -> str:
    if not cues:
        return ""

    normalized_position = int(position_ms)
    starts = [cue["start_ms"] for cue in cues]
    index = bisect_right(starts, normalized_position) - 1
    if index < 0:
        return ""

    cue = cues[index]
    if cue["start_ms"] <= normalized_position <= cue["end_ms"]:
        return cue["text"]
    return ""


def _load_subtitle_events_with_encoding(path: Path, encoding: str, fps: float | None) -> list[dict]:
    subtitle_file = pysubs2.load(str(path), encoding=encoding, fps=fps, errors="surrogateescape")
    cues = []

    for event in subtitle_file.events:
        if getattr(event, "is_comment", False):
            continue

        start_ms = int(event.start)
        end_ms = int(event.end)
        if end_ms <= start_ms:
            continue

        text = _clean_subtitle_text(event.text)
        if not text:
            continue

        cues.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
            }
        )

    return cues


def _clean_subtitle_text(text: str) -> str:
    normalized = text.replace("\\N", "\n").replace("\\n", "\n")
    without_ass_tags = ASS_OVERRIDE_TAG_RE.sub("", normalized)
    without_html_tags = HTML_TAG_RE.sub("", without_ass_tags)
    return html.unescape(without_html_tags).strip()


def _contains_surrogateescape_text(cues: list[dict]) -> bool:
    for cue in cues:
        if any(0xDC80 <= ord(character) <= 0xDCFF for character in cue["text"]):
            return True
    return False
