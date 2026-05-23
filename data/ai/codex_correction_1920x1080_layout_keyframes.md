# Codex Correction — Default Window Must Be 1920x1080

## Context

The previous UI layout spec used `1600x900` as the default target window size. That is incorrect.

The app should be designed by default for:

```text
1920 px width
1080 px height
```

The UI must still remain usable on smaller screens, but the main design target is now **Full HD 1920x1080**.

---

## Required window sizes

Update `ApplicationWindow`:

```qml
ApplicationWindow {
    width: 1920
    height: 1080

    minimumWidth: 1280
    minimumHeight: 720
}
```

Default layout target:

```text
Default: 1920x1080
Minimum: 1280x720
```

---

# Updated global layout values

Update the design tokens to use these values:

```qml
readonly property int windowMargin: 16
readonly property int panelRadius: 16
readonly property int panelPadding: 16
readonly property int sectionGap: 14

readonly property int headerHeight: 76
readonly property int rightPanelWidth: 380
readonly property int bottomPanelHeight: 430

readonly property int videoControlsOverlayHeight: 124
readonly property int timelineHeight: 84
readonly property int cutTableHeight: 190
readonly property int exportPanelHeight: 92
readonly property int statusLogHeight: 58

readonly property int controlHeight: 40
readonly property int smallButtonHeight: 36
readonly property int buttonRadius: 12
```

The interface should not look stretched. Use the extra space to make the video preview and cut list more readable.

---

# Updated main structure for 1920x1080

Recommended structure:

```text
ApplicationWindow 1920x1080
└── Root ColumnLayout
    ├── AppHeader              height: 76
    ├── Main Work Area         height: fills remaining top space
    │   ├── VideoPlayerPanel   fills width
    │   └── CurrentCutPanel    width: 380
    └── BottomCutWorkspace     height: 430
        ├── CutTimelinePanel   height: 84
        ├── CutListTable       height: 190
        ├── ExportPanel        height: 92
        └── StatusLogPanel     height: 58
```

Root layout:

```qml
ColumnLayout {
    anchors.fill: parent
    anchors.margins: 16
    spacing: 14
}
```

---

# Updated header dimensions

`qml/components/AppHeader.qml`

```qml
Layout.fillWidth: true
Layout.preferredHeight: 76
Layout.minimumHeight: 70
Layout.maximumHeight: 84
```

Internal items:

| Item | Width | Height |
|---|---:|---:|
| Logo square | 46 | 46 |
| App title | 170 | 46 |
| Folder button | 130 | 46 |
| Clear button | 110 | 46 |
| Filename field | fill | 46 |
| Subtitle status | 290 | 46 |
| Video loaded badge | 165 | 40 |
| Gear button | 56 | 56 |

---

# Updated main work area

`qml/components/MainWorkArea.qml`

```qml
RowLayout {
    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 400
    Layout.preferredHeight: 520
    spacing: 14
}
```

Children:

```text
VideoPlayerPanel    Layout.fillWidth: true
CurrentCutPanel     Layout.preferredWidth: 380
```

---

# Updated video player panel

`qml/components/VideoPlayerPanel.qml`

```qml
Layout.fillWidth: true
Layout.fillHeight: true
Layout.minimumHeight: 400
```

Video surface:

```qml
Rectangle {
    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 360
    radius: 16
}
```

The video preview should be the largest visual element in the app.

---

# Updated embedded video controls overlay

`qml/components/VideoControlsOverlay.qml`

Controls must stay inside the video player at the bottom.

```qml
height: 124
anchors.left: parent.left
anchors.right: parent.right
anchors.bottom: parent.bottom
anchors.margins: 14
radius: 16
opacity: 0.96
```

Row 1: timeline row

```qml
height: 36
```

| Item | Width | Height |
|---|---:|---:|
| Current time label | 90 | 30 |
| Seek slider | fill | 30 |
| Duration label | 90 | 30 |

Row 2: controls row

```qml
height: 52
```

| Button | Width | Height |
|---|---:|---:|
| -60 | 92 | 36 |
| -15 | 92 | 36 |
| -5 | 92 | 36 |
| Play/Pause | 124 | 40 |
| +5 | 92 | 36 |
| +15 | 92 | 36 |
| +60 | 92 | 36 |
| Set Start | 96 | 36 |
| Set End | 96 | 36 |
| + Add Cut | 128 | 36 |
| Volume label/icon | 36 | 36 |
| Volume slider | 190 | 30 |

---

# Updated current cut panel

`qml/components/CurrentCutPanel.qml`

```qml
Layout.preferredWidth: 380
Layout.minimumWidth: 340
Layout.maximumWidth: 420
Layout.fillHeight: true
```

Content heights:

| Element | Height |
|---|---:|
| Title + mode badge | 44 |
| Divider | 1 |
| Start row | 50 |
| End row | 50 |
| Duration / validation row | 36 |
| Reason label | 24 |
| Reason text field | 48 |
| Tags label | 24 |
| Tags text field | 48 |
| Keyframe info mini-card | 140 |
| Add / Reset buttons | 44 |

At `1920x1080`, this panel should fit without scrolling.

---

# Updated KeyframeCutInfo component

`qml/components/KeyframeCutInfo.qml`

```qml
Layout.fillWidth: true
Layout.preferredHeight: 140
Layout.minimumHeight: 120
```

This component must show:

```text
Requested: 00:00:33 → 00:00:42
Safe cut:  00:00:32 → 00:00:44
Extra removed: -1.0s before, +2.0s after
```

Also show nearby keyframes:

```text
Start keyframes: prev 00:00:32 | next 00:00:34
End keyframes:   prev 00:00:40 | next 00:00:44
```

The safe keyframe-aligned interval must be clearly visible because export uses it.

---

# Updated bottom cut workspace

`qml/components/BottomCutWorkspace.qml`

```qml
Layout.fillWidth: true
Layout.preferredHeight: 430
Layout.minimumHeight: 340
Layout.maximumHeight: 480
```

Internal sections:

| Section | Height |
|---|---:|
| Header row | 44 |
| Removal timeline | 84 |
| Cut list table | 190 |
| Export panel | 92 |
| Status/debug panel | 58 |

---

# Updated CutTimeline

`qml/components/CutTimeline.qml`

```qml
Layout.fillWidth: true
Layout.preferredHeight: 84
Layout.minimumHeight: 70
```

Must show:

- Full video duration.
- Requested interval in blue/cyan.
- Safe keyframe-aligned interval in orange/red.
- Current playhead.
- Tooltip or label for selected intervals.

---

# Updated CutListTable

`qml/components/CutListTable.qml`

```qml
Layout.fillWidth: true
Layout.preferredHeight: 190
Layout.minimumHeight: 140
```

Columns:

| Column | Width |
|---|---:|
| # | 44 |
| Requested Start | 125 |
| Requested End | 125 |
| Safe Start | 125 |
| Safe End | 125 |
| Removed Duration | 135 |
| Extra Removed | 150 |
| Reason | fill |
| Actions | 220 |

Row height:

```qml
rowHeight: 38
```

The cut list must be large enough to show several intervals without looking empty or cramped.

---

# Updated ExportPanel

`qml/components/ExportPanel.qml`

```qml
Layout.fillWidth: true
Layout.preferredHeight: 92
Layout.minimumHeight: 80
```

Content:

| Element | Width | Height |
|---|---:|---:|
| Output folder field | fill | 38 |
| Folder button | 90 | 38 |
| Remove selected intervals | 300 | 40 |
| Export selected clips | 300 | 40 |
| Export clips merged | 300 | 40 |

Warning text:

```text
No re-encoding: fast and quality-preserving, but cuts may align to nearby keyframes.
```

---

# Updated StatusLogPanel

`qml/components/StatusLogPanel.qml`

```qml
Layout.fillWidth: true
Layout.preferredHeight: 58
Layout.minimumHeight: 48
```

Collapsed status should show:

```text
Input: 72.0s | Requested removed: 9.0s | Safe removed: 12.0s | Expected output: 60.0s | Actual output: ...
```

Expanded debug mode can grow to:

```qml
Layout.preferredHeight: 100
```

---

# Keyframe requirement reminder

The UI must include a part near the selected cut that shows keyframes.

For every selected cut, store and display:

```text
requested_start
requested_end
safe_start
safe_end
previous_keyframe_start
next_keyframe_start
previous_keyframe_end
next_keyframe_end
```

For NSFW removal:

```text
safe_start = previous keyframe <= requested_start
safe_end   = next keyframe >= requested_end
```

Export must use the safe values, not only the requested values.

---

# Acceptance criteria update

The task is complete only if:

1. Default app window is `1920x1080`.
2. Minimum window remains `1280x720`.
3. Component dimensions are updated according to this file.
4. The UI looks professional on a Full HD screen.
5. The extra screen space is used for the video preview, cut list, and keyframe info.
6. The keyframe info card is visible near the current cut controls.
7. Cut list shows both requested interval and safe keyframe-aligned interval.
8. Export still uses `-c copy` only.
9. No re-encoding / accurate mode appears anywhere.
