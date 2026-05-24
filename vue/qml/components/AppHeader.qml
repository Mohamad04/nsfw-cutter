import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    property bool compactMode: false
    property bool headerCollapsed: false
    property bool narrowMode: false
    property url appIconSource: Qt.resolvedUrl("../../../assets/icons/app.png")
    property color panelColor: "#0B1324"
    property color strokeColor: "#1F2F4A"
    property color textColor: "#F8FAFC"
    property color mutedTextColor: "#94A3B8"
    property color accentColor: "#38BDF8"
    readonly property int expandedHeaderHeight: 72
    readonly property int collapsedHeaderHeight: 0
    readonly property int preferredHeaderHeight: root.headerCollapsed ? root.collapsedHeaderHeight : root.expandedHeaderHeight

    signal folderRequested()
    signal clearRequested()
    signal settingsClicked()

    implicitHeight: root.preferredHeaderHeight
    implicitWidth: 1200

    Behavior on height {
        NumberAnimation {
            duration: 160
            easing.type: Easing.OutCubic
        }
    }

    Panel {
        id: expandedHeader

        anchors.fill: parent
        panelColor: root.panelColor
        strokeColor: root.strokeColor
        visible: !root.headerCollapsed
        opacity: root.headerCollapsed ? 0 : 1

        Behavior on opacity {
            NumberAnimation {
                duration: 120
                easing.type: Easing.OutQuad
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: root.compactMode ? 10 : 12

            Image {
                source: root.appIconSource
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                Layout.preferredWidth: root.compactMode ? 40 : 44
                Layout.preferredHeight: root.compactMode ? 40 : 44
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

            AppButton {
                text: "▲"
                variant: "ghost"
                size: "icon"
                Layout.preferredWidth: root.compactMode ? 44 : 48
                Layout.preferredHeight: root.compactMode ? 44 : 48
                ToolTip.visible: hovered
                ToolTip.text: "Collapse header"
                onClicked: root.headerCollapsed = true
            }
        }
    }

}
