import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    required property int segmentIndex
    required property var startTime
    required property var endTime
    required property var safeStartTime
    required property var safeEndTime
    required property var extraBefore
    required property var extraAfter
    required property var cutType
    required property var reason
    required property var tags
    required property var source
    required property var score
    required property var status
    property bool narrowMode: false
    property bool compactTable: false
    property bool selected: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int indexColumnWidth: 44
    property int timeColumnWidth: 125
    property int durationColumnWidth: 135
    property int extraColumnWidth: 150
    property int statusColumnWidth: 62
    property int jumpButtonWidth: 58
    property int editButtonWidth: 52
    property int deleteButtonWidth: 68

    signal selectedRequested()
    signal removeRequested()
    signal editRequested()
    signal previewRequested()
    signal jumpStartRequested()
    signal jumpEndRequested()

    height: root.narrowMode ? 82 : 38
    color: root.selected ? "#102A43" : "#0B1324"
    border.color: root.selected ? root.accent : "#142033"

    function parseSeconds(value) {
        var parts = String(value).split(":")
        if (parts.length !== 3) return 0
        return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])
    }

    function durationText() {
        var totalSeconds = Math.max(0, Math.round(parseSeconds(root.safeEndTime) - parseSeconds(root.safeStartTime)))
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var seconds = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
    }

    MouseArea {
        anchors.fill: parent
        onClicked: root.selectedRequested()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: root.compactTable ? 6 : 8
        visible: !root.narrowMode

        Text { text: root.segmentIndex; color: root.textMain; font.pixelSize: 11; Layout.preferredWidth: root.indexColumnWidth; Layout.minimumWidth: 0 }
        Text { text: root.startTime; color: root.textMain; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.endTime; color: root.textMain; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.safeStartTime; color: "#FED7AA"; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.safeEndTime; color: "#FED7AA"; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.durationText(); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.durationColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: "-" + root.extraBefore + ", +" + root.extraAfter; color: "#FDE68A"; font.pixelSize: 11; Layout.preferredWidth: root.extraColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.reason; color: "#E5E7EB"; font.pixelSize: 11; Layout.fillWidth: true; Layout.minimumWidth: 56; elide: Text.ElideRight }
        Text { text: root.status; color: root.status === "Warning" ? "#FDE68A" : "#86EFAC"; font.pixelSize: 11; Layout.preferredWidth: root.statusColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }

        AppButton { text: "Jump"; variant: "secondary"; size: "sm"; Layout.preferredWidth: root.jumpButtonWidth; Layout.minimumWidth: 0; onClicked: root.jumpStartRequested() }
        AppButton { text: "Edit"; variant: "ghost"; size: "sm"; Layout.preferredWidth: root.editButtonWidth; Layout.minimumWidth: 0; onClicked: root.editRequested() }
        AppButton { text: "Delete"; variant: "danger"; size: "sm"; Layout.preferredWidth: root.deleteButtonWidth; Layout.minimumWidth: 0; onClicked: root.removeRequested() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4
        visible: root.narrowMode

        Text {
            Layout.fillWidth: true
            text: "#" + root.segmentIndex + "  Requested " + root.startTime + " -> " + root.endTime + "  Safe " + root.safeStartTime + " -> " + root.safeEndTime
            color: root.textMain
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            text: "Extra -" + root.extraBefore + ", +" + root.extraAfter + " | " + root.reason + " | " + root.tags + " | " + root.status
            color: root.textMuted
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            AppButton { text: "Jump"; variant: "secondary"; size: "sm"; Layout.fillWidth: true; onClicked: root.jumpStartRequested() }
            AppButton { text: "Edit"; variant: "ghost"; size: "sm"; Layout.fillWidth: true; onClicked: root.editRequested() }
            AppButton { text: "Delete"; variant: "danger"; size: "sm"; Layout.fillWidth: true; onClicked: root.removeRequested() }
        }
    }
}
