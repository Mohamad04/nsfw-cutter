pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "exportActionBar"

    property string outputDir: ""
    property bool lightMode: false
    property bool hasVideo: false
    property bool hasCuts: false
    property color panelColor: "#0C1625"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"

    signal chooseFolderRequested()
    signal exportCleanVideoRequested()

    radius: 10
    color: root.panelColor
    border.color: root.strokeColor
    clip: true

    AppTheme { id: theme }

    function statusText() {
        if (videoCutController.cutBusy) return videoCutController.cutStatus
        if (videoCutController.cutError.length > 0) return videoCutController.cutError
        if (videoCutController.cutWarning.length > 0) return videoCutController.cutWarning
        if (!root.hasVideo) return "Open a video to export"
        if (!root.hasCuts) return "Add at least one cut to export"
        return "Ready to export"
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 10

        Text {
            text: "Output Folder"
            color: root.textColor
            font.pixelSize: 12
            font.weight: Font.DemiBold
            Layout.preferredWidth: 96
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.minimumWidth: 180
            Layout.preferredHeight: 42
            radius: 11
            color: root.lightMode ? "#F8FAFC" : "#081321"
            border.color: root.lightMode ? "#DCE4EF" : "#1B2B45"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8

                Text {
                    text: "Dir"
                    color: root.mutedTextColor
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    verticalAlignment: Text.AlignVCenter
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: root.outputDir.length > 0 ? root.outputDir : "Choose an output folder"
                    color: root.outputDir.length > 0 ? root.textColor : root.mutedTextColor
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }

        AppButton {
            text: "Change..."
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: !videoCutController.cutBusy
            Layout.preferredWidth: 94
            Layout.preferredHeight: 40
            onClicked: root.chooseFolderRequested()
        }

        ColumnLayout {
            Layout.preferredWidth: 170
            Layout.minimumWidth: 130
            spacing: 3

            Text {
                Layout.fillWidth: true
                text: root.statusText()
                color: videoCutController.cutError.length > 0
                    ? (root.lightMode ? theme.lightDanger : theme.darkDanger)
                    : root.mutedTextColor
                font.pixelSize: 11
                elide: Text.ElideRight
            }

            ProgressBar {
                Layout.fillWidth: true
                Layout.preferredHeight: 5
                visible: videoCutController.cutBusy
                from: 0
                to: 1
                value: videoCutController.cutProgressValue / 100

                background: Rectangle {
                    radius: 3
                    color: root.lightMode ? "#E2E8F0" : "#111827"
                }

                contentItem: Item {
                    Rectangle {
                        width: parent.width * videoCutController.cutProgressValue / 100
                        height: parent.height
                        radius: 3
                        color: root.accentColor
                    }
                }
            }
        }

        AppButton {
            text: "Preview Cuts"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: false
            Layout.preferredWidth: 120
            Layout.preferredHeight: 40
            ToolTip.visible: hovered
            ToolTip.text: root.hasCuts
                ? "Previewing the final all-cuts output is not connected yet"
                : "Add at least one cut to preview"
        }

        AppButton {
            text: "Export Clean Video"
            variant: "success"
            size: "sm"
            lightMode: root.lightMode
            enabled: root.hasVideo && root.hasCuts && !videoCutController.cutBusy
            Layout.preferredWidth: 172
            Layout.preferredHeight: 40
            onClicked: root.exportCleanVideoRequested()
        }
    }
}
