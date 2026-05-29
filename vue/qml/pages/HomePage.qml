pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import "../components"

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
    property color accent: darkMode ? theme.darkAccent : theme.lightCyan
    property color borderColor: darkMode ? theme.darkBorder : theme.lightBorder
    property int listScrollbarGutter: 14
    property int selectedCutIndex: -1
    readonly property int footerHeight: {
        var target = root.shortMode ? 280 : Math.floor(root.height * 0.42)
        return Math.max(root.shortMode ? 260 : 390, Math.min(theme.bottomPanelHeight, target))
    }

    ListModel { id: cutsModel }

    AppTheme { id: theme }

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
                "type": cut.cutType,
                "status": cut.status
            })
        }
        return cuts
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
        var safeStart = cut.safeStart || cut.safe_start || start
        var safeEnd = cut.safeEnd || cut.safe_end || end

        cutsModel.append({
            "start": start,
            "end": end,
            "safeStart": safeStart,
            "safeEnd": safeEnd,
            "requestedStartSeconds": cut.requestedStartSeconds !== undefined ? cut.requestedStartSeconds : (cut.requested_start_seconds !== undefined ? cut.requested_start_seconds : ""),
            "requestedEndSeconds": cut.requestedEndSeconds !== undefined ? cut.requestedEndSeconds : (cut.requested_end_seconds !== undefined ? cut.requested_end_seconds : ""),
            "safeStartSeconds": cut.safeStartSeconds !== undefined ? cut.safeStartSeconds : (cut.safe_start_seconds !== undefined ? cut.safe_start_seconds : ""),
            "safeEndSeconds": cut.safeEndSeconds !== undefined ? cut.safeEndSeconds : (cut.safe_end_seconds !== undefined ? cut.safe_end_seconds : ""),
            "previousKeyframeStart": cut.previousKeyframeStart || cut.previous_keyframe_start || safeStart,
            "nextKeyframeStart": cut.nextKeyframeStart || cut.next_keyframe_start || start,
            "previousKeyframeEnd": cut.previousKeyframeEnd || cut.previous_keyframe_end || end,
            "nextKeyframeEnd": cut.nextKeyframeEnd || cut.next_keyframe_end || safeEnd,
            "extraBefore": cut.extraBefore || "0.0s",
            "extraAfter": cut.extraAfter || "0.0s",
            "reason": cut.reason || "Manual removal",
            "tags": cut.tags || "manual",
            "source": cut.source || "Manual",
            "score": cut.score || "--",
            "cutType": cut.type || cut.cutType || "Remove",
            "status": cut.status || "Pending"
        })
        root.selectedCutIndex = cutsModel.count - 1
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

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: root.compactMode ? 10 : theme.sectionGap

                HomeBody {
                    id: homeBody
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: root.shortMode ? 280 : 400
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
                    onHeaderExpandRequested: appHeader.headerCollapsed = false
                }

                HomeFooter {
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.footerHeight
                    Layout.minimumHeight: root.shortMode ? 260 : 340
                    Layout.maximumHeight: 480
                    cutsModel: cutsModel
                    compactMode: root.compactMode
                    lightMode: root.lightMode
                    narrowMode: root.narrowMode
                    shortMode: root.shortMode
                    panelTone: root.panel
                    textMain: root.textMain
                    textMuted: root.textMuted
                    accent: root.accent
                    scrollbarGutter: root.listScrollbarGutter
                    selectedCutIndex: root.selectedCutIndex
                    videoDurationMs: homeBody.videoDurationMs
                    videoPositionMs: homeBody.videoPositionMs
                    onCutSelected: function(index) { root.selectedCutIndex = index }
                    onEditRequested: function(startTime, endTime, reason, tags) {
                        homeBody.applyRecommendation(startTime, endTime, reason, tags)
                    }
                    onPreviewRequested: function(startTime) { homeBody.previewCut(startTime) }
                    onJumpRequested: function(timeText) { homeBody.seekToTime(timeText) }
                    onSuggestedCutAdded: function(startTime, endTime, reason, tags, score) {
                        root.addSuggestedCut(startTime, endTime, reason, tags, score)
                    }
                    onImportRequested: root.importCutsFromJson()
                    onExportRequested: appController.exportCuts(root.cutsToArray())
                    onFastExportAllRequested: function(outputDir, exportMode) {
                        videoCutController.exportSegments(appController.selectedVideoPath, root.cutsToArray(), outputDir, exportMode)
                    }
                }
            }
        }
    }
}
