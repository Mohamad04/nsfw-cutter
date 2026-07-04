import QtQuick
import QtQuick.Layouts
import "../Shared"

Rectangle {
    id: root

    property bool valid: false
    property string requestedStart: "00:00:00"
    property string requestedEnd: "00:00:00"
    property string safeStart: "00:00:00"
    property string safeEnd: "00:00:00"
    property string previousKeyframeStart: "00:00:00"
    property string nextKeyframeStart: "00:00:00"
    property string previousKeyframeEnd: "00:00:00"
    property string nextKeyframeEnd: "00:00:00"
    property string extraBefore: "0.0s"
    property string extraAfter: "0.0s"
    property string errorText: ""
    property bool lightMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"

    Layout.fillWidth: true
    Layout.preferredHeight: 140
    Layout.minimumHeight: 120
    radius: 12
    color: root.lightMode ? "#FFFBEB" : "#07111E"
    border.color: root.lightMode ? "#FCD34D" : (root.valid ? "#9A3412" : "#243244")
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: qsTr("Smart boundary keyframes")
                color: root.lightMode ? "#92400E" : root.textMain
                font.pixelSize: 12
                font.bold: true
                elide: Text.ElideRight
            }

            Rectangle {
                Layout.preferredWidth: 92
                Layout.preferredHeight: 22
                radius: 11
                color: root.lightMode ? "#FEF3C7" : "#2A160B"
                border.color: root.lightMode ? "#F59E0B" : "#F97316"

                Text {
                    anchors.centerIn: parent
                    text: qsTr("boundary")
                    color: root.lightMode ? "#B45309" : "#FDBA74"
                    font.pixelSize: 10
                    font.bold: true
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Rectangle { Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4; color: root.lightMode ? "#0284C7" : root.accent }
            Text {
                Layout.fillWidth: true
                text: qsTr("Requested: %1 -> %2").arg(root.requestedStart).arg(root.requestedEnd)
                color: root.lightMode ? "#78350F" : root.textMain
                font.pixelSize: 11
                elide: Text.ElideRight
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Rectangle { Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4; color: "#F97316" }
            Text {
                Layout.fillWidth: true
                text: qsTr("Boundary span: %1 -> %2").arg(root.safeStart).arg(root.safeEnd)
                color: root.lightMode ? "#B45309" : "#FED7AA"
                font.pixelSize: 11
                font.bold: true
                elide: Text.ElideRight
            }
        }

        Text {
            Layout.fillWidth: true
            text: qsTr("Boundary video: -%1 before, +%2 after").arg(root.extraBefore).arg(root.extraAfter)
            color: root.lightMode ? "#A16207" : "#FDE68A"
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            text: qsTr("Start keyframes: prev %1 | next %2").arg(root.previousKeyframeStart).arg(root.nextKeyframeStart)
            color: root.lightMode ? "#A16207" : root.textMuted
            font.pixelSize: 10
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            text: qsTr("End keyframes: prev %1 | next %2").arg(root.previousKeyframeEnd).arg(root.nextKeyframeEnd)
            color: root.lightMode ? "#A16207" : root.textMuted
            font.pixelSize: 10
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            text: root.valid ? qsTr("Smart export removes the requested range exactly.") : root.errorText
            color: root.lightMode ? (root.valid ? "#A16207" : "#DC2626") : (root.valid ? "#FDE68A" : "#FCA5A5")
            font.pixelSize: 10
            elide: Text.ElideRight
        }
    }
}

