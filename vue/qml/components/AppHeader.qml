import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Panel {
    id: root

    property bool compactMode: false
    property bool narrowMode: false
    property color textColor: "#F8FAFC"
    property color mutedTextColor: "#94A3B8"
    property color accentColor: "#38BDF8"

    signal folderRequested()
    signal clearRequested()
    signal settingsClicked()

    strokeColor: "#1F2F4A"

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: root.compactMode ? 10 : 12

        Rectangle {
            Layout.preferredWidth: root.compactMode ? 42 : 46
            Layout.preferredHeight: root.compactMode ? 42 : 46
            radius: 13
            color: "#0B2038"
            border.color: "#1E9BFF"

            Text {
                anchors.centerIn: parent
                text: "CUT"
                color: root.accentColor
                font.pixelSize: 10
                font.bold: true
            }
        }

        Text {
            text: "NSFW Cutter"
            color: root.textColor
            font.pixelSize: root.compactMode ? 17 : 20
            font.bold: true
            visible: !root.narrowMode
            Layout.preferredWidth: root.compactMode ? 150 : 170
        }

        AppButton {
            text: "Folder"
            variant: "primary"
            size: "md"
            Layout.preferredWidth: root.compactMode ? 110 : 130
            onClicked: root.folderRequested()
        }

        AppButton {
            text: "Clear"
            variant: "secondary"
            size: "md"
            Layout.preferredWidth: root.compactMode ? 96 : 110
            onClicked: root.clearRequested()
        }

        Rectangle {
            Layout.preferredHeight: root.compactMode ? 42 : 46
            Layout.fillWidth: true
            radius: 18
            color: "#0A1120"
            border.color: "#243244"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8

                Text {
                    text: appController.videoName
                    color: "#DDE7F6"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 18
                    color: "#243244"
                    visible: !root.narrowMode
                }

                Text {
                    text: appController.subtitleStatus
                    color: "#86EFAC"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    Layout.preferredWidth: root.compactMode ? 250 : 290
                    visible: !root.narrowMode
                }
            }
        }

        Rectangle {
            Layout.preferredHeight: root.compactMode ? 38 : 40
            Layout.preferredWidth: root.compactMode ? 150 : 165
            radius: 16
            color: "#103D22"
            border.color: "#1B6F3A"

            Text {
                anchors.centerIn: parent
                text: appController.projectStatus
                color: "#86EFAC"
                font.pixelSize: 12
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                width: parent.width - 16
                horizontalAlignment: Text.AlignHCenter
            }
        }

        AppButton {
            text: "⚙"
            variant: "ghost"
            size: "icon"
            Layout.preferredWidth: root.compactMode ? 52 : 56
            Layout.preferredHeight: root.compactMode ? 52 : 56
            ToolTip.visible: hovered
            ToolTip.text: "Settings"
            onClicked: root.settingsClicked()
        }
    }
}
