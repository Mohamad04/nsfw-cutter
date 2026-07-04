import QtQuick
import QtQuick.Layouts
import "../Shared"

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
    property bool lightMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property color requestedColor: root.lightMode ? "#F07818" : "#F59E3D"
    property color safeColor: root.lightMode ? "#1FA34A" : "#8AE6A2"
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
    color: root.lightMode ? (root.selected ? "#EFF6FF" : "#FFFFFF") : (root.selected ? "#102A43" : "#0B1324")
    border.color: root.lightMode ? (root.selected ? "#60A5FA" : "#E2E8F0") : (root.selected ? root.accent : "#142033")

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

    function localizedStatusText(status) {
        if (status === "Warning") return qsTr("Warning")
        if (status === "Failed") return qsTr("Failed")
        if (status === "Safe unavailable") return qsTr("Safe unavailable")
        if (status === "Exporting") return qsTr("Exporting")
        if (status === "Done") return qsTr("Done")
        if (status === "Pending") return qsTr("Pending")
        return status
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
        Text { text: root.localizedStatusText(root.status); color: root.status === "Warning" ? (root.lightMode ? "#A16207" : "#FDE68A") : (root.status === "Failed" || root.status === "Safe unavailable" ? (root.lightMode ? "#DC2626" : "#FCA5A5") : (root.lightMode ? "#15803D" : "#8AE6A2")); font.pixelSize: 11; Layout.preferredWidth: root.statusColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.startTime; color: root.requestedColor; font.pixelSize: 11; font.bold: true; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.endTime; color: root.requestedColor; font.pixelSize: 11; font.bold: true; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.safeStartTime; color: root.safeColor; font.pixelSize: 11; font.bold: true; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.safeEndTime; color: root.safeColor; font.pixelSize: 11; font.bold: true; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Text { text: root.durationText(); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.durationColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
        Item { Layout.fillWidth: true; Layout.minimumWidth: root.extraColumnWidth }

        AppButton { text: qsTr("Jump"); variant: "secondary"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: root.jumpButtonWidth; Layout.minimumWidth: 0; onClicked: root.jumpStartRequested() }
        AppButton { text: qsTr("Edit"); variant: "ghost"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: root.editButtonWidth; Layout.minimumWidth: 0; onClicked: root.editRequested() }
        AppButton { text: qsTr("Delete"); variant: "danger"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: root.deleteButtonWidth; Layout.minimumWidth: 0; onClicked: root.removeRequested() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4
        visible: root.narrowMode

        Text {
            Layout.fillWidth: true
            text: qsTr("#%1  %2  Requested %3 -> %4  Safe %5 -> %6")
                .arg(root.segmentIndex)
                .arg(root.localizedStatusText(root.status))
                .arg(root.startTime)
                .arg(root.endTime)
                .arg(root.safeStartTime)
                .arg(root.safeEndTime)
            color: root.textMain
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            text: qsTr("Removed %1 | %2 | %3").arg(root.durationText()).arg(root.reason).arg(root.tags)
            color: root.textMuted
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            AppButton { text: qsTr("Jump"); variant: "secondary"; size: "sm"; lightMode: root.lightMode; Layout.fillWidth: true; onClicked: root.jumpStartRequested() }
            AppButton { text: qsTr("Edit"); variant: "ghost"; size: "sm"; lightMode: root.lightMode; Layout.fillWidth: true; onClicked: root.editRequested() }
            AppButton { text: qsTr("Delete"); variant: "danger"; size: "sm"; lightMode: root.lightMode; Layout.fillWidth: true; onClicked: root.removeRequested() }
        }
    }
}

