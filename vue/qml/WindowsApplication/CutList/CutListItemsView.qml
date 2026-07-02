pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

import "../Shared"

Rectangle {
    id: root

    required property var cutsModel
    property int selectedIndex: -1
    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property var statusTextForCut: null
    property var durationSecondsForCut: null
    property var formatCompact: null

    signal cutSelected(int index)
    signal cutRemoveRequested(int index)
    signal editorDismissRequested()

    radius: 12
    color: root.lightMode ? "#F8FAFC" : "#050B14"
    border.color: root.lightMode ? "#E2E8F0" : "#17263E"
    clip: true

    function rowStatus(cut) {
        return root.statusTextForCut !== null ? root.statusTextForCut(cut) : "Safe"
    }

    function rowDurationText(cut) {
        var seconds = root.durationSecondsForCut !== null ? root.durationSecondsForCut(cut) : 0
        return root.formatCompact !== null ? root.formatCompact(seconds) : "00:00"
    }

    CutListEmptyState {
        anchors.centerIn: parent
        width: parent.width - 32
        visible: root.cutsModel.count === 0
        lightMode: root.lightMode
        textColor: root.textColor
        mutedTextColor: root.mutedTextColor
    }

    ListView {
        id: cutListView

        anchors.fill: parent
        anchors.margins: 8
        visible: root.cutsModel.count > 0
        model: root.cutsModel
        spacing: 7
        clip: true
        ScrollBar.vertical: AppScrollBar { lightMode: root.lightMode }

        delegate: CutListItem {
            id: rowItem

            required property int index
            required property var start
            required property var end
            readonly property var rowCut: root.cutsModel.get(index)

            width: cutListView.width - 4
            rowIndex: index
            startTime: String(start)
            endTime: String(end)
            rowStatus: root.rowStatus(rowCut)
            rowDurationText: root.rowDurationText(rowCut)
            selected: root.selectedIndex === index
            lightMode: root.lightMode
            textColor: root.textColor
            mutedTextColor: root.mutedTextColor
            accentColor: root.accentColor
            onCutSelected: function(index) { root.cutSelected(index) }
            onRemoveRequested: function(index) { root.cutRemoveRequested(index) }
            onEditorDismissRequested: root.editorDismissRequested()
        }
    }
}

