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

    signal settingsRequested()

    property bool compactMode: root.width < 1650 || root.height < 820
    property bool narrowMode: root.width < 1500
    property bool shortMode: root.height < 820
    property bool darkMode: settingsController.theme !== "light"
    property bool lightMode: !root.darkMode

    property color bg: darkMode ? theme.darkAppBg : theme.lightAppBg
    property color panel: darkMode ? theme.darkSurface : theme.lightSurface
    property color videoBg: darkMode ? theme.darkVideoSurface : theme.lightVideoSurface
    property color textMain: darkMode ? theme.darkTextPrimary : theme.lightTextPrimary
    property color textMuted: darkMode ? theme.darkTextMuted : theme.lightTextMuted
    property color accent: darkMode ? theme.darkAccent : theme.lightAccent
    property color borderColor: darkMode ? theme.darkBorder : theme.lightBorder
    property int listScrollbarGutter: 14
    property int selectedCutIndex: -1
    property string outputDir: ""

    ListModel { id: cutsModel }

    AppTheme { id: theme }

    Component.onCompleted: root.outputDir = settingsController.getExportDir()

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
                "safe_available": cut.safeAvailable,
                "previous_keyframe_start": cut.previousKeyframeStart,
                "next_keyframe_start": cut.nextKeyframeStart,
                "previous_keyframe_end": cut.previousKeyframeEnd,
                "next_keyframe_end": cut.nextKeyframeEnd,
                "reason": cut.reason,
                "tags": cut.tags,
                "source": cut.source,
                "score": cut.score,
                "type": cut.cutType,
                "status": cut.status
            })
        }
        return cuts
    }

    function hasUsableSafeCut(cut) {
        var safeStart = cut.safeStartSeconds !== undefined ? cut.safeStartSeconds : cut.safe_start_seconds
        var safeEnd = cut.safeEndSeconds !== undefined ? cut.safeEndSeconds : cut.safe_end_seconds
        var hasNumericSafe = safeStart !== undefined
            && safeStart !== null
            && safeStart !== ""
            && safeEnd !== undefined
            && safeEnd !== null
            && safeEnd !== ""
            && Number.isFinite(Number(safeStart))
            && Number.isFinite(Number(safeEnd))
            && Number(safeStart) < Number(safeEnd)
        if (hasNumericSafe) return true

        var safeStartText = cut.safeStart || cut.safe_start || ""
        var safeEndText = cut.safeEnd || cut.safe_end || ""
        return root.isTimeText(safeStartText) && root.isTimeText(safeEndText)
    }

    function isTimeText(value) {
        var parts = String(value).trim().split(":")
        return parts.length === 3
            && Number.isFinite(Number(parts[0]))
            && Number.isFinite(Number(parts[1]))
            && Number.isFinite(Number(parts[2]))
    }

    function computedSafeCut(start, end) {
        if (appController.selectedVideoPath.length === 0) return null
        var info = videoCutController.keyframeCutInfo(
            appController.selectedVideoPath,
            start,
            end,
            homeBody.videoDurationMs > 0 ? homeBody.videoDurationMs / 1000 : 0
        )
        if (!info.valid || info.safe_start === null || info.safe_end === null) return null
        return info
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
        if (milliseconds > 0) {
            text += "." + padMillis(milliseconds)
        }
        return text
    }

    function importCutsFromJson() {
        var importedCuts = appController.importCuts()
        if (importedCuts.length === 0) return

        cutsModel.clear()
        for (var index = 0; index < importedCuts.length; index += 1) {
            root.appendCut(importedCuts[index])
        }
    }

    function appendCut(cut) {
        var start = cut.start || cut.requestedStart || "00:00:00"
        var end = cut.end || cut.requestedEnd || "00:00:00"
        var safeInfo = root.hasUsableSafeCut(cut) ? null : root.computedSafeCut(start, end)
        var safeAvailable = root.hasUsableSafeCut(cut) || safeInfo !== null
        var requestedStartSeconds = safeInfo !== null ? safeInfo.requested_start : (cut.requestedStartSeconds !== undefined ? cut.requestedStartSeconds : (cut.requested_start_seconds !== undefined ? cut.requested_start_seconds : ""))
        var requestedEndSeconds = safeInfo !== null ? safeInfo.requested_end : (cut.requestedEndSeconds !== undefined ? cut.requestedEndSeconds : (cut.requested_end_seconds !== undefined ? cut.requested_end_seconds : ""))
        var safeStartSeconds = safeInfo !== null ? safeInfo.safe_start : (cut.safeStartSeconds !== undefined ? cut.safeStartSeconds : (cut.safe_start_seconds !== undefined ? cut.safe_start_seconds : ""))
        var safeEndSeconds = safeInfo !== null ? safeInfo.safe_end : (cut.safeEndSeconds !== undefined ? cut.safeEndSeconds : (cut.safe_end_seconds !== undefined ? cut.safe_end_seconds : ""))
        var safeStart = safeInfo !== null ? root.formatSeconds(safeInfo.safe_start) : (cut.safeStart || cut.safe_start || root.formatSeconds(safeStartSeconds))
        var safeEnd = safeInfo !== null ? root.formatSeconds(safeInfo.safe_end) : (cut.safeEnd || cut.safe_end || root.formatSeconds(safeEndSeconds))

        cutsModel.append({
            "start": start,
            "end": end,
            "safeStart": safeStart,
            "safeEnd": safeEnd,
            "requestedStartSeconds": requestedStartSeconds,
            "requestedEndSeconds": requestedEndSeconds,
            "safeStartSeconds": safeStartSeconds,
            "safeEndSeconds": safeEndSeconds,
            "safeAvailable": safeAvailable,
            "previousKeyframeStart": safeInfo !== null ? root.formatSeconds(safeInfo.previous_keyframe_start) : (cut.previousKeyframeStart || cut.previous_keyframe_start || ""),
            "nextKeyframeStart": safeInfo !== null ? root.formatSeconds(safeInfo.next_keyframe_start) : (cut.nextKeyframeStart || cut.next_keyframe_start || ""),
            "previousKeyframeEnd": safeInfo !== null ? root.formatSeconds(safeInfo.previous_keyframe_end) : (cut.previousKeyframeEnd || cut.previous_keyframe_end || ""),
            "nextKeyframeEnd": safeInfo !== null ? root.formatSeconds(safeInfo.next_keyframe_end) : (cut.nextKeyframeEnd || cut.next_keyframe_end || ""),
            "extraBefore": safeInfo !== null ? Number(safeInfo.extra_before).toFixed(1) + "s" : (cut.extraBefore || "0.0s"),
            "extraAfter": safeInfo !== null ? Number(safeInfo.extra_after).toFixed(1) + "s" : (cut.extraAfter || "0.0s"),
            "reason": cut.reason || "Manual removal",
            "tags": cut.tags || "manual",
            "source": cut.source || "Manual",
            "score": cut.score || "--",
            "cutType": cut.type || cut.cutType || "Remove",
            "status": safeAvailable ? (cut.status || "Pending") : "Safe unavailable"
        })
        root.selectedCutIndex = cutsModel.count - 1
    }

    function updateCutTiming(index, startMs, endMs) {
        if (index < 0 || index >= cutsModel.count) return
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs >= endMs) return

        var start = root.formatSeconds(startMs / 1000)
        var end = root.formatSeconds(endMs / 1000)
        var safeInfo = root.computedSafeCut(start, end)

        cutsModel.setProperty(index, "start", start)
        cutsModel.setProperty(index, "end", end)
        cutsModel.setProperty(index, "requestedStartSeconds", startMs / 1000)
        cutsModel.setProperty(index, "requestedEndSeconds", endMs / 1000)

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
            cutsModel.setProperty(index, "extraBefore", Number(safeInfo.extra_before).toFixed(1) + "s")
            cutsModel.setProperty(index, "extraAfter", Number(safeInfo.extra_after).toFixed(1) + "s")
            cutsModel.setProperty(index, "status", "Pending")
        } else {
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

        root.selectedCutIndex = index
    }

    function addSuggestedCut(startTime, endTime, reason, tags, score) {
        root.appendCut({
            "start": startTime,
            "end": endTime,
            "reason": reason,
            "tags": tags,
            "source": "AI",
            "score": score,
            "cutType": "Remove",
            "status": "Pending"
        })
    }

    function chooseOutputFolder() {
        var folder = settingsController.chooseExportDir()
        if (folder.length === 0) return
        root.outputDir = folder
        settingsController.setExportDir(folder)
    }

    function previewCuts() {
        if (cutsModel.count === 0) return
        var index = root.selectedCutIndex >= 0 && root.selectedCutIndex < cutsModel.count ? root.selectedCutIndex : 0
        root.selectedCutIndex = index
        var cut = cutsModel.get(index)
        homeBody.previewCut(cut.safeStart || cut.start || "00:00:00")
    }

    Rectangle {
        anchors.fill: parent
        color: root.bg

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: root.compactMode ? 12 : theme.windowMargin
            spacing: appHeader.headerCollapsed ? 0 : (root.compactMode ? 10 : theme.sectionGap)

            AppHeader {
                id: appHeader

                visible: !appHeader.headerCollapsed
                Layout.fillWidth: true
                Layout.preferredHeight: appHeader.preferredHeaderHeight
                Layout.minimumHeight: appHeader.collapsedHeaderHeight
                Layout.preferredWidth: -1
                Layout.maximumWidth: Number.POSITIVE_INFINITY
                Layout.maximumHeight: appHeader.expandedHeaderHeight
                Layout.alignment: Qt.AlignTop | Qt.AlignLeft
                compactMode: root.compactMode
                narrowMode: root.narrowMode
                lightMode: root.lightMode
                panelColor: root.panel
                strokeColor: root.borderColor
                textColor: root.textMain
                mutedTextColor: root.textMuted
                accentColor: root.accent
                durationMs: homeBody.videoDurationMs
                onOpenFileRequested: appController.openFile()
                onOpenFilesRequested: appController.openFiles()
                onOpenFolderRequested: appController.browseFolder()
                onRecentFileRequested: function(path) { appController.openRecentFile(path) }
                onClearRecentFilesRequested: appController.clearRecentFiles()
                onClearRequested: {
                    appController.clearVideo()
                    homeBody.stopPlayback()
                }
                onSettingsClicked: root.settingsRequested()
            }

            HomeBody {
                id: homeBody
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: root.shortMode ? 430 : 560
                cutsModel: cutsModel
                compactMode: root.compactMode
                lightMode: root.lightMode
                narrowMode: root.narrowMode
                shortMode: root.shortMode
                rightPanelWidth: theme.rightPanelWidth
                panelTone: root.panel
                videoTone: root.videoBg
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                headerCollapsed: appHeader.headerCollapsed
                selectedCutIndex: root.selectedCutIndex
                onCutAdded: function(cut) { root.appendCut(cut) }
                onCutSelected: function(index) { root.selectedCutIndex = index }
                onCutRangeChanged: function(index, startMs, endMs) {
                    root.updateCutTiming(index, startMs, endMs)
                }
                onSuggestedCutAdded: function(startTime, endTime, reason, tags, score) {
                    root.addSuggestedCut(startTime, endTime, reason, tags, score)
                }
                onImportRequested: root.importCutsFromJson()
                onExportRequested: appController.exportCuts(root.cutsToArray())
                onFastExportAllRequested: function(outputDir, exportMode) {
                    videoCutController.exportSegments(appController.selectedVideoPath, root.cutsToArray(), outputDir, exportMode)
                }
                onHeaderExpandRequested: appHeader.headerCollapsed = false
            }

            CutExportControls {
                Layout.fillWidth: true
                Layout.preferredHeight: root.shortMode ? 72 : 78
                Layout.minimumHeight: root.shortMode ? 68 : 74
                outputDir: root.outputDir
                narrowMode: root.narrowMode
                hasSegments: cutsModel.count > 0
                lightMode: root.lightMode
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                onChooseFolderRequested: root.chooseOutputFolder()
                onPreviewCutsRequested: root.previewCuts()
                onExportRemoveRequested: {
                    videoCutController.exportSegments(appController.selectedVideoPath, root.cutsToArray(), root.outputDir, "remove_intervals")
                }
            }
        }
    }
}


