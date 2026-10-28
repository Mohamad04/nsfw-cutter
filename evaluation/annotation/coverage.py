"""Which parts of a video were genuinely played, for the full-viewing requirement (pure Python, no Qt).

The player reports its position every few tens of milliseconds. A step from one reported position to
the next counts as watched only when it is consistent with real playback: it moves forward, and by no
more than playback rate x elapsed wall-clock time (plus a small jitter allowance). A seek, a skipped
segment or a jump forward therefore never counts, whatever the playback speed; replaying a segment
counts it once. The interface also interrupts tracking explicitly on every seek, stop, rate change and
media change. A pause followed by a resume with no seek in between keeps the paused position as the
anchor, so the frames shown between the pause and the next position report are not lost at each pause.
"""
from __future__ import annotations

# Total unplayed time still accepted as "complete": the player's position-update granularity (~50 ms)
# and the gap between the container duration and the last decoded position at end of stream.
TIMING_TOLERANCE_SECONDS = 0.5
# Allowed excess of one media-time step over rate x wall time (timer and position-update jitter).
STEP_SLACK_SECONDS = 0.25


def merge(intervals):
    merged = []
    for start, end in sorted((float(a), float(b)) for a, b in intervals if b > a):
        if merged and start <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def covered_seconds(intervals, duration: float) -> float:
    return sum(max(0.0, min(end, duration) - max(start, 0.0)) for start, end in merge(intervals))


def unplayed_seconds(intervals, duration: float) -> float:
    return max(0.0, duration - covered_seconds(intervals, duration))


def fully_played(intervals, duration: float) -> bool:
    return unplayed_seconds(intervals, duration) <= TIMING_TOLERANCE_SECONDS


def unplayed_segments(intervals, duration: float, minimum: float = 0.25):
    """Gaps longer than `minimum` seconds, to tell the reviewer what is still unwatched."""
    gaps, cursor = [], 0.0
    for start, end in merge(intervals):
        if start - cursor > minimum:
            gaps.append([round(cursor, 2), round(min(start, duration), 2)])
        cursor = max(cursor, end)
    if duration - cursor > minimum:
        gaps.append([round(cursor, 2), round(duration, 2)])
    return gaps


class PlaybackTracker:
    def __init__(self, intervals=()):
        self.intervals = merge(intervals)
        self._anchor = None  # (media seconds, wall seconds, rate) of the last accepted observation

    def interrupt(self):
        """Pause, stop, seek, rate change or media change: the next observation starts a new segment."""
        self._anchor = None

    def resume(self, wall: float):
        """Playback resumes after a pause: the paused position stays the anchor, re-timed to the resume."""
        if self._anchor is not None:
            self._anchor = (self._anchor[0], wall, self._anchor[2])

    def observe(self, position: float, wall: float, rate: float) -> bool:
        """Records one position report made while playing; returns whether a step was counted."""
        anchor, self._anchor = self._anchor, (position, wall, rate)
        if anchor is None:
            return False
        last_position, last_wall, last_rate = anchor
        step, elapsed = position - last_position, wall - last_wall
        if rate != last_rate or step <= 0 or elapsed < 0 or step > last_rate * elapsed + STEP_SLACK_SECONDS:
            return False
        self.intervals = merge([*self.intervals, [last_position, position]])
        return True
