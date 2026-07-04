import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../Shared"

Rectangle {
    id: root

    required property int rowIndex
    required property string startTime
    required property string endTime
    required property string rowStatus
    required property string rowDurationText
    property bool selected: false
    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property color safeColor: root.lightMode ? "#15803D" : "#86EFAC"

    signal cutSelected(int index)
    signal removeRequested(int index)
    signal editorDismissRequested()

    function localizedStatusText(status) {
        if (status === "Adjusted") return qsTr("Adjusted")
        if (status === "Safe") return qsTr("Safe")
        return status
    }

    height: 72
    radius: 10
    color: root.selected
        ? (root.lightMode ? "#EFF6FF" : "#102A43")
        : (rowMouse.containsMouse ? (root.lightMode ? "#FFFFFF" : "#0B1324") : "transparent")
    border.color: root.selected
        ? root.accentColor
        : (rowMouse.containsMouse ? (root.lightMode ? "#CBD5E1" : "#243244") : "transparent")
    border.width: root.selected || rowMouse.containsMouse ? 1 : 0

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: root.accentColor
        opacity: root.selected ? 0.08 : 0
    }

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 3
        radius: 2
        color: root.accentColor
        visible: root.selected
    }

    MouseArea {
        id: rowMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onPressed: root.editorDismissRequested()
        onClicked: root.cutSelected(root.rowIndex)
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 8
        spacing: 8

        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 5

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: qsTr("Cut %1").arg(root.rowIndex + 1)
                    color: root.textColor
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                Rectangle {
                    Layout.preferredWidth: rowStatusText.implicitWidth + 34
                    Layout.preferredHeight: 22
                    radius: 11
                    color: root.rowStatus === "Adjusted"
                        ? (root.lightMode ? "#FEF3C7" : "#2A160B")
                        : (root.lightMode ? "#DCFCE7" : "#103D22")
                    border.color: root.rowStatus === "Adjusted"
                        ? (root.lightMode ? "#F59E0B" : "#F59E3D")
                        : (root.lightMode ? "#22C55E" : "#22B454")

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: 4

                        VectorIcon {
                            Layout.preferredWidth: 12
                            Layout.preferredHeight: 12
                            name: root.rowStatus === "Adjusted" ? "warning" : "shield"
                            iconColor: root.rowStatus === "Adjusted"
                                ? (root.lightMode ? "#A16207" : "#FDE68A")
                                : root.safeColor
                        }

                        Text {
                            id: rowStatusText
                            text: root.localizedStatusText(root.rowStatus)
                            color: root.rowStatus === "Adjusted"
                                ? (root.lightMode ? "#A16207" : "#FDE68A")
                                : root.safeColor
                            font.pixelSize: 10
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: root.startTime + " -> " + root.endTime
                    color: root.mutedTextColor
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }

                Text {
                    text: root.rowDurationText
                    color: root.textColor
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignRight
                }
            }
        }

        AppButton {
            text: ""
            iconName: "trash"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            Layout.preferredWidth: 38
            Layout.preferredHeight: 32
            ToolTip.visible: hovered
            ToolTip.text: qsTr("Delete cut")
            onPressed: root.editorDismissRequested()
            onClicked: root.removeRequested(root.rowIndex)
        }
    }
}

