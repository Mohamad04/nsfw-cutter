import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    property bool compactMode: false
    property bool headerCollapsed: false
    property bool lightMode: false
    property bool narrowMode: false
    property url appIconSource: Qt.resolvedUrl("../../../assets/icons/app.png")
    property color panelColor: "#0B1324"
    property color strokeColor: "#1F2F4A"
    property color textColor: "#F8FAFC"
    property color mutedTextColor: "#94A3B8"
    property color accentColor: "#38BDF8"
    readonly property int expandedHeaderHeight: 76
    readonly property int collapsedHeaderHeight: 0
    readonly property int preferredHeaderHeight: root.headerCollapsed ? root.collapsedHeaderHeight : root.expandedHeaderHeight

    signal openFileRequested()
    signal openFilesRequested()
    signal openFolderRequested()
    signal recentFileRequested(string path)
    signal clearRecentFilesRequested()
    signal clearRequested()
    signal settingsClicked()

    AppTheme { id: theme }

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
            anchors.leftMargin: root.compactMode ? 14 : 18
            anchors.rightMargin: 14
            anchors.topMargin: 10
            anchors.bottomMargin: 10
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
                id: mediaButton

                text: "Media v"
                variant: "primary"
                size: "md"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 110 : 130
                onClicked: mediaMenu.showAt(mediaButton)
            }

            Rectangle {
                Layout.preferredHeight: root.compactMode ? 42 : 46
                Layout.fillWidth: true
                radius: 16
                color: root.lightMode ? theme.lightSurfaceAlt : "#0A1120"
                border.color: root.lightMode ? theme.lightBorder : "#243244"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 8

                    Text {
                        text: appController.videoName
                        color: root.lightMode ? theme.lightTextPrimary : "#DDE7F6"
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 18
                        color: root.lightMode ? theme.lightDivider : "#243244"
                        visible: !root.narrowMode
                    }

                    Rectangle {
                        Layout.preferredWidth: root.compactMode ? 250 : 290
                        Layout.preferredHeight: 28
                        radius: 12
                        visible: !root.narrowMode
                        color: root.lightMode ? "#ECFDF5" : "#103D22"
                        border.color: root.lightMode ? "#BBF7D0" : "#1B6F3A"

                        Text {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            text: appController.subtitleStatus
                            color: root.lightMode ? "#15803D" : "#86EFAC"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }

            Rectangle {
                Layout.preferredHeight: root.compactMode ? 38 : 40
                Layout.preferredWidth: root.compactMode ? 150 : 165
                radius: 16
                color: root.lightMode ? theme.lightSuccessSoft : "#103D22"
                border.color: root.lightMode ? "#86EFAC" : "#1B6F3A"

                Text {
                    anchors.centerIn: parent
                    text: appController.projectStatus
                    color: root.lightMode ? "#166534" : "#86EFAC"
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
                lightMode: root.lightMode
                Layout.preferredWidth: 52
                Layout.preferredHeight: 52
                ToolTip.visible: hovered
                ToolTip.text: "Settings"
                onClicked: root.settingsClicked()
            }

            AppButton {
                text: "▲"
                variant: "ghost"
                size: "icon"
                lightMode: root.lightMode
                Layout.preferredWidth: 52
                Layout.preferredHeight: 52
                ToolTip.visible: hovered
                ToolTip.text: "Collapse header"
                onClicked: root.headerCollapsed = true
            }
        }
    }

    HeaderMediaMenu {
        id: mediaMenu

        lightMode: root.lightMode
        textColor: root.textColor
        mutedTextColor: root.mutedTextColor
        accentColor: root.accentColor
        recentFiles: appController.recentFiles
        canClearCurrentMedia: appController.selectedVideoPath.length > 0
        onRefreshRecentFilesRequested: appController.refreshRecentFiles()
        onOpenFileRequested: root.openFileRequested()
        onOpenFilesRequested: root.openFilesRequested()
        onOpenFolderRequested: root.openFolderRequested()
        onRecentFileRequested: function(path) { root.recentFileRequested(path) }
        onClearRecentFilesRequested: root.clearRecentFilesRequested()
        onClearCurrentMediaRequested: root.clearRequested()
    }

    Shortcut {
        sequence: "Ctrl+O"
        onActivated: root.openFileRequested()
    }

}
