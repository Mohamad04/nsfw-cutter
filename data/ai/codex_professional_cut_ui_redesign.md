# Codex Task — Redesign the Cutting UI Professionally and Make the Workflow Debuggable

## Context

The current UI still looks unprofessional and confusing. The video controls take too much separate space, the cut list area is not clearly usable, and the selected cuts are not visibly displayed, making the cutting feature hard to debug.

Also, remove any UI reference to `Accurate mode` or re-encoding. This app must use **no re-encoding at all**. Only FFmpeg stream copy is allowed.

## Main objective

Redesign the cutting interface so it behaves like a professional video player/editor:

- The video controls must be embedded inside the video player, similar to YouTube/VLC style.
- The selected removal intervals must appear immediately in a clear cut list.
- The timeline must visually show selected cut intervals.
- The export/remove workflow must be obvious.
- The UI must not include any re-encoding option.

---

## Required UI layout

### 1. Header bar

Keep the top header compact.

It should contain:

- App logo/name.
- Open file/folder button.
- Current video filename.
- Subtitle status.
- Settings gear icon.
- Video loaded/status indicator.

Do not make the header too tall.

---

### 2. Main video player area

The video player should be the central focus.

The controls must be embedded at the bottom of the video preview, not placed as a large separate block below it.

Inside the video player overlay, include:

- Play/Pause button.
- Timeline/progress bar.
- Current time / total duration.
- Volume icon + volume slider.
- Small skip buttons: `-60`, `-15`, `-5`, `+5`, `+15`, `+60`.
- `Set Start` and `Set End` buttons.
- Optional fullscreen button later.

The controls should appear as a bottom overlay with a semi-transparent/dark background.

Do not waste vertical space with huge buttons.

---

### 3. Current cut panel

Keep a compact right-side panel called:

```text
Current Removal Interval
```

This panel should contain:

- Start time
- End time
- Duration preview
- Reason
- Tags
- Add cut button
- Reset current interval button

The user workflow should be:

```text
1. Move video to desired start time
2. Click Set Start
3. Move video to desired end time
4. Click Set End
5. Optionally enter reason/tags
6. Click Add Cut
7. The cut immediately appears in the cut list and on the timeline
```

Important:

- `Add Cut` must be disabled if start/end are invalid.
- End must be greater than start.
- Show a validation message if the interval is invalid.
- When a cut is added, increment `Cuts: N`.

---

### 4. Cut list area

The cut list must have real visible space.

Current problem: selected cuts are not appearing clearly, which makes debugging impossible.

Create a dedicated bottom panel:

```text
Removal Intervals
```

This panel must show a table/list with:

| # | Start | End | Duration | Reason | Tags | Actions |
|---|-------|-----|----------|--------|------|---------|

Actions:

- Edit
- Delete
- Jump to start
- Preview interval

When a cut is added, it must immediately appear here.

The cut list should not be hidden in a tiny area. It should be large enough to debug the selected intervals.

If the list is empty, show:

```text
No removal intervals selected yet.
Use Set Start and Set End, then click Add Cut.
```

---

### 5. Timeline visualization

Above or inside the cut list area, add a clear removal timeline.

The timeline should show:

- Full video duration as one horizontal bar.
- Selected removal intervals as highlighted red/orange segments.
- Hover tooltip or label with start/end time.

Example behavior:

```text
Video duration: 01:12
Selected cut: 00:33 → 00:42
Timeline should show a highlighted segment from 33s to 42s.
```

This helps verify that the selected cut is the expected one.

---

## Export/remove section

Create a clean export panel, not a messy set of wide buttons.

It should include:

- Output folder display.
- Choose output folder button.
- Main action: `Remove selected intervals`
- Secondary actions:
  - `Export selected clips separately`
  - `Export selected clips merged`

All of these must use **stream copy only**.

Do not show:

```text
Accurate mode
Re-encode
Frame-perfect export
libx264
aac
crf
preset
```

The UI can show this warning:

```text
No-reencode mode uses FFmpeg stream copy. Cuts are fast and quality-preserving, but may align to keyframes.
```

But it must not offer re-encoding as a solution.

---

## Important cutting bug to verify

The selected removal interval was:

```text
00:00:33 → 00:00:42
```

The original video duration was:

```text
00:01:12
```

Expected removed duration:

```text
9 seconds
```

Expected output duration:

```text
01:12 - 00:09 = 01:03
```

But the actual result became around:

```text
01:07
```

So only about 5 seconds were removed, which means the wrong interval was cut or the segment reconstruction logic is incorrect.

Codex must make the cut list visible and add logging/debug information so this can be verified.

---

## Debug requirements

When exporting, show a small debug/status area with:

- Number of intervals.
- Input duration.
- Expected removed duration.
- Expected output duration.
- Actual output duration from ffprobe after export.
- Final FFmpeg command used.
- Export status/errors.

Example:

```text
Input duration: 72.0s
Selected intervals: 1
Interval 1: 33.0s → 42.0s, duration 9.0s
Expected output duration: 63.0s
Actual output duration: 67.0s
WARNING: output duration differs from expected duration.
```

This is necessary because no-reencode cutting can drift due to keyframes, but the app still needs to show what it actually did.

---

## No re-encoding rule

Absolutely remove re-encoding from both UI and backend.

Allowed FFmpeg behavior:

```bash
-c copy
```

Forbidden:

```bash
-c:v libx264
-c:a aac
-crf
-preset
-vf
-af
-filter_complex
```

For merging no-reencode clips, use concat demuxer with stream copy:

```bash
ffmpeg -y -f concat -safe 0 -i concat_list.txt -c copy output.mp4
```

For exporting segments, use stream copy only.

---

## Suggested layout

Use this high-level structure:

```text
Header
└── Open file, filename, subtitle status, settings

Main area
├── Left: Video preview/player
│   └── Embedded overlay controls
│
└── Right: Current Removal Interval panel
    ├── Start / End / Duration
    ├── Reason / Tags
    └── Add Cut / Reset

Bottom area
├── Removal timeline
├── Removal intervals table
└── Export panel + status/debug messages
```

The UI should feel like a clean desktop video tool, not a test dashboard.

---

## QML refactor requirement

Do not keep everything inside `Main.qml`.

Create reusable components, for example:

```text
qml/
├── Main.qml
├── components/
│   ├── AppHeader.qml
│   ├── VideoPlayerPanel.qml
│   ├── VideoControlsOverlay.qml
│   ├── CurrentCutPanel.qml
│   ├── CutTimeline.qml
│   ├── CutListTable.qml
│   ├── ExportPanel.qml
│   ├── StatusLogPanel.qml
│   └── AppButton.qml
```

`Main.qml` should only compose these components.

---

## Acceptance criteria

The task is complete only if:

1. No re-encoding option appears anywhere in the UI.
2. `Accurate mode` is removed.
3. Video controls are embedded inside the video player overlay.
4. User can set start/end using video controls.
5. Added cuts appear immediately in the cut list.
6. Added cuts appear visually on the timeline.
7. Cut count updates correctly.
8. Export buttons are disabled when there are no cuts.
9. The app shows expected output duration vs actual output duration.
10. The interval `00:00:33 → 00:00:42` on a `01:12` video is debuggable and should target a final duration close to `01:03`, acknowledging possible keyframe drift.
11. The backend still uses FFmpeg `-c copy` only.
12. `Main.qml` is split into components.
