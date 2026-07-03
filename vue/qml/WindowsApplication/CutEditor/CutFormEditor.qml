import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

ColumnLayout {
    id: root

    property bool shortMode: false
    property bool headerCollapsed: false
    property bool lightMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property string selectedVideoPath: ""
    property real videoDurationMs: 0
    property var cutPreview: ({ "visible": false })
    property var keyframeInfo: ({
        "valid": false,
        "error": "Mark Start and End to preview Smart Cutting boundaries.",
        "requested_start": 0,
        "requested_end": 0,
        "safe_start": null,
        "safe_end": null,
        "previous_keyframe_start": null,
        "next_keyframe_start": null,
        "previous_keyframe_end": null,
        "next_keyframe_end": null,
        "extra_before": 0,
        "extra_after": 0
    })

    signal cutAdded(var cut)
    signal previewChanged(var preview)
    signal headerExpandRequested()

    spacing: 10

    AppTheme { id: theme }

    function setStartTime(timeText) {
        startInput.text = timeText
        refreshKeyframeInfo()
    }

    function setEndTime(timeText) {
        endInput.text = timeText
        refreshKeyframeInfo()
    }

    function applyRecommendation(startTime, endTime, reason, tags) {
        startInput.text = startTime
        endInput.text = endTime
        reasonInput.text = reason
        tagsInput.text = tags
        refreshKeyframeInfo()
    }

    function clearEditor() {
        startInput.text = "00:00:00"
        endInput.text = "00:00:00"
        reasonInput.text = ""
        tagsInput.text = ""
        resetKeyframeInfo()
        updateCutPreview()
    }

    function parseTimeToMs(value) {
        var parts = value.trim().split(":")
        if (parts.length !== 3) return -1

        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var seconds = Number(parts[2])
        if (!Number.isInteger(hours) || !Number.isInteger(minutes) || !Number.isFinite(seconds)) return -1
        if (hours < 0 || minutes < 0 || minutes > 59 || seconds < 0 || seconds > 59) return -1
        return ((hours * 3600) + (minutes * 60) + seconds) * 1000
    }

    function formatSeconds(seconds) {
        if (seconds === null || seconds === undefined || seconds === "") return "unavailable"
        var safeSeconds = Number(seconds)
        if (!Number.isFinite(safeSeconds)) return "unavailable"
        safeSeconds = Math.max(0, safeSeconds)
        var totalMilliseconds = Math.round(safeSeconds * 1000)
        var totalSeconds = Math.floor(totalMilliseconds / 1000)
        var milliseconds = totalMilliseconds % 1000
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var wholeSeconds = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        function padMillis(value) {
            if (value < 10) return "00" + value
            if (value < 100) return "0" + value
            return "" + value
        }
        var text = pad(hours) + ":" + pad(minutes) + ":" + pad(wholeSeconds)
        if (milliseconds > 0) {
            text += "." + padMillis(milliseconds)
        }
        return text
    }

    function formatDelta(seconds) {
        return (Number(seconds) || 0).toFixed(1) + "s"
    }

    function resetKeyframeInfo(message) {
        root.keyframeInfo = {
            "valid": false,
            "error": message || "Mark Start and End to preview Smart Cutting boundaries.",
            "requested_start": 0,
            "requested_end": 0,
            "safe_start": null,
            "safe_end": null,
            "previous_keyframe_start": null,
            "next_keyframe_start": null,
            "previous_keyframe_end": null,
            "next_keyframe_end": null,
            "extra_before": 0,
            "extra_after": 0
        }
    }

    function updateCutPreview() {
        var startMs = parseTimeToMs(startInput.text)
        var endMs = parseTimeToMs(endInput.text)
        var hasTimes = startMs >= 0 && endMs >= 0 && (startMs !== 0 || endMs !== 0)

        if (!hasTimes) {
            root.cutPreview = { "visible": false }
            root.previewChanged(root.cutPreview)
            return
        }

        var hasSafe = hasSafeKeyframeInfo()
        var validOrder = startMs < endMs
        root.cutPreview = {
            "visible": true,
            "valid": validOrder,
            "has_safe": validOrder && hasSafe,
            "requested_start": startMs / 1000,
            "requested_end": endMs / 1000,
            "safe_start": validOrder && hasSafe ? root.keyframeInfo.safe_start : null,
            "safe_end": validOrder && hasSafe ? root.keyframeInfo.safe_end : null,
            "error": validOrder ? "" : "End time must be after start time."
        }
        root.previewChanged(root.cutPreview)
    }

    function refreshKeyframeInfo() {
        if (!canAddCut()) {
            resetKeyframeInfo(validationMessage())
            updateCutPreview()
            return
        }

        root.keyframeInfo = videoCutController.keyframeCutInfo(
            root.selectedVideoPath,
            startInput.text,
            endInput.text,
            root.videoDurationMs > 0 ? root.videoDurationMs / 1000 : 0
        )
        updateCutPreview()
    }

    function validationMessage() {
        var startMs = parseTimeToMs(startInput.text)
        var endMs = parseTimeToMs(endInput.text)

        if (startMs < 0 || endMs < 0) return "Use HH:MM:SS for start and end."
        if (startMs === 0 && endMs === 0) return ""
        if (startMs >= endMs) return "End time must be after start time."
        return ""
    }

    function canAddCut() {
        var startMs = parseTimeToMs(startInput.text)
        var endMs = parseTimeToMs(endInput.text)
        return startMs >= 0 && endMs >= 0 && startMs < endMs
    }

    function hasSafeKeyframeInfo() {
        var info = root.keyframeInfo
        return info.valid
            && info.safe_start !== null
            && info.safe_end !== null
            && Number.isFinite(Number(info.safe_start))
            && Number.isFinite(Number(info.safe_end))
            && Number(info.safe_start) < Number(info.safe_end)
    }

    function canAddSafeCut() {
        return root.canAddCut() && root.hasSafeKeyframeInfo()
    }

    function addCut(source, score) {
        if (!canAddCut()) return
        refreshKeyframeInfo()
        if (!hasSafeKeyframeInfo()) return
        var info = root.keyframeInfo
        var safeStart = root.formatSeconds(info.safe_start)
        var safeEnd = root.formatSeconds(info.safe_end)
        root.cutAdded({
            "start": startInput.text,
            "end": endInput.text,
            "safeStart": safeStart,
            "safeEnd": safeEnd,
            "requestedStartSeconds": info.requested_start,
            "requestedEndSeconds": info.requested_end,
            "safeStartSeconds": info.safe_start,
            "safeEndSeconds": info.safe_end,
            "previousKeyframeStart": root.formatSeconds(info.previous_keyframe_start),
            "nextKeyframeStart": root.formatSeconds(info.next_keyframe_start),
            "previousKeyframeEnd": root.formatSeconds(info.previous_keyframe_end),
            "nextKeyframeEnd": root.formatSeconds(info.next_keyframe_end),
            "extraBefore": root.formatDelta(info.extra_before),
            "extraAfter": root.formatDelta(info.extra_after),
            "cutType": "Remove",
            "reason": reasonInput.text.length > 0 ? reasonInput.text : "Manual removal",
            "tags": tagsInput.text.length > 0 ? tagsInput.text : "manual",
            "source": source,
            "score": score,
            "status": "Pending"
        })
        root.clearEditor()
    }

    function addCurrentCut() {
        root.addCut("Manual", "--")
    }

    Item {
        Layout.fillWidth: true
        Layout.preferredHeight: root.headerCollapsed ? 52 : 44

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: headerActions.left
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2

            Text {
                text: "CURRENT CUT"
                color: root.accent
                font.pixelSize: 16
                font.bold: true
                font.letterSpacing: 1.0
            }

            Text {
                text: "Mark a removal interval"
                color: root.textMuted
                font.pixelSize: 12
            }
        }

        RowLayout {
            id: headerActions

            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            Rectangle {
                id: manualBadge

                Layout.preferredWidth: 96
                Layout.preferredHeight: 28
                radius: 14
                color: root.lightMode ? "#EFF6FF" : "#12223A"
                border.color: root.lightMode ? "#BFDBFE" : "#284566"

                Text {
                    anchors.centerIn: parent
                    text: "Manual"
                    color: root.lightMode ? "#2563EB" : root.textMuted
                    font.pixelSize: 12
                }
            }

            AppButton {
                id: expandHeaderButton

                visible: root.headerCollapsed
                Layout.preferredWidth: theme.collapsedControlSize
                Layout.preferredHeight: theme.collapsedControlSize
                text: "▼"
                variant: "ghost"
                size: "icon"
                lightMode: root.lightMode
                ToolTip.visible: hovered
                ToolTip.text: "Expand header"
                onClicked: root.headerExpandRequested()
            }
        }
    }

    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: root.lightMode ? theme.lightDivider : "#1F2F4A" }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 50
        spacing: 8
        Text { text: "Start"; color: root.textMain; font.pixelSize: 13; Layout.preferredWidth: 40 }
        AppTextField { id: startInput; Layout.fillWidth: true; lightMode: root.lightMode; placeholderText: "00:00:00"; text: "00:00:00"; onEditingFinished: root.refreshKeyframeInfo() }
        AppButton { text: "Reset"; variant: "ghost"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 58; onClicked: { startInput.text = "00:00:00"; root.refreshKeyframeInfo() } }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 50
        spacing: 8
        Text { text: "End"; color: root.textMain; font.pixelSize: 13; Layout.preferredWidth: 40 }
        AppTextField {
            id: endInput
            Layout.fillWidth: true
            lightMode: root.lightMode
            placeholderText: "00:00:00"
            text: "00:00:00"
            onAccepted: root.addCut("Manual", "--")
            onEditingFinished: root.refreshKeyframeInfo()
        }
        AppButton { text: "Reset"; variant: "ghost"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 58; onClicked: { endInput.text = "00:00:00"; root.refreshKeyframeInfo() } }
    }

    Text {
        Layout.fillWidth: true
        Layout.preferredHeight: 36
        text: root.validationMessage()
        color: root.lightMode ? theme.lightDanger : "#FCA5A5"
        font.pixelSize: 12
        visible: text.length > 0
        wrapMode: Text.WordWrap
    }

    KeyframeCutInfo {
        Layout.fillWidth: true
        valid: root.keyframeInfo.valid
        requestedStart: root.formatSeconds(root.keyframeInfo.requested_start)
        requestedEnd: root.formatSeconds(root.keyframeInfo.requested_end)
        safeStart: root.formatSeconds(root.keyframeInfo.safe_start)
        safeEnd: root.formatSeconds(root.keyframeInfo.safe_end)
        previousKeyframeStart: root.formatSeconds(root.keyframeInfo.previous_keyframe_start)
        nextKeyframeStart: root.formatSeconds(root.keyframeInfo.next_keyframe_start)
        previousKeyframeEnd: root.formatSeconds(root.keyframeInfo.previous_keyframe_end)
        nextKeyframeEnd: root.formatSeconds(root.keyframeInfo.next_keyframe_end)
        extraBefore: root.formatDelta(root.keyframeInfo.extra_before)
        extraAfter: root.formatDelta(root.keyframeInfo.extra_after)
        errorText: root.keyframeInfo.error || "Keyframe data unavailable."
        textMain: root.textMain
        textMuted: root.textMuted
        accent: root.accent
        lightMode: root.lightMode
    }

    Text { text: "Reason"; color: root.textMain; font.pixelSize: 13; Layout.preferredHeight: 24 }

    AppTextArea {
        id: reasonInput
        Layout.fillWidth: true
        Layout.preferredHeight: 48
        lightMode: root.lightMode
        placeholderText: "Reason for this cut..."
    }

    Text { text: "Tags"; color: root.textMain; font.pixelSize: 13; Layout.preferredHeight: 24 }

    AppTextField {
        id: tagsInput
        Layout.fillWidth: true
        Layout.preferredHeight: 48
        lightMode: root.lightMode
        placeholderText: "kissing, romance, nsfw"
        onAccepted: root.addCut("Manual", "--")
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 44
        spacing: 8

        AppButton {
            text: "+ Add Cut"
            accessibilityLabel: "Cut video segment"
            iconSource: Qt.resolvedUrl("../../../../assets/icons/cut.png")
            imageIconSize: 32
            variant: "primary"
            size: "lg"
            lightMode: root.lightMode
            Layout.fillWidth: true
            enabled: root.canAddSafeCut()
            ToolTip.visible: hovered
            ToolTip.text: "Cut"
            onClicked: root.addCut("Manual", "--")
        }

        AppButton {
            text: "Reset"
            variant: "danger"
            size: "md"
            lightMode: root.lightMode
            Layout.preferredWidth: 80
            onClicked: root.clearEditor()
        }
    }
}

