pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import "../components"

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

    AppTheme { id: theme }
    ListModel { id: cutsModel; objectName: "cutsModel" }

    Component.onCompleted: root.outputDir = settingsController.getExportDir()

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
                Layout.fillWidth: true
                Layout.preferredHeight: 76
                lightMode: root.lightMode
                panelColor: root.surface
                strokeColor: root.borderColor
                textColor: root.textMain
                mutedTextColor: root.textMuted
                accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                onSettingsRequested: root.settingsRequested()
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
                    lightMode: root.lightMode
                    panelColor: root.surface
                    videoColor: root.darkMode ? "#020617" : "#0F172A"
                    strokeColor: root.borderColor
                    textColor: root.textMain
                    mutedTextColor: root.textMuted
                    accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                    onCutAdded: function(cut) { root.appendCut(cut) }
                }

                CutManagementPanel {
                    Layout.preferredWidth: 340
                    Layout.minimumWidth: 320
                    Layout.maximumWidth: 360
                    Layout.fillHeight: true
                    cutsModel: cutsModel
                    selectedIndex: root.selectedCutIndex
                    durationMs: videoWorkspace.durationMs
                    lightMode: root.lightMode
                    panelColor: root.surface
                    strokeColor: root.borderColor
                    textColor: root.textMain
                    mutedTextColor: root.textMuted
                    accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                    onCutSelected: function(index) { root.selectedCutIndex = index }
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
}
