import QtQuick
import QtQuick.Layouts

Item {
    id: root

    required property var cutsModel
    property bool compactMode: false
    property bool headerCollapsed: false
    property bool lightMode: false
    property bool narrowMode: false
    property bool shortMode: false
    property color panelTone: "#0C1625"
    property color videoTone: "#07101C"
    property color textMain: "#F3F6FB"
    property color textMuted: "#92A2B8"
    property color accent: "#2F7BFF"
    property int selectedCutIndex: -1
    property int rightPanelWidth: 380
    property var cutPreview: ({ "visible": false })
    readonly property real videoDurationMs: videoPanel.durationMs
    readonly property real videoPositionMs: videoPanel.positionMs

    AppTheme { id: theme }

    signal cutAdded(var cut)
    signal cutSelected(int index)
    signal cutRangeChanged(int index, real startMs, real endMs)
    signal suggestedCutAdded(string startTime, string endTime, string reason, string tags, string score)
    signal importRequested()
    signal exportRequested()
    signal fastExportAllRequested(string outputDir, string exportMode)
    signal headerExpandRequested()

    function stopPlayback() {
        videoPanel.stopPlayback()
    }

    function applyRecommendation(startTime, endTime, reason, tags) {
        cutInspector.applyRecommendation(startTime, endTime, reason, tags)
    }

    function addCurrentCut() {
        cutInspector.addCurrentCut()
    }

    function seekToTime(timeText) {
        videoPanel.seekToTime(timeText)
    }

    function previewCut(timeText) {
        videoPanel.playFromTime(timeText)
    }

    function previewSelectedCut() {
        videoPanel.previewSelectedCut()
    }

    RowLayout {
        anchors.fill: parent
        spacing: root.compactMode ? 8 : theme.sectionGap

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            spacing: root.compactMode ? 8 : theme.sectionGap

            VideoPreviewPanel {
                id: videoPanel
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: root.shortMode ? 360 : 460
                compactMode: root.compactMode
                lightMode: root.lightMode
                shortMode: root.shortMode
                panelTone: root.panelTone
                videoTone: root.videoTone
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                cutCount: root.cutsModel.count
                cutsModel: root.cutsModel
                selectedCutIndex: root.selectedCutIndex
                cutPreview: root.cutPreview
                onStartRequested: function(timeText) { cutInspector.setStartTime(timeText) }
                onEndRequested: function(timeText) { cutInspector.setEndTime(timeText) }
                onAddCutRequested: root.addCurrentCut()
                onCutMarkerSelected: function(index) { root.cutSelected(index) }
                onCutRangeChanged: function(index, startMs, endMs) {
                    root.cutRangeChanged(index, startMs, endMs)
                }
            }

            AiPicksPanel {
                id: aiPicksPanel
                Layout.fillWidth: true
                Layout.preferredHeight: aiPicksPanel.pickCount === 0 ? 44 : (root.shortMode ? 94 : 108)
                Layout.minimumHeight: aiPicksPanel.pickCount === 0 ? 44 : 88
                Layout.maximumHeight: aiPicksPanel.pickCount === 0 ? 44 : 116
                lightMode: root.lightMode
                narrowMode: root.narrowMode
                shortMode: root.shortMode
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                onEditRequested: function(startTime, endTime, reason, tags) {
                    root.applyRecommendation(startTime, endTime, reason, tags)
                }
                onAddRequested: function(startTime, endTime, reason, tags, score) {
                    root.suggestedCutAdded(startTime, endTime, reason, tags, score)
                }
            }

            CutListPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: root.cutsModel.count === 0 ? 126 : (root.shortMode ? 190 : 250)
                Layout.minimumHeight: root.cutsModel.count === 0 ? 116 : 160
                Layout.maximumHeight: root.cutsModel.count === 0 ? 136 : (root.shortMode ? 220 : 300)
                cutsModel: root.cutsModel
                compactMode: root.compactMode
                lightMode: root.lightMode
                narrowMode: root.narrowMode
                shortMode: root.shortMode
                showExportControls: false
                panelColor: root.panelTone
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                selectedIndex: root.selectedCutIndex
                durationMs: root.videoDurationMs
                videoPositionMs: root.videoPositionMs
                onCutSelected: function(index) { root.cutSelected(index) }
                onEditCutRequested: function(startTime, endTime, reason, tags) {
                    root.applyRecommendation(startTime, endTime, reason, tags)
                }
                onPreviewCutRequested: function(startTime) { root.previewCut(startTime) }
                onJumpCutRequested: function(timeText) { root.seekToTime(timeText) }
                onImportRequested: root.importRequested()
                onExportRequested: root.exportRequested()
                onFastExportAllRequested: function(outputDir, exportMode) {
                    root.fastExportAllRequested(outputDir, exportMode)
                }
            }
        }

        CurrentCutInspector {
            id: cutInspector
            Layout.preferredWidth: root.narrowMode ? 360 : root.rightPanelWidth
            Layout.minimumWidth: 340
            Layout.maximumWidth: 400
            Layout.fillHeight: true
            compactMode: root.compactMode
            lightMode: root.lightMode
            shortMode: root.shortMode
            cutsModel: root.cutsModel
            selectedCutIndex: root.selectedCutIndex
            selectedVideoPath: appController.selectedVideoPath
            videoDurationMs: root.videoDurationMs
            textMain: root.textMain
            textMuted: root.textMuted
            accent: root.accent
            onCutAdded: function(cut) { root.cutAdded(cut) }
            onPreviewChanged: function(preview) { root.cutPreview = preview }
            onSelectedCutRequested: function(index) { root.cutSelected(index) }
        }
    }
}
