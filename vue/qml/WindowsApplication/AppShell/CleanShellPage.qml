pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import "../CutEditor"
import "../CutList"
import "../Discovery"
import "../Settings"
import "../Shared"
import "../VideoPlayer"

Item {
    id: root
    objectName: "cleanShellPage"

    signal settingsRequested()

    property bool darkMode: settingsController.theme !== "light"
    property bool lightMode: !root.darkMode
    property color pageBg: root.darkMode ? theme.darkAppBg : theme.lightAppBg
    property color surface: root.darkMode ? theme.darkSurface : theme.lightSurface
    property color videoSurface: root.darkMode ? theme.darkVideoSurface : theme.lightVideoSurface
    property color borderColor: root.darkMode ? theme.darkBorder : theme.lightBorder
    property color textMain: root.darkMode ? theme.darkTextPrimary : theme.lightTextPrimary
    property color textMuted: root.darkMode ? theme.darkTextMuted : theme.lightTextMuted
    property int selectedCutIndex: -1
    property string outputDir: ""
    property string cutTimingMode: "safe"

    AppTheme { id: theme }
    ListModel {
        id: cutsModel
        objectName: "cutsModel"

        onCountChanged: root.syncAiPickAddedState()
    }

    Component.onCompleted: root.outputDir = settingsController.getExportDir()

    function syncAiPickAddedState() {
        appHeader.syncAiPickAddedState(cutsModel)
    }

    function formatSeconds(seconds) {
        if (seconds === null || seconds === undefined || seconds === "") return ""
        var value = Number(seconds)
        if (!Number.isFinite(value)) return ""
        value = Math.max(0, value)
        var totalMilliseconds = Math.round(value * 1000)
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

    function numericSeconds(cut, secondsKey, timeKey) {
        if (!cut) return NaN
        var seconds = cut[secondsKey]
        if (seconds !== undefined && seconds !== null && seconds !== "") {
            var numeric = Number(seconds)
            if (Number.isFinite(numeric)) return numeric
        }

        var parts = String(cut[timeKey] || "").trim().split(":")
        if (parts.length !== 3) return NaN
        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var timeSeconds = Number(parts[2])
        if (!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(timeSeconds)) return NaN
        return hours * 3600 + minutes * 60 + timeSeconds
    }

    function computedSafeCut(start, end) {
        if (appController.selectedVideoPath.length === 0) return null
        var info = videoCutController.keyframeCutInfo(
            appController.selectedVideoPath,
            start,
            end,
            videoWorkspace.durationMs > 0 ? videoWorkspace.durationMs / 1000 : 0
        )
        if (!info.valid || info.safe_start === null || info.safe_end === null) return null
        return info
    }

    function clearSafeCut(index) {
        cutsModel.setProperty(index, "safeStart", "")
        cutsModel.setProperty(index, "safeEnd", "")
        cutsModel.setProperty(index, "safeStartSeconds", "")
        cutsModel.setProperty(index, "safeEndSeconds", "")
        cutsModel.setProperty(index, "safeAvailable", false)
        cutsModel.setProperty(index, "previousKeyframeStart", "")
        cutsModel.setProperty(index, "nextKeyframeStart", "")
        cutsModel.setProperty(index, "previousKeyframeEnd", "")
        cutsModel.setProperty(index, "nextKeyframeEnd", "")
        cutsModel.setProperty(index, "extraBefore", "0.0s")
        cutsModel.setProperty(index, "extraAfter", "0.0s")
        cutsModel.setProperty(index, "status", "Safe unavailable")
    }

    function updateRequestedCutTime(index, fieldName, seconds) {
        if (index < 0 || index >= cutsModel.count || !Number.isFinite(seconds) || seconds < 0) return

        var cut = cutsModel.get(index)
        var startSeconds = root.numericSeconds(cut, "requestedStartSeconds", "start")
        var endSeconds = root.numericSeconds(cut, "requestedEndSeconds", "end")
        if (!Number.isFinite(startSeconds) || !Number.isFinite(endSeconds)) return

        if (fieldName === "start") {
            startSeconds = seconds
        } else if (fieldName === "end") {
            endSeconds = seconds
        } else if (fieldName === "duration") {
            endSeconds = startSeconds + seconds
        } else {
            return
        }

        var videoSeconds = videoWorkspace.durationMs > 0 ? videoWorkspace.durationMs / 1000 : 0
        if (endSeconds <= startSeconds) return
        if (videoSeconds > 0 && (startSeconds > videoSeconds || endSeconds > videoSeconds)) return

        var startText = root.formatSeconds(startSeconds)
        var endText = root.formatSeconds(endSeconds)
        var safeInfo = root.computedSafeCut(startText, endText)

        cutsModel.setProperty(index, "start", startText)
        cutsModel.setProperty(index, "end", endText)
        cutsModel.setProperty(index, "requestedStartSeconds", startSeconds)
        cutsModel.setProperty(index, "requestedEndSeconds", endSeconds)

        if (safeInfo !== null) {
            cutsModel.setProperty(index, "safeStart", root.formatSeconds(safeInfo.safe_start))
            cutsModel.setProperty(index, "safeEnd", root.formatSeconds(safeInfo.safe_end))
            cutsModel.setProperty(index, "safeStartSeconds", safeInfo.safe_start)
            cutsModel.setProperty(index, "safeEndSeconds", safeInfo.safe_end)
            cutsModel.setProperty(index, "safeAvailable", true)
            cutsModel.setProperty(index, "previousKeyframeStart", root.formatSeconds(safeInfo.previous_keyframe_start))
            cutsModel.setProperty(index, "nextKeyframeStart", root.formatSeconds(safeInfo.next_keyframe_start))
            cutsModel.setProperty(index, "previousKeyframeEnd", root.formatSeconds(safeInfo.previous_keyframe_end))
            cutsModel.setProperty(index, "nextKeyframeEnd", root.formatSeconds(safeInfo.next_keyframe_end))
            cutsModel.setProperty(index, "extraBefore", Number(safeInfo.extra_before || 0).toFixed(1) + "s")
            cutsModel.setProperty(index, "extraAfter", Number(safeInfo.extra_after || 0).toFixed(1) + "s")
            cutsModel.setProperty(index, "status", "Pending")
        } else {
            root.clearSafeCut(index)
        }

        root.selectedCutIndex = index
    }

    function appendCut(cut) {
        cutsModel.append({
            "start": cut.start || "00:00:00",
            "end": cut.end || "00:00:00",
            "safeStart": cut.safeStart || "",
            "safeEnd": cut.safeEnd || "",
            "requestedStartSeconds": cut.requestedStartSeconds !== undefined ? cut.requestedStartSeconds : "",
            "requestedEndSeconds": cut.requestedEndSeconds !== undefined ? cut.requestedEndSeconds : "",
            "safeStartSeconds": cut.safeStartSeconds !== undefined ? cut.safeStartSeconds : "",
            "safeEndSeconds": cut.safeEndSeconds !== undefined ? cut.safeEndSeconds : "",
            "safeAvailable": cut.safeAvailable === true,
            "previousKeyframeStart": cut.previousKeyframeStart || "",
            "nextKeyframeStart": cut.nextKeyframeStart || "",
            "previousKeyframeEnd": cut.previousKeyframeEnd || "",
            "nextKeyframeEnd": cut.nextKeyframeEnd || "",
            "extraBefore": cut.extraBefore || "0.0s",
            "extraAfter": cut.extraAfter || "0.0s",
            "reason": cut.reason || "Manual removal",
            "tags": cut.tags || "manual",
            "source": cut.source || "Manual",
            "score": cut.score || "--",
            "cutType": cut.cutType || "Remove",
            "status": cut.status || "Pending"
        })
        root.selectedCutIndex = cutsModel.count - 1
    }

    function cutsToArray() {
        var cuts = []
        for (var index = 0; index < cutsModel.count; index += 1) {
            var cut = cutsModel.get(index)
            cuts.push({
                "start": cut.start,
                "end": cut.end,
                "safe_start": cut.safeStart,
                "safe_end": cut.safeEnd,
                "requested_start_seconds": cut.requestedStartSeconds,
                "requested_end_seconds": cut.requestedEndSeconds,
                "safe_start_seconds": cut.safeStartSeconds,
                "safe_end_seconds": cut.safeEndSeconds,
                "previous_keyframe_start": cut.previousKeyframeStart,
                "next_keyframe_start": cut.nextKeyframeStart,
                "previous_keyframe_end": cut.previousKeyframeEnd,
                "next_keyframe_end": cut.nextKeyframeEnd,
                "reason": cut.reason,
                "tags": cut.tags,
                "source": cut.source,
                "score": cut.score,
                "timing_mode": root.cutTimingMode,
                "type": cut.cutType,
                "status": cut.status
            })
        }
        return cuts
    }

    function chooseOutputFolder() {
        var folder = settingsController.chooseExportDir()
        if (folder.length === 0) return
        root.outputDir = folder
        settingsController.setExportDir(folder)
    }

    function exportCleanVideo() {
        if (appController.selectedVideoPath.length === 0 || cutsModel.count === 0) return
        videoCutController.exportSegments(
            appController.selectedVideoPath,
            root.cutsToArray(),
            root.outputDir,
            "remove_intervals"
        )
    }

    function previewStartForCut(cut) {
        if (!cut) return "00:00:00"
        if (root.cutTimingMode === "requested")
            return cut.start || root.formatSeconds(cut.requestedStartSeconds)
        return cut.safeStart || cut.start || root.formatSeconds(cut.safeStartSeconds) || "00:00:00"
    }

    Rectangle {
        anchors.fill: parent
        color: root.pageBg
        gradient: Gradient {
            GradientStop { position: 0.0; color: root.lightMode ? root.pageBg : "#050A13" }
            GradientStop { position: 0.55; color: root.lightMode ? "#F8FAFC" : "#07111F" }
            GradientStop { position: 1.0; color: root.lightMode ? "#EEF2F7" : "#030711" }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            CompactAppHeader {
                id: appHeader

                Layout.fillWidth: true
                Layout.preferredHeight: 76
                lightMode: root.lightMode
                panelColor: root.surface
                strokeColor: root.borderColor
                textColor: root.textMain
                mutedTextColor: root.textMuted
                accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                onSettingsRequested: root.settingsRequested()
                onAiPickAddRequested: function(index, startTime, endTime, confidence, reason) {
                    if (videoWorkspace.addCutFromSuggestion(startTime, endTime, confidence, reason))
                        appHeader.markAiPickAdded(index)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12

                VideoWorkspace {
                    id: videoWorkspace

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    cutsModel: cutsModel
                    cutTimingMode: root.cutTimingMode
                    lightMode: root.lightMode
                    panelColor: root.surface
                    videoColor: root.darkMode ? "#020617" : "#0F172A"
                    strokeColor: root.borderColor
                    textColor: root.textMain
                    mutedTextColor: root.textMuted
                    accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                    onCutAdded: function(cut) { root.appendCut(cut) }
                    onTimingModeSelected: function(mode) { root.cutTimingMode = mode }
                }

                CutManagementPanel {
                    Layout.preferredWidth: 340
                    Layout.minimumWidth: 320
                    Layout.maximumWidth: 360
                    Layout.fillHeight: true
                    cutsModel: cutsModel
                    selectedIndex: root.selectedCutIndex
                    durationMs: videoWorkspace.durationMs
                    cutTimingMode: root.cutTimingMode
                    lightMode: root.lightMode
                    panelColor: root.surface
                    strokeColor: root.borderColor
                    textColor: root.textMain
                    mutedTextColor: root.textMuted
                    accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                    onCutSelected: function(index) { root.selectedCutIndex = index }
                    onTimingModeSelected: function(mode) { root.cutTimingMode = mode }
                    onRequestedTimeEdited: function(index, fieldName, seconds) {
                        root.updateRequestedCutTime(index, fieldName, seconds)
                    }
                }
            }

            ExportActionBar {
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                outputDir: root.outputDir
                lightMode: root.lightMode
                hasVideo: appController.selectedVideoPath.length > 0
                hasCuts: cutsModel.count > 0
                panelColor: root.surface
                strokeColor: root.borderColor
                textColor: root.textMain
                mutedTextColor: root.textMuted
                accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                onChooseFolderRequested: root.chooseOutputFolder()
                onExportCleanVideoRequested: root.exportCleanVideo()
            }
        }
    }

    Connections {
        target: appController

        function onAiSuggestionsChanged() {
            Qt.callLater(root.syncAiPickAddedState)
        }
    }
}

