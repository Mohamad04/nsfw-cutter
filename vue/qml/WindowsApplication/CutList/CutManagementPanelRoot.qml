pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import "../Shared"

Rectangle {
    id: root
    objectName: "cutManagementPanel"

    required property var cutsModel
    property int selectedIndex: -1
    property real durationMs: 0
    property bool lightMode: false
    property color panelColor: "#0C1625"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property color requestedColor: root.lightMode ? "#D97706" : "#F59E3D"
    property color safeColor: root.lightMode ? "#15803D" : "#86EFAC"
    property bool requestedEditorActive: false
    property string cutTimingMode: "safe"
    property bool hasVideo: false

    signal importJsonRequested()
    signal exportJsonRequested()
    signal cutSelected(int index)
    signal requestedTimeEdited(int index, string fieldName, real seconds)
    signal timingModeSelected(string mode)

    radius: 14
    focus: true
    color: root.lightMode ? root.panelColor : "#081321"
    border.color: root.lightMode ? root.strokeColor : "#223754"
    clip: true

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 13
        color: "transparent"
        border.color: root.lightMode ? "#FFFFFF" : "#163456"
        opacity: root.lightMode ? 0.36 : 0.42
    }

    AppTheme { id: theme }

    function selectedCut() {
        if (root.selectedIndex < 0 || root.selectedIndex >= root.cutsModel.count) return null
        return root.cutsModel.get(root.selectedIndex)
    }

    function parseTimeSeconds(value) {
        var parts = String(value || "").trim().split(":")
        if (parts.length !== 3) return NaN
        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var seconds = Number(parts[2])
        if (!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(seconds)) return NaN
        return hours * 3600 + minutes * 60 + seconds
    }

    function numericSeconds(cut, secondsKey, timeKey) {
        if (!cut) return NaN
        var value = cut[secondsKey]
        if (value !== undefined && value !== null && value !== "") {
            var numeric = Number(value)
            if (Number.isFinite(numeric)) return numeric
        }
        return root.parseTimeSeconds(cut[timeKey])
    }

    function requestedStartSeconds(cut) {
        return root.numericSeconds(cut, "requestedStartSeconds", "start")
    }

    function requestedEndSeconds(cut) {
        return root.numericSeconds(cut, "requestedEndSeconds", "end")
    }

    function safeStartSeconds(cut) {
        return root.numericSeconds(cut, "safeStartSeconds", "safeStart")
    }

    function safeEndSeconds(cut) {
        return root.numericSeconds(cut, "safeEndSeconds", "safeEnd")
    }

    function requestedDurationSeconds(cut) {
        var start = root.requestedStartSeconds(cut)
        var end = root.requestedEndSeconds(cut)
        return Number.isFinite(start) && Number.isFinite(end) && end > start ? end - start : 0
    }

    function safeDurationSeconds(cut) {
        var start = root.safeStartSeconds(cut)
        var end = root.safeEndSeconds(cut)
        return Number.isFinite(start) && Number.isFinite(end) && end > start ? end - start : root.requestedDurationSeconds(cut)
    }

    function activeStartSeconds(cut) {
        return root.requestedStartSeconds(cut)
    }

    function activeEndSeconds(cut) {
        return root.requestedEndSeconds(cut)
    }

    function activeDurationSeconds(cut) {
        var start = root.activeStartSeconds(cut)
        var end = root.activeEndSeconds(cut)
        return Number.isFinite(start) && Number.isFinite(end) && end > start ? end - start : 0
    }

    function isAdjusted(cut) {
        if (!cut) return false
        var requestedStart = root.requestedStartSeconds(cut)
        var requestedEnd = root.requestedEndSeconds(cut)
        var safeStart = root.safeStartSeconds(cut)
        var safeEnd = root.safeEndSeconds(cut)
        if (!Number.isFinite(requestedStart) || !Number.isFinite(requestedEnd)) return false
        if (!Number.isFinite(safeStart) || !Number.isFinite(safeEnd)) return false
        return Math.abs(safeStart - requestedStart) > 0.001 || Math.abs(safeEnd - requestedEnd) > 0.001
    }

    function statusText(cut) {
        return root.isAdjusted(cut) ? "Adjusted" : "Safe"
    }

    function totalRemovedSeconds() {
        var total = 0
        for (var index = 0; index < root.cutsModel.count; index += 1) {
            total += root.activeDurationSeconds(root.cutsModel.get(index))
        }
        return total
    }

    function formatHms(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
        var totalSeconds = Math.round(seconds)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var secs = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(secs)
    }

    function formatCompact(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
        var totalSeconds = Math.round(seconds)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var secs = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        if (hours > 0) return pad(hours) + ":" + pad(minutes) + ":" + pad(secs)
        return pad(minutes) + ":" + pad(secs)
    }

    function formatSignedDelta(seconds) {
        if (!Number.isFinite(seconds) || Math.abs(seconds) < 0.001) return "00:00"
        return (seconds > 0 ? "+" : "-") + root.formatCompact(Math.abs(seconds))
    }

    function displayTime(cut, timeKey, secondsKey) {
        if (!cut) return "--"
        var text = cut[timeKey]
        if (text !== undefined && text !== null && String(text).length > 0) return String(text)
        var seconds = cut[secondsKey]
        return Number.isFinite(Number(seconds)) ? root.formatHms(Number(seconds)) : "--"
    }

    function canApplyRequestedEdit(fieldName, seconds) {
        var cut = root.selectedCut()
        if (!cut || !Number.isFinite(seconds) || seconds < 0) return false

        var start = root.requestedStartSeconds(cut)
        var end = root.requestedEndSeconds(cut)
        if (!Number.isFinite(start) || !Number.isFinite(end)) return false

        if (fieldName === "start") start = seconds
        else if (fieldName === "end") end = seconds
        else if (fieldName === "duration") end = start + seconds
        else return false

        if (end <= start) return false

        var videoSeconds = Number.isFinite(root.durationMs) && root.durationMs > 0 ? root.durationMs / 1000 : 0
        if (videoSeconds > 0 && (start > videoSeconds || end > videoSeconds)) return false
        return true
    }

    function videoAfterCutsText() {
        if (!Number.isFinite(root.durationMs) || root.durationMs <= 0) return "--:--:--"
        var remaining = Math.max(0, root.durationMs / 1000 - root.totalRemovedSeconds())
        return root.formatHms(remaining)
    }

    function deleteCut(index) {
        if (index < 0 || index >= root.cutsModel.count) return

        var nextSelected = root.selectedIndex
        if (root.selectedIndex === index) {
            nextSelected = Math.min(index, root.cutsModel.count - 2)
        } else if (root.selectedIndex > index) {
            nextSelected = root.selectedIndex - 1
        }

        root.cutsModel.remove(index)
        root.cutSelected(root.cutsModel.count > 0 ? nextSelected : -1)
    }

    function dismissRequestedEditor() {
        if (root.requestedEditorActive)
            root.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        CutListSummaryHeader {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            cutsCount: root.cutsModel.count
            totalRemovedText: root.formatHms(root.totalRemovedSeconds())
            textColor: root.textColor
            mutedTextColor: root.mutedTextColor
            accentColor: root.accentColor
        }

        CutListItemsView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 170
            cutsModel: root.cutsModel
            selectedIndex: root.selectedIndex
            lightMode: root.lightMode
            textColor: root.textColor
            mutedTextColor: root.mutedTextColor
            accentColor: root.accentColor
            statusTextForCut: function(cut) { return root.statusText(cut) }
            durationSecondsForCut: function(cut) { return root.activeDurationSeconds(cut) }
            formatCompact: function(seconds) { return root.formatCompact(seconds) }
            onCutSelected: function(index) { root.cutSelected(index) }
            onCutRemoveRequested: function(index) { root.deleteCut(index) }
            onEditorDismissRequested: root.dismissRequestedEditor()
        }

        CutDetailsPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: root.cutsModel.count > 0 ? 168 : 86
            hasCuts: root.cutsModel.count > 0
            hasSelection: root.selectedCut() !== null
            selectedIndex: root.selectedIndex
            adjusted: root.isAdjusted(root.selectedCut())
            statusText: root.statusText(root.selectedCut())
            requestedStartText: root.displayTime(root.selectedCut(), "start", "requestedStartSeconds")
            requestedEndText: root.displayTime(root.selectedCut(), "end", "requestedEndSeconds")
            requestedDurationText: root.formatCompact(root.requestedDurationSeconds(root.selectedCut()))
            requestedDurationEditText: root.formatHms(root.requestedDurationSeconds(root.selectedCut()))
            safeStartText: root.displayTime(root.selectedCut(), "safeStart", "safeStartSeconds")
            safeEndText: root.displayTime(root.selectedCut(), "safeEnd", "safeEndSeconds")
            safeDurationText: root.formatCompact(root.safeDurationSeconds(root.selectedCut()))
            startDeltaText: root.formatSignedDelta(root.safeStartSeconds(root.selectedCut()) - root.requestedStartSeconds(root.selectedCut()))
            endDeltaText: root.formatSignedDelta(root.safeEndSeconds(root.selectedCut()) - root.requestedEndSeconds(root.selectedCut()))
            durationDeltaText: root.formatSignedDelta(root.safeDurationSeconds(root.selectedCut()) - root.requestedDurationSeconds(root.selectedCut()))
            lightMode: root.lightMode
            textColor: root.textColor
            mutedTextColor: root.mutedTextColor
            accentColor: root.accentColor
            requestedColor: root.requestedColor
            safeColor: root.safeColor
            canApplyEdit: function(fieldName, seconds) { return root.canApplyRequestedEdit(fieldName, seconds) }
            onEditorDismissRequested: root.dismissRequestedEditor()
            onEditorActiveChanged: function(active) { root.requestedEditorActive = active }
            onRequestedTimeEdited: function(fieldName, seconds) {
                root.requestedTimeEdited(root.selectedIndex, fieldName, seconds)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            radius: 12
            color: root.lightMode ? "#F8FAFC" : "#07101D"
            border.color: root.lightMode ? "#E2E8F0" : "#17263E"

            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8

                AppButton {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    text: qsTr("Import JSON")
                    iconName: "open"
                    variant: "secondary"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    onClicked: root.importJsonRequested()
                }

                AppButton {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    text: qsTr("Export JSON")
                    iconName: "export"
                    variant: "secondary"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.hasVideo && root.cutsModel.count > 0
                    onClicked: root.exportJsonRequested()
                }
            }
        }

        CutTotalsPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 74
            totalRemovedText: root.formatHms(root.totalRemovedSeconds())
            videoAfterCutsText: root.videoAfterCutsText()
            hasVideoDuration: root.durationMs > 0
            lightMode: root.lightMode
            textColor: root.textColor
            mutedTextColor: root.mutedTextColor
        }
    }
}

