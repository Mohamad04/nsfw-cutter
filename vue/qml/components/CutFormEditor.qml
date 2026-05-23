import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root

    property bool shortMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property string selectedVideoPath: ""
    property real videoDurationMs: 0
    property var keyframeInfo: ({
        "valid": false,
        "error": "Mark Start and End to preview keyframe-safe removal.",
        "requested_start": 0,
        "requested_end": 0,
        "safe_start": 0,
        "safe_end": 0,
        "previous_keyframe_start": 0,
        "next_keyframe_start": 0,
        "previous_keyframe_end": 0,
        "next_keyframe_end": 0,
        "extra_before": 0,
        "extra_after": 0
    })

    signal cutAdded(var cut)

    spacing: 10

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
    }

    function parseTimeToMs(value) {
        var parts = value.trim().split(":")
        if (parts.length !== 3) return -1

        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var seconds = Number(parts[2])
        if (!Number.isInteger(hours) || !Number.isInteger(minutes) || !Number.isInteger(seconds)) return -1
        if (hours < 0 || minutes < 0 || minutes > 59 || seconds < 0 || seconds > 59) return -1
        return ((hours * 3600) + (minutes * 60) + seconds) * 1000
    }

    function formatSeconds(seconds) {
        var safeSeconds = Math.max(0, Number(seconds) || 0)
        var totalSeconds = Math.floor(safeSeconds)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var wholeSeconds = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(wholeSeconds)
    }

    function formatDelta(seconds) {
        return (Number(seconds) || 0).toFixed(1) + "s"
    }

    function resetKeyframeInfo(message) {
        root.keyframeInfo = {
            "valid": false,
            "error": message || "Mark Start and End to preview keyframe-safe removal.",
            "requested_start": 0,
            "requested_end": 0,
            "safe_start": 0,
            "safe_end": 0,
            "previous_keyframe_start": 0,
            "next_keyframe_start": 0,
            "previous_keyframe_end": 0,
            "next_keyframe_end": 0,
            "extra_before": 0,
            "extra_after": 0
        }
    }

    function refreshKeyframeInfo() {
        if (!canAddCut()) {
            resetKeyframeInfo(validationMessage())
            return
        }

        root.keyframeInfo = videoCutController.keyframeCutInfo(
            root.selectedVideoPath,
            startInput.text,
            endInput.text,
            root.videoDurationMs > 0 ? root.videoDurationMs / 1000 : 0
        )
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

    function addCut(source, score) {
        if (!canAddCut()) return
        refreshKeyframeInfo()
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
    }

    function addCurrentCut() {
        root.addCut("Manual", "--")
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 44

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            Text {
                text: "CURRENT CUT"
                color: root.accent
                font.pixelSize: 15
                font.bold: true
                font.letterSpacing: 0.6
            }

            Text {
                text: "Mark a removal interval"
                color: root.textMuted
                font.pixelSize: 12
            }
        }

        Rectangle {
            Layout.preferredHeight: 28
            Layout.preferredWidth: 78
            radius: 14
            color: "#12223A"
            border.color: "#284566"

            Text {
                anchors.centerIn: parent
                text: "Manual"
                color: root.textMuted
                font.pixelSize: 12
            }
        }
    }

    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#1F2F4A" }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 50
        spacing: 8
        Text { text: "Start"; color: root.textMain; font.pixelSize: 12; Layout.preferredWidth: 40 }
        AppTextField { id: startInput; Layout.fillWidth: true; placeholderText: "00:00:00"; text: "00:00:00"; onEditingFinished: root.refreshKeyframeInfo() }
        AppButton { text: "Reset"; variant: "ghost"; size: "sm"; Layout.preferredWidth: 58; onClicked: { startInput.text = "00:00:00"; root.refreshKeyframeInfo() } }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 50
        spacing: 8
        Text { text: "End"; color: root.textMain; font.pixelSize: 12; Layout.preferredWidth: 40 }
        AppTextField {
            id: endInput
            Layout.fillWidth: true
            placeholderText: "00:00:00"
            text: "00:00:00"
            onAccepted: root.addCut("Manual", "--")
            onEditingFinished: root.refreshKeyframeInfo()
        }
        AppButton { text: "Reset"; variant: "ghost"; size: "sm"; Layout.preferredWidth: 58; onClicked: { endInput.text = "00:00:00"; root.refreshKeyframeInfo() } }
    }

    Text {
        Layout.fillWidth: true
        Layout.preferredHeight: 36
        text: root.validationMessage()
        color: "#FCA5A5"
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
    }

    Text { text: "Reason"; color: root.textMain; font.pixelSize: 12; Layout.preferredHeight: 24 }

    AppTextArea {
        id: reasonInput
        Layout.fillWidth: true
        Layout.preferredHeight: 48
        placeholderText: "Reason for this cut..."
    }

    Text { text: "Tags"; color: root.textMain; font.pixelSize: 12; Layout.preferredHeight: 24 }

    AppTextField {
        id: tagsInput
        Layout.fillWidth: true
        Layout.preferredHeight: 48
        placeholderText: "kissing, romance, nsfw"
        onAccepted: root.addCut("Manual", "--")
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 44
        spacing: 8

        AppButton {
            text: "+ Add Cut"
            variant: "primary"
            size: "lg"
            Layout.fillWidth: true
            enabled: root.canAddCut()
            onClicked: root.addCut("Manual", "--")
        }

        AppButton {
            text: "Reset"
            variant: "danger"
            size: "md"
            Layout.preferredWidth: 80
            onClicked: root.clearEditor()
        }
    }
}
