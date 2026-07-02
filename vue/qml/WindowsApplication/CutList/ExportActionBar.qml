pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

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

    radius: 14
    color: root.lightMode ? root.panelColor : "#081321"
    border.color: root.lightMode ? root.strokeColor : "#223754"
    clip: true

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 13
        color: "transparent"
        border.color: root.lightMode ? "#FFFFFF" : "#163456"
        opacity: root.lightMode ? 0.36 : 0.42
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
            color: root.lightMode ? "#F8FAFC" : "#06101D"
            border.color: root.lightMode ? "#DCE4EF" : "#1C3150"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8

                VectorIcon {
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                    name: "folder"
                    iconColor: root.outputDir.length > 0 ? root.accentColor : root.mutedTextColor
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
            iconName: "folder"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: !videoCutController.cutBusy
            Layout.preferredWidth: 122
            Layout.preferredHeight: 40
            onClicked: root.chooseFolderRequested()
        }

        AppButton {
            text: "Preview Cuts"
            iconName: "eye"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: false
            Layout.preferredWidth: 144
            Layout.preferredHeight: 40
            ToolTip.visible: hovered
            ToolTip.text: root.hasCuts
                ? "Previewing the final all-cuts output is not connected yet"
                : "Add at least one cut to preview"
        }

        AppButton {
            text: "Export Clean Video"
            iconName: "export"
            variant: "success"
            size: "sm"
            lightMode: root.lightMode
            enabled: root.hasVideo && root.hasCuts && !videoCutController.cutBusy
            Layout.preferredWidth: 196
            Layout.preferredHeight: 40
            onClicked: root.exportCleanVideoRequested()
        }
    }
}

