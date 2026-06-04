pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import "../components"

Item {
    id: root

    signal settingsRequested()

    property bool darkMode: settingsController.theme !== "light"
    property bool lightMode: !root.darkMode
    property color pageBg: root.darkMode ? theme.darkAppBg : theme.lightAppBg
    property color surface: root.darkMode ? theme.darkSurface : theme.lightSurface
    property color videoSurface: root.darkMode ? theme.darkVideoSurface : theme.lightVideoSurface
    property color borderColor: root.darkMode ? theme.darkBorder : theme.lightBorder
    property color textMain: root.darkMode ? theme.darkTextPrimary : theme.lightTextPrimary
    property color textMuted: root.darkMode ? theme.darkTextMuted : theme.lightTextMuted

    AppTheme { id: theme }

    Rectangle {
        anchors.fill: parent
        color: root.pageBg

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            CompactAppHeader {
                Layout.fillWidth: true
                Layout.preferredHeight: 76
                lightMode: root.lightMode
                panelColor: root.surface
                strokeColor: root.borderColor
                textColor: root.textMain
                mutedTextColor: root.textMuted
                accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                onSettingsRequested: root.settingsRequested()
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 10
                    color: root.videoSurface
                    border.color: root.borderColor

                    Text {
                        anchors.centerIn: parent
                        text: "Video workspace placeholder"
                        color: root.textMain
                        font.pixelSize: 22
                        font.bold: true
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 320
                    Layout.minimumWidth: 260
                    Layout.maximumWidth: 360
                    Layout.fillHeight: true
                    radius: 10
                    color: root.surface
                    border.color: root.borderColor

                    Text {
                        anchors.centerIn: parent
                        text: "Cut list placeholder"
                        color: root.textMain
                        font.pixelSize: 16
                        font.bold: true
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                radius: 10
                color: root.surface
                border.color: root.borderColor

                Text {
                    anchors.centerIn: parent
                    text: "Export/actions bar placeholder"
                    color: root.textMuted
                    font.pixelSize: 16
                }
            }
        }
    }
}
