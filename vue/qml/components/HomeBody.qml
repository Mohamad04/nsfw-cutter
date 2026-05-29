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
    property color panelTone: "#0B1324"
    property color videoTone: "#1E293B"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int selectedCutIndex: -1
    property int rightPanelWidth: 380
    property var cutPreview: ({ "visible": false })
    readonly property real videoDurationMs: videoPanel.durationMs
    readonly property real videoPositionMs: videoPanel.positionMs

    AppTheme { id: theme }

    signal cutAdded(var cut)
    signal cutSelected(int index)
    signal cutRangeChanged(int index, real startMs, real endMs)
    signal headerExpandRequested()

    function stopPlayback() {
        videoPanel.stopPlayback()
    }

    function applyRecommendation(startTime, endTime, reason, tags) {
        cutEditor.applyRecommendation(startTime, endTime, reason, tags)
    }

    function addCurrentCut() {
        cutEditor.addCurrentCut()
    }

    function seekToTime(timeText) {
        videoPanel.seekToTime(timeText)
    }

    function previewCut(timeText) {
        videoPanel.playFromTime(timeText)
    }

    RowLayout {
        anchors.fill: parent
        spacing: root.compactMode ? 10 : theme.sectionGap

        VideoPreviewPanel {
            id: videoPanel
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            Layout.minimumHeight: root.shortMode ? 260 : 400
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
            onStartRequested: function(timeText) { cutEditor.setStartTime(timeText) }
            onEndRequested: function(timeText) { cutEditor.setEndTime(timeText) }
            onAddCutRequested: root.addCurrentCut()
            onCutMarkerSelected: function(index) { root.cutSelected(index) }
            onCutRangeChanged: function(index, startMs, endMs) {
                root.cutRangeChanged(index, startMs, endMs)
            }
        }

        CutEditorPanel {
            id: cutEditor
            Layout.preferredWidth: root.narrowMode ? 320 : root.rightPanelWidth
            Layout.minimumWidth: root.narrowMode ? 300 : 340
            Layout.maximumWidth: 420
            Layout.fillHeight: true
            Layout.minimumHeight: root.shortMode ? 260 : 400
            compactMode: root.compactMode
            headerCollapsed: root.headerCollapsed
            lightMode: root.lightMode
            shortMode: root.shortMode
            selectedVideoPath: appController.selectedVideoPath
            videoDurationMs: root.videoDurationMs
            panelTone: root.panelTone
            textMain: root.textMain
            textMuted: root.textMuted
            accent: root.accent
            onCutAdded: function(cut) { root.cutAdded(cut) }
            onPreviewChanged: function(preview) { root.cutPreview = preview }
            onHeaderExpandRequested: root.headerExpandRequested()
        }
    }
}
