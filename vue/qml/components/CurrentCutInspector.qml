import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    required property var cutsModel
    property bool compactMode: false
    property bool lightMode: false
    property bool shortMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#2F7BFF"
    property string selectedVideoPath: ""
    property real videoDurationMs: 0
    property int selectedCutIndex: -1
    property var cutPreview: ({ "visible": false })
    property var keyframeInfo: ({
        "valid": false,
        "error": "Set Start and Set End to preview the safe removal.",
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
    readonly property int cutCount: root.cutsModel ? root.cutsModel.count : 0
    readonly property color requestedColor: root.lightMode ? theme.lightCutRequested : theme.darkCutRequested
    readonly property color safeColor: root.lightMode ? theme.lightCutSafe : theme.darkCutSafe

    signal cutAdded(var cut)
    signal previewChanged(var preview)
    signal selectedCutRequested(int index)

    radius: 18
    color: root.lightMode ? theme.lightSurface : theme.darkSurface
    border.color: root.lightMode ? theme.lightBorder : theme.darkBorder
    clip: true

    AppTheme { id: theme }

    function selectedCut() {
        if (!root.cutsModel || root.selectedCutIndex < 0 || root.selectedCutIndex >= root.cutsModel.count) return null
        return root.cutsModel.get(root.selectedCutIndex)
    }

    function parseTimeToMs(value) {
        var parts = String(value).trim().split(":")
        if (parts.length !== 3) return -1
        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var seconds = Number(parts[2])
        if (!Number.isInteger(hours) || !Number.isInteger(minutes) || !Number.isFinite(seconds)) return -1
        if (hours < 0 || minutes < 0 || minutes > 59 || seconds < 0 || seconds >= 60) return -1
        return ((hours * 3600) + (minutes * 60) + seconds) * 1000
    }

    function parseSeconds(value) {
        var ms = root.parseTimeToMs(value)
        return ms < 0 ? 0 : ms / 1000
    }

    function numericOrFallback(value, fallback) {
        if (value === undefined || value === null || value === "") return fallback
        var numberValue = Number(value)
        return Number.isFinite(numberValue) ? numberValue : fallback
    }

    function formatSeconds(seconds) {
        if (seconds === null || seconds === undefined || seconds === "") return ""
        var safeSeconds = Number(seconds)
        if (!Number.isFinite(safeSeconds)) return ""
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
        if (milliseconds > 0) text += "." + padMillis(milliseconds)
        return text
    }

    function formatDelta(seconds) {
        var value = Number(seconds) || 0
        return value.toFixed(1) + "s"
    }

    function formatDeltaSigned(seconds) {
        var value = Number(seconds) || 0
        var prefix = value > 0 ? "+" : ""
        return prefix + value.toFixed(1) + "s"
    }

    function formatClockDuration(seconds) {
        var value = Math.max(0, Math.round(Number(seconds) || 0))
        var hours = Math.floor(value / 3600)
        var minutes = Math.floor((value % 3600) / 60)
        var wholeSeconds = value % 60
        function pad(numberValue) { return numberValue < 10 ? "0" + numberValue : "" + numberValue }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(wholeSeconds)
    }

    function formatSignedClockDelta(seconds) {
        var value = Number(seconds) || 0
        var prefix = value > 0 ? "+" : (value < 0 ? "-" : "")
        return prefix + root.formatClockDuration(Math.abs(value))
    }

    function formatDuration(startSeconds, endSeconds) {
        var startValue = Number(startSeconds)
        var endValue = Number(endSeconds)
        if (!Number.isFinite(startValue) || !Number.isFinite(endValue) || endValue < startValue) return "--"
        return root.formatClockDuration(endValue - startValue)
    }

    function showOptionalDetails() {
        return root.selectedCutIndex >= 0
            || root.canAddCut()
            || reasonInput.text.length > 0
            || tagsInput.text.length > 0
    }

    function resetKeyframeInfo(message) {
        root.keyframeInfo = {
            "valid": false,
            "error": message || "Set Start and Set End to preview the safe removal.",
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

    function validationMessage() {
        var startMs = root.parseTimeToMs(startInput.text)
        var endMs = root.parseTimeToMs(endInput.text)
        if (startMs < 0 || endMs < 0) return "Use HH:MM:SS for start and end."
        if (startMs === 0 && endMs === 0) return ""
        if (startMs >= endMs) return "End time must be after start time."
        if (root.selectedVideoPath.length === 0) return "Load a video before adding a stream-copy cut."
        return ""
    }

    function canAddCut() {
        var startMs = root.parseTimeToMs(startInput.text)
        var endMs = root.parseTimeToMs(endInput.text)
        return startMs >= 0 && endMs >= 0 && startMs < endMs && root.selectedVideoPath.length > 0
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

    function updateCutPreview() {
        var startMs = root.parseTimeToMs(startInput.text)
        var endMs = root.parseTimeToMs(endInput.text)
        var hasTimes = startMs >= 0 && endMs >= 0 && (startMs !== 0 || endMs !== 0)
        if (!hasTimes) {
            root.cutPreview = { "visible": false }
            root.previewChanged(root.cutPreview)
            return
        }
        var validOrder = startMs < endMs
        var hasSafe = root.hasSafeKeyframeInfo()
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
        if (!root.canAddCut()) {
            root.resetKeyframeInfo(root.validationMessage())
            root.updateCutPreview()
            return
        }
        root.keyframeInfo = videoCutController.keyframeCutInfo(
            root.selectedVideoPath,
            startInput.text,
            endInput.text,
            root.videoDurationMs > 0 ? root.videoDurationMs / 1000 : 0
        )
        root.updateCutPreview()
    }

    function loadSelectedCut() {
        var cut = root.selectedCut()
        if (cut === null) return

        startInput.text = cut.start || "00:00:00"
        endInput.text = cut.end || "00:00:00"
        reasonInput.text = cut.reason || ""
        tagsInput.text = cut.tags || ""

        var requestedStart = root.numericOrFallback(cut.requestedStartSeconds, root.parseSeconds(startInput.text))
        var requestedEnd = root.numericOrFallback(cut.requestedEndSeconds, root.parseSeconds(endInput.text))
        var safeStart = root.numericOrFallback(cut.safeStartSeconds, root.parseSeconds(cut.safeStart || startInput.text))
        var safeEnd = root.numericOrFallback(cut.safeEndSeconds, root.parseSeconds(cut.safeEnd || endInput.text))
        var hasStoredSafe = cut.safeAvailable === true
            || String(cut.safeAvailable) === "true"
            || (String(cut.safeStart || "").length > 0 && String(cut.safeEnd || "").length > 0)
        var safeAvailable = hasStoredSafe && Number.isFinite(safeStart) && Number.isFinite(safeEnd) && safeStart < safeEnd

        root.keyframeInfo = {
            "valid": safeAvailable,
            "error": safeAvailable ? "" : "Safe keyframes unavailable for this cut.",
            "requested_start": requestedStart,
            "requested_end": requestedEnd,
            "safe_start": safeAvailable ? safeStart : null,
            "safe_end": safeAvailable ? safeEnd : null,
            "previous_keyframe_start": root.numericOrFallback(cut.previousKeyframeStart, null),
            "next_keyframe_start": root.numericOrFallback(cut.nextKeyframeStart, null),
            "previous_keyframe_end": root.numericOrFallback(cut.previousKeyframeEnd, null),
            "next_keyframe_end": root.numericOrFallback(cut.nextKeyframeEnd, null),
            "extra_before": Math.max(0, requestedStart - safeStart),
            "extra_after": Math.max(0, safeEnd - requestedEnd)
        }
        root.updateCutPreview()
    }

    function setStartTime(timeText) {
        if (root.selectedCutIndex >= 0) root.selectedCutRequested(-1)
        startInput.text = timeText
        root.refreshKeyframeInfo()
    }

    function setEndTime(timeText) {
        if (root.selectedCutIndex >= 0) root.selectedCutRequested(-1)
        endInput.text = timeText
        root.refreshKeyframeInfo()
    }

    function applyRecommendation(startTime, endTime, reason, tags) {
        if (root.selectedCutIndex >= 0) root.selectedCutRequested(-1)
        startInput.text = startTime
        endInput.text = endTime
        reasonInput.text = reason
        tagsInput.text = tags
        root.refreshKeyframeInfo()
    }

    function clearEditor(clearSelection) {
        startInput.text = "00:00:00"
        endInput.text = "00:00:00"
        reasonInput.text = ""
        tagsInput.text = ""
        if (clearSelection === undefined || clearSelection === true) root.selectedCutRequested(-1)
        root.resetKeyframeInfo()
        root.updateCutPreview()
    }

    function addCut(source, score) {
        if (!root.canAddCut()) return
        root.refreshKeyframeInfo()
        if (!root.hasSafeKeyframeInfo()) return
        var info = root.keyframeInfo
        root.cutAdded({
            "start": startInput.text,
            "end": endInput.text,
            "safeStart": root.formatSeconds(info.safe_start),
            "safeEnd": root.formatSeconds(info.safe_end),
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
        root.clearEditor(false)
    }

    function addCurrentCut() {
        root.addCut("Manual", "--")
    }

    onSelectedCutIndexChanged: Qt.callLater(root.loadSelectedCut)
    onSelectedVideoPathChanged: Qt.callLater(root.refreshKeyframeInfo)
    Component.onCompleted: root.refreshKeyframeInfo()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.compactMode ? 12 : 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 42
            spacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 1

                Text {
                    Layout.fillWidth: true
                    text: "CURRENT CUT"
                    color: root.accent
                    font.pixelSize: 14
                    font.bold: true
                    font.letterSpacing: 1.0
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: root.selectedCutIndex >= 0 ? ("Cut " + (root.selectedCutIndex + 1) + " of " + root.cutCount) : "New removal interval"
                    color: root.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }

            AppButton {
                text: "Prev"
                variant: "ghost"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: 54
                enabled: root.selectedCutIndex > 0
                onClicked: root.selectedCutRequested(root.selectedCutIndex - 1)
            }

            AppButton {
                text: "Next"
                variant: "ghost"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: 54
                enabled: root.selectedCutIndex >= 0 && root.selectedCutIndex < root.cutCount - 1
                onClicked: root.selectedCutRequested(root.selectedCutIndex + 1)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: root.lightMode ? theme.lightDivider : theme.darkDivider
        }

        Flickable {
            id: inspectorScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: inspectorContent.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: AppScrollBar { lightMode: root.lightMode }

            ColumnLayout {
                id: inspectorContent
                width: inspectorScroll.width - (inspectorScroll.contentHeight > inspectorScroll.height ? 10 : 0)
                spacing: root.compactMode ? 8 : 10

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    spacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text { text: "Start"; color: root.textMuted; font.pixelSize: 11; font.bold: true }
                        AppTextField {
                            id: startInput
                            Layout.fillWidth: true
                            lightMode: root.lightMode
                            placeholderText: "00:00:00"
                            text: "00:00:00"
                            onEditingFinished: root.refreshKeyframeInfo()
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text { text: "End"; color: root.textMuted; font.pixelSize: 11; font.bold: true }
                        AppTextField {
                            id: endInput
                            Layout.fillWidth: true
                            lightMode: root.lightMode
                            placeholderText: "00:00:00"
                            text: "00:00:00"
                            onAccepted: root.addCut("Manual", "--")
                            onEditingFinished: root.refreshKeyframeInfo()
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.validationMessage()
                    color: root.lightMode ? theme.lightDanger : theme.darkDanger
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    visible: text.length > 0
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.shortMode ? 156 : 176
                    radius: 14
                    color: root.lightMode ? "#F8FAFC" : "#081321"
                    border.color: root.lightMode ? "#DCE4EF" : "#1B2B45"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 7

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "Safe Comparison"
                                color: root.textMain
                                font.pixelSize: 13
                                font.bold: true
                            }
                            Item { Layout.fillWidth: true }
                            Rectangle {
                                Layout.preferredWidth: 104
                                Layout.preferredHeight: 24
                                radius: 12
                                color: root.safeColor
                                opacity: 0.16
                                border.color: root.safeColor
                                Text {
                                    anchors.centerIn: parent
                                    text: "Safe (adjusted)"
                                    color: root.safeColor
                                    font.pixelSize: 10
                                    font.bold: true
                                }
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 4
                            columnSpacing: 8
                            rowSpacing: 7

                            Text { text: ""; color: root.textMuted; font.pixelSize: 10; Layout.preferredWidth: 54 }
                            Text { text: "Requested"; color: root.requestedColor; font.pixelSize: 10; font.bold: true; Layout.fillWidth: true }
                            Text { text: "Safe (adjusted)"; color: root.safeColor; font.pixelSize: 10; font.bold: true; Layout.fillWidth: true }
                            Text { text: "Delta"; color: root.textMuted; font.pixelSize: 10; font.bold: true; Layout.preferredWidth: 52 }

                            Text { text: "Start"; color: root.textMuted; font.pixelSize: 11 }
                            Text { text: startInput.text; color: root.requestedColor; font.pixelSize: 11; font.bold: true }
                            Text { text: root.hasSafeKeyframeInfo() ? root.formatSeconds(root.keyframeInfo.safe_start) : "--"; color: root.safeColor; font.pixelSize: 11; font.bold: true }
                            Text { text: root.hasSafeKeyframeInfo() ? root.formatSignedClockDelta(root.keyframeInfo.safe_start - root.keyframeInfo.requested_start) : "--"; color: root.textMuted; font.pixelSize: 11 }

                            Text { text: "End"; color: root.textMuted; font.pixelSize: 11 }
                            Text { text: endInput.text; color: root.requestedColor; font.pixelSize: 11; font.bold: true }
                            Text { text: root.hasSafeKeyframeInfo() ? root.formatSeconds(root.keyframeInfo.safe_end) : "--"; color: root.safeColor; font.pixelSize: 11; font.bold: true }
                            Text { text: root.hasSafeKeyframeInfo() ? root.formatSignedClockDelta(root.keyframeInfo.safe_end - root.keyframeInfo.requested_end) : "--"; color: root.textMuted; font.pixelSize: 11 }

                            Text { text: "Duration"; color: root.textMuted; font.pixelSize: 11 }
                            Text { text: root.formatDuration(root.parseSeconds(startInput.text), root.parseSeconds(endInput.text)); color: root.requestedColor; font.pixelSize: 11; font.bold: true }
                            Text { text: root.hasSafeKeyframeInfo() ? root.formatDuration(root.keyframeInfo.safe_start, root.keyframeInfo.safe_end) : "--"; color: root.safeColor; font.pixelSize: 11; font.bold: true }
                            Text { text: root.hasSafeKeyframeInfo() ? root.formatSignedClockDelta((root.keyframeInfo.safe_end - root.keyframeInfo.safe_start) - (root.keyframeInfo.requested_end - root.keyframeInfo.requested_start)) : "--"; color: root.textMuted; font.pixelSize: 11 }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.hasSafeKeyframeInfo()
                                  ? (root.formatSignedClockDelta(root.keyframeInfo.extra_before + root.keyframeInfo.extra_after) + " extra removed - Keyframe-aligned stream-copy.")
                                  : (root.keyframeInfo.error || "Set Start and Set End to calculate the adjusted removal.")
                            color: root.hasSafeKeyframeInfo() ? root.textMuted : (root.lightMode ? theme.lightWarning : theme.darkWarning)
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Optional reason and tags appear after setting a valid interval."
                    color: root.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    visible: !root.showOptionalDetails()
                }

                Text {
                    text: "Reason"
                    color: root.textMuted
                    font.pixelSize: 11
                    font.bold: true
                    visible: root.showOptionalDetails()
                }

                AppTextArea {
                    id: reasonInput
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.shortMode ? 50 : 62
                    lightMode: root.lightMode
                    placeholderText: "Reason for this cut..."
                    visible: root.showOptionalDetails()
                }

                Text {
                    text: "Tags"
                    color: root.textMuted
                    font.pixelSize: 11
                    font.bold: true
                    visible: root.showOptionalDetails()
                }

                AppTextField {
                    id: tagsInput
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42
                    lightMode: root.lightMode
                    placeholderText: "kissing, romance, nsfw"
                    visible: root.showOptionalDetails()
                    onAccepted: root.addCut("Manual", "--")
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42
                    spacing: 8

                    AppButton {
                        text: "+ Add Cut"
                        accessibilityLabel: "Cut video segment"
                        iconSource: Qt.resolvedUrl("../../../assets/icons/cut.png")
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
                        variant: "ghost"
                        size: "md"
                        lightMode: root.lightMode
                        Layout.preferredWidth: 78
                        onClicked: root.clearEditor()
                    }
                }

            }
        }
    }
}
