pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import "../components"

Item {
    id: root

    signal settingsRequested()

    property bool compactMode: root.width < 1180 || root.height < 720
    property bool narrowMode: root.width < 1060
    property bool shortMode: root.height < 700
    property bool darkMode: settingsController.theme !== "light"

    property color bg: darkMode ? "#0F172A" : "#F6F7FB"
    property color panel: darkMode ? "#0B1324" : "#FFFFFF"
    property color videoBg: darkMode ? "#1E293B" : "#E2E8F0"
    property color textMain: darkMode ? "#F8FAFC" : "#0F172A"
    property color textMuted: darkMode ? "#94A3B8" : "#475569"
    property color accent: "#38BDF8"
    property int listScrollbarGutter: 14

    ListModel { id: cutsModel }

    function cutsToArray() {
        var cuts = []
        for (var index = 0; index < cutsModel.count; index += 1) {
            var cut = cutsModel.get(index)
            cuts.push({
                "start": cut.start,
                "end": cut.end,
                "reason": cut.reason,
                "tags": cut.tags,
                "source": cut.source,
                "score": cut.score
            })
        }
        return cuts
    }

    function importCutsFromJson() {
        var importedCuts = appController.importCuts()
        if (importedCuts.length === 0) return

        cutsModel.clear()
        for (var index = 0; index < importedCuts.length; index += 1) {
            cutsModel.append(importedCuts[index])
        }
    }

    function addSuggestedCut(startTime, endTime, reason, tags, score) {
        cutsModel.append({
            "start": startTime,
            "end": endTime,
            "reason": reason,
            "tags": tags,
            "source": "AI",
            "score": score
        })
    }

    Rectangle {
        anchors.fill: parent
        color: root.bg

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: root.compactMode ? 10 : 14
            spacing: root.compactMode ? 8 : 10

            AppHeader {
                Layout.fillWidth: true
                Layout.preferredHeight: root.compactMode ? 52 : 58
                compactMode: root.compactMode
                narrowMode: root.narrowMode
                panelColor: root.panel
                textColor: root.textMain
                mutedTextColor: root.textMuted
                accentColor: root.accent
                onFolderRequested: appController.browseFolder()
                onClearRequested: {
                    appController.clearVideo()
                    videoPreview.stopPlayback()
                }
                onSettingsClicked: root.settingsRequested()
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: root.compactMode ? 8 : 10

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: root.compactMode ? 8 : 10

                    VideoPreviewPanel {
                        id: videoPreview
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 330
                        compactMode: root.compactMode
                        panelTone: root.panel
                        videoTone: root.videoBg
                        textMain: root.textMain
                        textMuted: root.textMuted
                        accent: root.accent
                        cutCount: cutsModel.count
                        onStartRequested: function(timeText) { cutEditor.setStartTime(timeText) }
                        onEndRequested: function(timeText) { cutEditor.setEndTime(timeText) }
                    }

                    CutEditorPanel {
                        id: cutEditor
                        Layout.preferredWidth: root.narrowMode ? 300 : 320
                        Layout.minimumWidth: 290
                        Layout.alignment: Qt.AlignTop
                        Layout.preferredHeight: implicitHeight
                        compactMode: root.compactMode
                        shortMode: root.shortMode
                        panelTone: root.panel
                        textMain: root.textMain
                        textMuted: root.textMuted
                        accent: root.accent
                        onCutAdded: function(cut) { cutsModel.append(cut) }
                    }
                }

                Panel {
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.shortMode ? 168 : 218
                    panelColor: root.panel
                    strokeColor: "#21324D"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: root.compactMode ? 10 : 12
                        spacing: root.compactMode ? 8 : 10

                        FoundVideosPanel {
                            Layout.preferredWidth: root.narrowMode ? 220 : 260
                            Layout.fillHeight: true
                            shortMode: root.shortMode
                            textMain: root.textMain
                            textMuted: root.textMuted
                            accent: root.accent
                            scrollbarGutter: root.listScrollbarGutter
                        }

                        AiPicksPanel {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            narrowMode: root.narrowMode
                            shortMode: root.shortMode
                            textMain: root.textMain
                            textMuted: root.textMuted
                            accent: root.accent
                            scrollbarGutter: root.listScrollbarGutter
                            onEditRequested: function(startTime, endTime, reason, tags) {
                                cutEditor.applyRecommendation(startTime, endTime, reason, tags)
                            }
                            onAddRequested: function(startTime, endTime, reason, tags, score) {
                                root.addSuggestedCut(startTime, endTime, reason, tags, score)
                            }
                        }

                        CutListPanel {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            cutsModel: cutsModel
                            narrowMode: root.narrowMode
                            textMain: root.textMain
                            textMuted: root.textMuted
                            accent: root.accent
                            scrollbarGutter: root.listScrollbarGutter
                            onImportRequested: root.importCutsFromJson()
                            onExportRequested: appController.exportCuts(root.cutsToArray())
                        }
                    }
                }
            }
        }
    }
}
