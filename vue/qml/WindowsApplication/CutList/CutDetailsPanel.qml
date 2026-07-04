import QtQuick
import QtQuick.Layouts

import "../Shared"
import "../VideoPlayer"

Rectangle {
    id: root

    property bool hasCuts: false
    property bool hasSelection: false
    property bool adjusted: false
    property int selectedIndex: -1
    property string cutTimingMode: "safe"
    property string statusText: "Safe"
    property string requestedStartText: "--"
    property string requestedEndText: "--"
    property string requestedDurationText: "00:00"
    property string requestedDurationEditText: "00:00:00"
    property string safeStartText: "--"
    property string safeEndText: "--"
    property string safeDurationText: "00:00"
    property string startDeltaText: "00:00"
    property string endDeltaText: "00:00"
    property string durationDeltaText: "00:00"
    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property color requestedColor: root.lightMode ? "#D97706" : "#F59E3D"
    property color safeColor: root.lightMode ? "#15803D" : "#86EFAC"
    property var canApplyEdit: null

    signal timingModeSelected(string mode)
    signal requestedTimeEdited(string fieldName, real seconds)
    signal editorDismissRequested()
    signal editorActiveChanged(bool active)

    function localizedStatusText(status) {
        if (status === "Adjusted") return qsTr("Adjusted")
        if (status === "Safe") return qsTr("Safe")
        return status
    }

    radius: 12
    color: root.lightMode ? "#F8FAFC" : "#07101D"
    border.color: root.lightMode ? "#E2E8F0" : "#17263E"

    MouseArea {
        anchors.fill: parent
        enabled: root.hasSelection
        z: 0
        onPressed: root.editorDismissRequested()
    }

    Text {
        anchors.centerIn: parent
        width: parent.width - 28
        visible: root.hasCuts && !root.hasSelection
        text: qsTr("Select a cut to view requested timing and keyframe details.")
        color: root.mutedTextColor
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 9
        visible: root.hasSelection

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 26
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: qsTr("Cut %1 Details").arg(root.selectedIndex + 1)
                color: root.textColor
                font.pixelSize: 14
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            Rectangle {
                Layout.preferredWidth: detailStatusText.implicitWidth + 16
                Layout.preferredHeight: 22
                radius: 11
                color: root.adjusted
                    ? (root.lightMode ? "#FEF3C7" : "#2A160B")
                    : (root.lightMode ? "#DCFCE7" : "#103D22")
                border.color: root.adjusted
                    ? (root.lightMode ? "#F59E0B" : "#F59E3D")
                    : (root.lightMode ? "#22C55E" : "#22B454")

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 4

                    VectorIcon {
                        Layout.preferredWidth: 12
                        Layout.preferredHeight: 12
                        name: root.adjusted ? "warning" : "shield"
                        iconColor: root.adjusted
                            ? (root.lightMode ? "#A16207" : "#FDE68A")
                            : root.safeColor
                    }

                    Text {
                        id: detailStatusText
                        text: root.localizedStatusText(root.statusText)
                        color: root.adjusted
                            ? (root.lightMode ? "#A16207" : "#FDE68A")
                            : root.safeColor
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }
                }
            }
        }

        CutModeControl {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            Layout.alignment: Qt.AlignVCenter

            cutTimingMode: root.cutTimingMode
            lightMode: root.lightMode
            mutedTextColor: root.mutedTextColor

            onTimingModeSelected: function(mode) {
                root.timingModeSelected(mode)
            }
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 4
            columnSpacing: 8
            rowSpacing: 7

            Text { text: ""; Layout.preferredWidth: 54 }
            Text { text: qsTr("Requested"); color: root.requestedColor; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
            Text { text: qsTr("Keyframe Span"); color: root.safeColor; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
            Text { text: qsTr("Delta"); color: root.mutedTextColor; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.preferredWidth: 54; horizontalAlignment: Text.AlignRight }

            Text { text: qsTr("Start"); color: root.mutedTextColor; font.pixelSize: 11 }
            EditableRequestedTime {
                fieldName: "start"
                displayText: root.requestedStartText
                editTextOnStart: root.requestedStartText
                canEdit: root.hasSelection
                lightMode: root.lightMode
                textColor: root.textColor
                requestedColor: root.requestedColor
                accentColor: root.accentColor
                canApplyEdit: root.canApplyEdit
                onEditingChanged: root.editorActiveChanged(editing)
                onRequestedTimeEdited: function(fieldName, seconds) { root.requestedTimeEdited(fieldName, seconds) }
            }
            Text { text: root.safeStartText; color: root.safeColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
            Text { text: root.startDeltaText; color: root.textColor; font.pixelSize: 11; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 54 }

            Text { text: qsTr("End"); color: root.mutedTextColor; font.pixelSize: 11 }
            EditableRequestedTime {
                fieldName: "end"
                displayText: root.requestedEndText
                editTextOnStart: root.requestedEndText
                canEdit: root.hasSelection
                lightMode: root.lightMode
                textColor: root.textColor
                requestedColor: root.requestedColor
                accentColor: root.accentColor
                canApplyEdit: root.canApplyEdit
                onEditingChanged: root.editorActiveChanged(editing)
                onRequestedTimeEdited: function(fieldName, seconds) { root.requestedTimeEdited(fieldName, seconds) }
            }
            Text { text: root.safeEndText; color: root.safeColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
            Text { text: root.endDeltaText; color: root.textColor; font.pixelSize: 11; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 54 }

            Text { text: qsTr("Duration"); color: root.mutedTextColor; font.pixelSize: 11 }
            EditableRequestedTime {
                fieldName: "duration"
                displayText: root.requestedDurationText
                editTextOnStart: root.requestedDurationEditText
                canEdit: root.hasSelection
                lightMode: root.lightMode
                textColor: root.textColor
                requestedColor: root.requestedColor
                accentColor: root.accentColor
                canApplyEdit: root.canApplyEdit
                onEditingChanged: root.editorActiveChanged(editing)
                onRequestedTimeEdited: function(fieldName, seconds) { root.requestedTimeEdited(fieldName, seconds) }
            }
            Text { text: root.safeDurationText; color: root.safeColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
            Text { text: root.durationDeltaText; color: root.textColor; font.pixelSize: 11; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 54 }
        }

        Text {
            Layout.fillWidth: true
            text: root.cutTimingMode === "requested"
                ? qsTr("Fast mode uses the exact requested range for preview and export.")
                : qsTr("Smart mode removes the requested range exactly and only re-encodes boundary video chunks.")
            color: root.mutedTextColor
            font.pixelSize: 11
            wrapMode: Text.WordWrap
        }
    }
}

