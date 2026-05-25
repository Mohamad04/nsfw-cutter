import QtQuick
import QtQuick.Layouts

Panel {
    id: root

    required property var cutsModel
    property bool compactMode: false
    property bool lightMode: false
    property bool narrowMode: false
    property bool shortMode: false
    property color panelTone: "#0B1324"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int scrollbarGutter: 14
    property int selectedCutIndex: -1
    property real videoDurationMs: 0
    property real videoPositionMs: 0
    readonly property int sidePanelWidth: root.narrowMode ? 280 : (root.compactMode ? 320 : 360)

    signal editRequested(string startTime, string endTime, string reason, string tags)
    signal previewRequested(string startTime)
    signal jumpRequested(string timeText)
    signal cutSelected(int index)
    signal suggestedCutAdded(string startTime, string endTime, string reason, string tags, string score)
    signal importRequested()
    signal exportRequested()
    signal fastExportAllRequested(string outputDir, string exportMode)

    panelColor: root.panelTone
    strokeColor: root.lightMode ? "#CBD5E1" : "#21324D"

    RowLayout {
        anchors.fill: parent
        anchors.margins: 0
        spacing: root.compactMode ? 8 : 10

        ColumnLayout {
            Layout.preferredWidth: root.sidePanelWidth
            Layout.minimumWidth: root.narrowMode ? 250 : 300
            Layout.maximumWidth: root.narrowMode ? 300 : 380
            Layout.fillHeight: true
            spacing: root.compactMode ? 8 : 10

            FoundVideosPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: root.shortMode ? 112 : 160
                lightMode: root.lightMode
                shortMode: root.shortMode
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                scrollbarGutter: root.scrollbarGutter
            }

            AiPicksPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: root.shortMode ? 112 : 160
                lightMode: root.lightMode
                narrowMode: root.narrowMode
                shortMode: root.shortMode
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                scrollbarGutter: root.scrollbarGutter
                onEditRequested: function(startTime, endTime, reason, tags) {
                    root.editRequested(startTime, endTime, reason, tags)
                }
                onAddRequested: function(startTime, endTime, reason, tags, score) {
                    root.suggestedCutAdded(startTime, endTime, reason, tags, score)
                }
            }
        }

        CutListPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: root.shortMode ? 250 : 340
            cutsModel: root.cutsModel
            lightMode: root.lightMode
            shortMode: root.shortMode
            selectedIndex: root.selectedCutIndex
            durationMs: root.videoDurationMs
            videoPositionMs: root.videoPositionMs
            narrowMode: root.narrowMode
            textMain: root.textMain
            textMuted: root.textMuted
            accent: root.accent
            scrollbarGutter: root.scrollbarGutter
            onImportRequested: root.importRequested()
            onExportRequested: root.exportRequested()
            onCutSelected: function(index) { root.cutSelected(index) }
            onEditCutRequested: function(startTime, endTime, reason, tags) {
                root.editRequested(startTime, endTime, reason, tags)
            }
            onPreviewCutRequested: function(startTime) { root.previewRequested(startTime) }
            onJumpCutRequested: function(timeText) { root.jumpRequested(timeText) }
            onFastExportAllRequested: function(outputDir, exportMode) {
                root.fastExportAllRequested(outputDir, exportMode)
            }
        }
    }
}
