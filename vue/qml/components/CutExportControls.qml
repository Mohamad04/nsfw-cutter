import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property string outputDir: ""
    property bool narrowMode: false
    property bool hasSegments: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"

    signal chooseFolderRequested()
    signal exportRemoveRequested()

    implicitHeight: 92
    radius: 10
    color: "#091321"
    border.color: "#243244"
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 6
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            spacing: 6

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 120
                Layout.preferredHeight: 38
                radius: 10
                color: "#050B14"
                border.color: "#142033"

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    text: root.outputDir.length > 0 ? root.outputDir : "Choose an output folder"
                    color: root.outputDir.length > 0 ? root.textMain : root.textMuted
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                    verticalAlignment: Text.AlignVCenter
                }
            }

            AppButton {
                text: "Folder"
                variant: "secondary"
                size: "sm"
                Layout.preferredWidth: root.narrowMode ? 76 : 90
                Layout.preferredHeight: 38
                enabled: !videoCutController.cutBusy
                onClicked: root.chooseFolderRequested()
            }

            AppButton {
                text: "Remove selected intervals"
                variant: "danger"
                size: "sm"
                Layout.preferredWidth: root.narrowMode ? 210 : 300
                Layout.preferredHeight: 40
                enabled: root.hasSegments && !videoCutController.cutBusy
                onClicked: root.exportRemoveRequested()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 16
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "No re-encoding: fast and quality-preserving, but cuts may align to nearby keyframes."
                color: "#FDE68A"
                font.pixelSize: 11
                elide: Text.ElideRight
            }

            Text {
                text: videoCutController.cutProgressValue > 0 && videoCutController.cutBusy ? videoCutController.cutProgressValue + "%" : ""
                color: root.accent
                font.pixelSize: 11
                font.bold: true
                visible: videoCutController.cutBusy
            }
        }

        ProgressBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 6
            visible: videoCutController.cutBusy
            from: 0
            to: 1
            value: videoCutController.cutProgressValue / 100

            background: Rectangle { radius: 3; color: "#111827" }
            contentItem: Item {
                Rectangle {
                    width: parent.width * videoCutController.cutProgressValue / 100
                    height: parent.height
                    radius: 3
                    color: root.accent
                }
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: 14
            text: videoCutController.cutError.length > 0 ? videoCutController.cutError : videoCutController.cutStatus
            color: videoCutController.cutError.length > 0 ? "#FCA5A5" : root.textMuted
            font.pixelSize: 10
            elide: Text.ElideRight
        }
    }
}
