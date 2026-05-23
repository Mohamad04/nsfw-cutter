# Codex Task — Precise QML Layout Dimensions + Keyframe Preview Near Cut Points

## Context

The current NSFW Cutter UI is visually better than before, but it still has layout problems:

- Components are not sized with a clear design system.
- The video player area is too empty and the controls are still too heavy.
- The cut list area has space, but it needs a stricter structure.
- We need a dedicated UI part that shows the **nearest keyframes around the selected cut**, because this app uses **no re-encoding** and cuts may align to keyframes.
- The user needs to see both:
  - The requested interval.
  - The actual keyframe-aligned interval that will be removed.

This task is about **layout precision** and **keyframe visibility**.

---

## Non-negotiable rule

This app must remain **no-reencoding only**.

Allowed:

```bash
-c copy
```

Forbidden everywhere:

```bash
-c:v libx264
-c:a aac
-crf
-preset
-filter_complex
-vf
-af
accurate mode
reencode mode
```

Do not add any re-encoding option to solve keyframe drift.

---

# 1. Target window and layout system

Design for a default desktop window of:

```text
Width: 1600 px
Height: 900 px
```

Minimum supported window:

```text
Width: 1280 px
Height: 720 px
```

Use QML `Layout.preferredWidth`, `Layout.preferredHeight`, `Layout.minimumWidth`, `Layout.minimumHeight`, `Layout.fillWidth`, and `Layout.fillHeight`.

Avoid hardcoding everything with absolute anchors only. The UI should resize cleanly.

---

# 2. Global spacing / design tokens

Create reusable constants, for example in `Theme.qml` or `AppTheme.qml`:

```qml
readonly property int windowMargin: 14
readonly property int panelRadius: 16
readonly property int panelPadding: 14
readonly property int sectionGap: 12
readonly property int controlHeight: 38
readonly property int smallButtonHeight: 34
readonly property int headerHeight: 72
readonly property int rightPanelWidth: 330
readonly property int bottomPanelHeight: 390
readonly property int timelineHeight: 70
readonly property int cutTableHeight: 150
readonly property int exportPanelHeight: 110
readonly property int statusLogHeight: 80
```

Recommended colors should stay close to the current dark theme, but keep the hierarchy clear.

---

# 3. Main window structure

`Main.qml` should mostly compose components.

Recommended structure:

```text
ApplicationWindow 1600x900
└── Root ColumnLayout
    ├── AppHeader              height: 72
    ├── Main Work Area         height: fills available top area
    │   ├── VideoPlayerPanel   fills width except right panel
    │   └── CurrentCutPanel    width: 330
    └── BottomCutWorkspace     height: 390
        ├── CutTimelinePanel
        ├── CutListTable
        ├── ExportPanel
        └── StatusLogPanel
```

Recommended QML dimensions:

```qml
ApplicationWindow {
    width: 1600
    height: 900
    minimumWidth: 1280
    minimumHeight: 720
}
```

Root layout:

```qml
ColumnLayout {
    anchors.fill: parent
    anchors.margins: 14
    spacing: 12
}
```

---

# 4. Header component dimensions

File:

```text
qml/components/AppHeader.qml
```

Recommended size:

```qml
Layout.fillWidth: true
Layout.preferredHeight: 72
Layout.minimumHeight: 64
Layout.maximumHeight: 80
```

Internal items:

| Item | Width | Height |
|---|---:|---:|
| Logo square | 42 | 42 |
| App title | 150 | 42 |
| Folder button | 110 | 42 |
| Clear button | 96 | 42 |
| Filename field | fill | 42 |
| Subtitle status | 250 | 42 |
| Video loaded badge | 150 | 38 |
| Gear button | 52 | 52 |

Header should never grow vertically.

---

# 5. Main work area dimensions

File:

```text
qml/components/MainWorkArea.qml
```

Recommended:

```qml
RowLayout {
    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 330
    Layout.preferredHeight: 390
    spacing: 12
}
```

Contains:

```text
VideoPlayerPanel    Layout.fillWidth: true
CurrentCutPanel     Layout.preferredWidth: 330
```

---

# 6. Video player panel dimensions

File:

```text
qml/components/VideoPlayerPanel.qml
```

Recommended panel:

```qml
Layout.fillWidth: true
Layout.fillHeight: true
Layout.minimumHeight: 320
```

The video surface should fill almost all of this component.

Video surface:

```qml
Rectangle {
    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 290
    radius: 14
}
```

## Embedded video controls overlay

File:

```text
qml/components/VideoControlsOverlay.qml
```

The controls must be inside the video player at the bottom.

Recommended overlay:

```qml
height: 118
anchors.left: parent.left
anchors.right: parent.right
anchors.bottom: parent.bottom
anchors.margins: 12
radius: 14
opacity: 0.96
```

The overlay should contain two rows:

### Row 1: timeline row

Height:

```qml
height: 34
```

Items:

| Item | Width | Height |
|---|---:|---:|
| Current time label | 82 | 28 |
| Seek slider | fill | 28 |
| Duration label | 82 | 28 |

### Row 2: controls row

Height:

```qml
height: 48
```

Buttons:

| Button | Width | Height |
|---|---:|---:|
| -60 | 80 | 34 |
| -15 | 80 | 34 |
| -5 | 80 | 34 |
| Play/Pause | 110 | 38 |
| +5 | 80 | 34 |
| +15 | 80 | 34 |
| +60 | 80 | 34 |
| Set Start | 84 | 34 |
| Set End | 84 | 34 |
| + Add Cut | 110 | 34 |
| Volume label/icon | 34 | 34 |
| Volume slider | 160 | 28 |

Do not make skip buttons huge. They should be compact.

---

# 7. Current cut panel dimensions

File:

```text
qml/components/CurrentCutPanel.qml
```

Recommended:

```qml
Layout.preferredWidth: 330
Layout.minimumWidth: 300
Layout.maximumWidth: 360
Layout.fillHeight: true
```

Content:

| Element | Height |
|---|---:|
| Title + mode badge | 40 |
| Divider | 1 |
| Start row | 46 |
| End row | 46 |
| Duration / validation row | 34 |
| Reason label | 22 |
| Reason text field | 44 |
| Tags label | 22 |
| Tags text field | 44 |
| Keyframe info mini-card | 120 |
| Add / Reset buttons | 42 |

The panel should scroll only if the window height is too small, but at 1600x900 everything should fit without needing a scrollbar.

---

# 8. Keyframe info near selected cut

Add a dedicated component:

```text
qml/components/KeyframeCutInfo.qml
```

Place it inside the `CurrentCutPanel`, directly below Start/End/Duration.

Recommended size:

```qml
Layout.fillWidth: true
Layout.preferredHeight: 120
Layout.minimumHeight: 100
```

## Purpose

When the user selects:

```text
Requested removal: 00:00:33 → 00:00:42
```

The app should display nearest keyframes:

```text
Previous keyframe before start: 00:00:32
Next keyframe after start:      00:00:34
Previous keyframe before end:   00:00:40
Next keyframe after end:        00:00:44
```

Then show the safe no-reencode removal interval:

```text
Actually removed without re-encoding:
00:00:32 → 00:00:44
```

## UI content

The keyframe info card should show:

```text
Keyframe-aligned removal
Requested: 00:00:33 → 00:00:42
Safe cut:  00:00:32 → 00:00:44
Extra removed: -1.0s before, +2.0s after
```

Use a small warning text:

```text
No-reencoding mode cuts on/near keyframes.
```

## Visual requirement

Use two different visual indicators:

- Requested interval: blue/cyan.
- Keyframe-aligned interval: orange/red.

Do not make this a giant block. It should be compact and always visible when start/end are valid.

---

# 9. Bottom cut workspace dimensions

File:

```text
qml/components/BottomCutWorkspace.qml
```

Recommended:

```qml
Layout.fillWidth: true
Layout.preferredHeight: 390
Layout.minimumHeight: 320
Layout.maximumHeight: 430
```

Internal layout:

```text
Top row: title/actions
Timeline panel
Cut list table
Export panel
Status/debug panel
```

Suggested heights:

| Section | Height |
|---|---:|
| Header row | 42 |
| Removal timeline | 70 |
| Cut list table | 150 |
| Export panel | 80 |
| Status/debug panel | 48 |

If the window is taller, the cut list table can expand.

---

# 10. Cut timeline panel dimensions

File:

```text
qml/components/CutTimeline.qml
```

Recommended:

```qml
Layout.fillWidth: true
Layout.preferredHeight: 70
Layout.minimumHeight: 60
```

Content:

- One horizontal full-duration bar.
- Requested intervals shown in blue/cyan.
- Keyframe-aligned removal intervals shown in red/orange.
- Current playhead as a thin vertical line.
- Tooltip/label on hover or selected interval.

Example:

```text
Full video: 00:00:00 → 00:01:12
Requested: 00:00:33 → 00:00:42
Safe cut:  00:00:32 → 00:00:44
```

The timeline must help the user see that the actual no-reencode removal may be bigger than the requested interval.

---

# 11. Cut list table dimensions

File:

```text
qml/components/CutListTable.qml
```

Recommended:

```qml
Layout.fillWidth: true
Layout.preferredHeight: 150
Layout.minimumHeight: 120
```

Columns:

| Column | Width |
|---|---:|
| # | 40 |
| Requested Start | 110 |
| Requested End | 110 |
| Safe Start | 110 |
| Safe End | 110 |
| Removed Duration | 120 |
| Extra Removed | 130 |
| Reason | fill |
| Actions | 190 |

Actions:

- Jump
- Edit
- Delete

Each row height:

```qml
rowHeight: 36
```

Empty state:

```text
No removal intervals selected yet.
Mark Start and End, then Add Cut.
```

---

# 12. Export panel dimensions

File:

```text
qml/components/ExportPanel.qml
```

Recommended:

```qml
Layout.fillWidth: true
Layout.preferredHeight: 80
Layout.minimumHeight: 70
```

Content:

| Element | Width | Height |
|---|---:|---:|
| Output folder field | fill | 36 |
| Folder button | 80 | 36 |
| Remove selected intervals | 250 | 38 |
| Export selected clips | 250 | 38 |
| Export clips merged | 250 | 38 |

Warning text:

```text
No re-encoding: fast and quality-preserving, but cuts may align to nearby keyframes.
```

Remove the UI if no cuts exist:

- Buttons should be disabled.
- Do not show confusing disabled colors that look like errors.

---

# 13. Status/debug panel dimensions

File:

```text
qml/components/StatusLogPanel.qml
```

Recommended:

```qml
Layout.fillWidth: true
Layout.preferredHeight: 48
Layout.minimumHeight: 44
```

For expanded debug mode, allow height:

```qml
Layout.preferredHeight: 90
```

Should show:

```text
Input duration: 72.0s | Requested removed: 9.0s | Safe removed: 12.0s | Expected output: 60.0s | Actual output: ...
```

Also show FFmpeg command only in expanded debug/details mode, not always visible.

---

# 14. Backend keyframe extraction

Add/verify service:

```text
app/services/keyframe_service.py
```

Use ffprobe:

```bash
ffprobe -v error -select_streams v:0 -skip_frame nokey -show_entries frame=best_effort_timestamp_time -of json input.mp4
```

Return:

```python
list[float]
```

Example:

```python
[0.0, 2.0, 4.0, 6.0, 8.0, 10.0, ...]
```

---

# 15. Data model for cuts

Each cut should store both requested and safe keyframe-aligned values.

Example Pydantic model:

```python
class RemovalInterval(BaseModel):
    id: str
    requested_start: float
    requested_end: float
    safe_start: float
    safe_end: float
    previous_keyframe_start: float | None = None
    next_keyframe_start: float | None = None
    previous_keyframe_end: float | None = None
    next_keyframe_end: float | None = None
    reason: str | None = None
    tags: list[str] = []
```

The UI should never only display the requested interval. It must also display the safe interval used for no-reencoding export.

---

# 16. Safe keyframe alignment logic

For NSFW removal, prefer safety over exact preservation.

Given:

```text
requested_start = 33.0
requested_end   = 42.0
```

Use:

```text
safe_start = previous keyframe <= requested_start
safe_end   = next keyframe >= requested_end
```

This ensures the no-reencode removal interval fully covers the requested NSFW segment.

Optional safety padding before keyframe alignment:

```python
padded_start = max(0, requested_start - safety_padding_before)
padded_end = min(video_duration, requested_end + safety_padding_after)
safe_start = previous_keyframe(padded_start)
safe_end = next_keyframe(padded_end)
```

Default padding:

```text
0.5 seconds before
0.5 seconds after
```

Make padding configurable later in settings, but start with a constant.

---

# 17. UX behavior

When user clicks `Set Start`:

- Save requested start.
- Look up previous/next keyframes around start.
- Update `KeyframeCutInfo`.

When user clicks `Set End`:

- Save requested end.
- Look up previous/next keyframes around end.
- Compute safe interval.
- Update `KeyframeCutInfo`.

When user clicks `Add Cut`:

- Add the interval with both requested and safe values.
- Display it immediately in the cut list.
- Display both requested and safe intervals on the timeline.
- Increment `Cuts: N`.

When exporting:

- Use safe intervals, not only requested intervals.
- Show debug values:
  - requested removed duration
  - safe removed duration
  - expected output duration
  - actual output duration from ffprobe

---

# 18. Acceptance criteria

This task is complete only if:

1. The UI uses the dimensions listed above or very close equivalents.
2. The layout looks professional at 1600x900.
3. The layout remains usable at 1280x720.
4. `Main.qml` remains mostly a composition file.
5. Video controls are embedded inside the video player.
6. The right current cut panel has a keyframe info card.
7. The timeline shows requested intervals and keyframe-aligned safe intervals.
8. The cut list table shows requested start/end and safe start/end.
9. Export uses safe keyframe-aligned intervals.
10. The app uses `-c copy` only.
11. There is no accurate/reencode mode anywhere.
12. The user can debug why a 33s→42s requested cut may remove 32s→44s.
