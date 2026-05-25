import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property bool lightMode: false
    property bool shortMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int scrollbarGutter: 14

    radius: 14
    color: root.lightMode ? "#FFFFFF" : "#08111F"
    border.color: root.lightMode ? "#CBD5E1" : "#1F2F4A"
    clip: true

    function formatBytes(bytes) {
        var value = Number(bytes)
        if (!Number.isFinite(value) || value <= 0) return "--"
        var units = ["B", "KB", "MB", "GB", "TB"]
        var index = 0
        while (value >= 1024 && index < units.length - 1) {
            value = value / 1024
            index += 1
        }
        return value.toFixed(index === 0 ? 0 : 1) + " " + units[index]
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 2

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: "FOUND VIDEOS IN FOLDER"
                        color: root.accent
                        font.pixelSize: 15
                        font.bold: true
                        font.letterSpacing: 0.8
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                    }

                    Text {
                        text: appController.availableVideos.length
                        color: root.textMuted
                        font.pixelSize: 12
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: appController.currentFolder.length > 0 ? appController.currentFolder : "Choose a video folder"
                    color: root.textMuted
                    font.pixelSize: 10
                    elide: Text.ElideMiddle
                    visible: !root.shortMode
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 10
            color: root.lightMode ? "#F8FAFC" : "#050B14"
            border.color: root.lightMode ? "#E2E8F0" : "#142033"
            clip: true

            Text {
                anchors.centerIn: parent
                visible: appController.availableVideos.length === 0
                text: appController.currentFolder.length > 0 ? "No videos found" : "No folder selected"
                color: root.textMuted
                font.pixelSize: 12
            }

            ListView {
                id: availableVideosListView
                anchors.fill: parent
                visible: appController.availableVideos.length > 0
                model: appController.availableVideos
                clip: true
                spacing: 2
                ScrollBar.vertical: AppScrollBar { lightMode: root.lightMode }

                delegate: Rectangle {
                    id: videoDelegate

                    required property int index
                    required property var modelData

                    width: availableVideosListView.width - root.scrollbarGutter
                    height: root.shortMode ? 56 : 68
                    radius: 8
                    color: root.lightMode ? (videoDelegate.modelData.path === appController.selectedVideoPath ? "#EFF6FF" : "#FFFFFF") : (videoDelegate.modelData.path === appController.selectedVideoPath ? "#102A43" : (videoDelegate.index % 2 === 0 ? "#0B1324" : "#0E1728"))
                    border.color: root.lightMode ? (videoDelegate.modelData.path === appController.selectedVideoPath ? "#60A5FA" : "#E2E8F0") : (videoDelegate.modelData.path === appController.selectedVideoPath ? root.accent : "#142033")

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 8
                        spacing: 10

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3

                            Text {
                                text: videoDelegate.modelData.name
                                color: root.textMain
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            Text {
                                text: videoDelegate.modelData.path
                                color: root.textMuted
                                font.pixelSize: 11
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                visible: !root.shortMode

                                Text {
                                    text: (videoDelegate.modelData.extension || "").toUpperCase().replace(".", "") + " - " + root.formatBytes(videoDelegate.modelData.file_size_bytes)
                                    color: root.lightMode ? "#475569" : "#CBD5E1"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                    Layout.preferredWidth: 82
                                }

                                Rectangle {
                                    Layout.preferredWidth: 1
                                    Layout.preferredHeight: 12
                                    color: root.lightMode ? "#E5EAF2" : "#243244"
                                }

                                Text {
                                    text: videoDelegate.modelData.subtitle_found ? "Subtitle: " + videoDelegate.modelData.subtitle_name : "No subtitle"
                                    color: videoDelegate.modelData.subtitle_found ? (root.lightMode ? "#16A34A" : "#86EFAC") : root.textMuted
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        AppButton {
                            text: "Load"
                            variant: "primary"
                            size: "sm"
                            lightMode: root.lightMode
                            Layout.preferredWidth: 56
                            onClicked: appController.selectAvailableVideo(videoDelegate.index)
                        }
                    }
                }
            }
        }
    }
}
