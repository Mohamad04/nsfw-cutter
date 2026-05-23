import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Panel {
    id: root

    property bool compactMode: false
    property bool shortMode: false
    property color panelTone: "#0B1324"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property string selectedVideoPath: ""
    property real videoDurationMs: 0

    signal cutAdded(var cut)

    implicitHeight: content.implicitHeight + (root.compactMode ? 24 : 32)
    panelColor: root.panelTone
    strokeColor: "#21324D"

    function setStartTime(timeText) {
        cutForm.setStartTime(timeText)
    }

    function setEndTime(timeText) {
        cutForm.setEndTime(timeText)
    }

    function applyRecommendation(startTime, endTime, reason, tags) {
        cutForm.applyRecommendation(startTime, endTime, reason, tags)
    }

    function addCurrentCut() {
        cutForm.addCurrentCut()
    }

    Flickable {
        id: editorScroll
        anchors.fill: parent
        anchors.margins: root.compactMode ? 12 : 16
        contentWidth: width
        contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.vertical: AppScrollBar {}

        ColumnLayout {
            id: content
            width: editorScroll.width - (editorScroll.contentHeight > editorScroll.height ? 10 : 0)
            spacing: root.compactMode ? 8 : 10

            CutFormEditor {
                id: cutForm
                Layout.fillWidth: true
                spacing: root.compactMode ? 8 : 10
                shortMode: root.shortMode
                textMain: root.textMain
                textMuted: root.textMuted
                accent: root.accent
                selectedVideoPath: root.selectedVideoPath
                videoDurationMs: root.videoDurationMs
                onCutAdded: function(cut) { root.cutAdded(cut) }
            }

            ExportJobSection {
                Layout.fillWidth: true
                textMuted: root.textMuted
                accent: root.accent
            }
        }
    }
}
