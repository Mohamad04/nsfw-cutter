# Codex Patch: Remove All Re-Encoding From Video Cutting

## Context
The project already received a first Markdown spec about video cutting. That spec may have mentioned an optional re-encoding / accurate cut mode.

This is now rejected.

The application must **never re-encode videos** during cutting, trimming, removing segments, or merging selected cuts.

The goal is:

- Fast cutting.
- No quality loss.
- No video/audio re-encoding.
- FFmpeg stream copy only.
- Keyframe-based precision is acceptable.

## Critical Requirement
Remove every feature, option, command, label, enum, setting, branch, or UI control that offers re-encoding.

The app must not expose or internally call any mode such as:

- Accurate cut
- Frame-perfect cut
- Re-encode cut
- H.264 export
- libx264 export
- CRF export
- Preset export
- Transcode export

Only keep:

```text
Fast cut / no re-encode / stream copy
```

## FFmpeg Rule
Every cutting and merging operation must use stream copy:

```bash
-c copy
```

The app must not use commands containing:

```bash
-c:v libx264
-c:a aac
-crf
-preset
-filter_complex
-vf
-af
```

Exception: `-filter_complex` must not be used for cut/merge because it usually implies decoding/re-encoding. Use the concat **demuxer**, not the concat filter.

## Correct Behavior for Removing a Segment
If the user selects this interval to remove:

```text
00:00:33 -> 00:00:42
```

from a video of:

```text
00:01:12
```

then the app should keep:

```text
Segment 1: 00:00:00 -> 00:00:33
Segment 2: 00:00:42 -> 00:01:12
```

Then it should concatenate the kept segments without re-encoding.

Expected final duration should be approximately:

```text
01:12 - 00:09 = 01:03
```

Because this is stream-copy cutting, the result may be slightly different because FFmpeg cuts around keyframes. However, an output of `01:07` means the app probably did not remove the intended interval correctly or used the wrong duration calculation.

## Implementation Pattern

### 1. Derive Keep Segments
For every selected cut/removal interval, derive the complement intervals to keep.

Example:

```python
video_duration = 72.0
cuts_to_remove = [
    {"start": 33.0, "end": 42.0}
]

keep_segments = [
    {"start": 0.0, "end": 33.0},
    {"start": 42.0, "end": 72.0}
]
```

For multiple cuts, sort them, validate them, merge overlapping intervals, then compute the remaining keep segments.

### 2. Export Each Kept Segment With `-c copy`
Use `-ss` and `-t`, not ambiguous `-to` logic.

```bash
ffmpeg -y -hide_banner \
  -ss START_TIME \
  -i input.mp4 \
  -t DURATION \
  -map 0 \
  -c copy \
  -avoid_negative_ts make_zero \
  keep_001.mp4
```

Where:

```text
DURATION = segment_end - segment_start
```

### 3. Merge Kept Segments With Concat Demuxer
Create a concat list file:

```text
file 'keep_001.mp4'
file 'keep_002.mp4'
```

Then run:

```bash
ffmpeg -y -hide_banner \
  -f concat \
  -safe 0 \
  -i concat_list.txt \
  -map 0 \
  -c copy \
  final_output.mp4
```

Do not use concat filter.

## Required Code Changes

### Remove Re-Encoding From Backend
Search the codebase for:

```text
reencode
re-encode
accurate
frame-perfect
libx264
aac
crf
preset
filter_complex
transcode
```

Remove these from the video cutting path.

If there is an enum like:

```python
class CutMode(str, Enum):
    FAST = "fast"
    ACCURATE = "accurate"
```

replace it with one fixed mode or remove the enum entirely:

```python
CUT_MODE = "stream_copy"
```

or:

```python
class CutMode(str, Enum):
    STREAM_COPY = "stream_copy"
```

There must be no user-selectable re-encoding mode.

### Update Settings Model
If the Pydantic settings model contains options like:

```python
accurate_cut_enabled: bool
reencode_enabled: bool
video_codec: str
crf: int
preset: str
```

remove them from settings.

Keep only preferences like:

```python
default_export_dir: Path | None = None
last_video_path: Path | None = None
recent_videos: list[Path] = []
default_cut_behavior: Literal["remove_selected_segments"] = "remove_selected_segments"
```

### Update UI
Remove any UI option that suggests re-encoding or accurate export.

The UI should clearly say:

```text
Fast Cut: No re-encoding, keyframe-based
```

Do not give the user a toggle for re-encoding.

## Debugging Requirement
The currently selected cuts are not visible enough in the UI, making debugging difficult.

Add a proper cut list area that always displays every selected cut with:

- Index
- Start time
- End time
- Duration to remove
- Reason
- Tags
- Actions: Edit, Delete

Example:

| # | Start | End | Remove Duration | Reason | Tags | Actions |
|---|-------|-----|-----------------|--------|------|---------|
| 1 | 00:00:33 | 00:00:42 | 00:00:09 | manual | nsfw | Edit / Delete |

The cut must appear in the list immediately after clicking `Add Cut`.

## Export Debug Logs
When exporting, log the following to console and optionally to the UI:

```text
Input video: ...
Video duration: 72.000s
Cuts to remove:
  1. 33.000s -> 42.000s, duration 9.000s
Keep segments:
  1. 0.000s -> 33.000s, duration 33.000s
  2. 42.000s -> 72.000s, duration 30.000s
FFmpeg command for keep_001: ...
FFmpeg command for keep_002: ...
FFmpeg concat command: ...
Final output duration according to ffprobe: ...
```

This is required so we can verify whether the app is removing the correct interval.

## Acceptance Criteria

### Functional
- Selecting `00:00:33 -> 00:00:42` creates one visible cut in the UI.
- Exporting the video removes that interval, not another interval.
- For a `01:12` input, the output should be approximately `01:03`, allowing small variation caused by keyframe-based stream copy.
- The app creates temporary kept segments and merges them with concat demuxer.
- The final output is created without re-encoding.

### No Re-Encoding Verification
The generated FFmpeg commands must contain:

```bash
-c copy
```

The generated FFmpeg commands must not contain:

```bash
libx264
-aac
-c:a aac
-c:v
-crf
-preset
-filter_complex
-vf
-af
```

### UI
- Video controls should be embedded inside the video player, like a normal video player interface.
- The side panel should not waste too much space.
- The cut list must have enough vertical space to show actual cuts.
- The cut list must not look empty after adding a cut.
- The user must be able to see, edit, and delete selected cuts before exporting.

## Important Note About Accuracy
Because re-encoding is forbidden, cuts are keyframe-based and may not be perfectly frame-accurate.

That is acceptable.

Do not solve accuracy by adding re-encoding.

Instead, show this warning in the UI:

```text
No re-encoding mode is fast and preserves quality, but cuts may align to nearby keyframes.
```

