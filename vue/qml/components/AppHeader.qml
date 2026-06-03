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
    property color panelColor: "#0C1625"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    readonly property int expandedHeaderHeight: root.compactMode ? 64 : 70
    readonly property int collapsedHeaderHeight: 0
    readonly property int preferredHeaderHeight: root.expandedHeaderHeight

    signal openFileRequested()
    signal openFilesRequested()
    signal openFolderRequested()
    signal recentFileRequested(string path)
    signal clearRecentFilesRequested()
    signal clearRequested()
    signal settingsClicked()

    AppTheme { id: theme }

    function selectedSubtitleLabel() {
        var options = appController.analysisSubtitleOptions
        for (var index = 0; index < options.length; index += 1) {
            if (options[index].selected) return options[index].label
        }
        if (appController.subtitleCandidates.length > 0) return "Select subtitle"
        if (appController.subtitleDetectionState === "loading") return "Detecting"
        return "Subtitles"
    }

    function subtitleCountLabel() {
        var count = appController.subtitleCandidates.length
        if (count === 1) return "1 subtitle detected"
        return count + " subtitles detected"
    }

    function toggleTheme() {
        settingsController.setTheme(root.lightMode ? "dark" : "light")
    }

    implicitHeight: root.preferredHeaderHeight
    implicitWidth: 1200

    Panel {
        anchors.fill: parent
        panelColor: root.panelColor
        strokeColor: root.strokeColor

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: root.compactMode ? 12 : 16
            anchors.rightMargin: root.compactMode ? 12 : 16
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            spacing: root.compactMode ? 8 : 12

            Image {
                source: root.appIconSource
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                Layout.preferredWidth: root.compactMode ? 36 : 42
                Layout.preferredHeight: root.compactMode ? 36 : 42
            }

            Text {
                text: "NSFW Cutter"
                color: root.textColor
                font.pixelSize: root.compactMode ? 18 : 22
                font.bold: true
                visible: !root.narrowMode
                Layout.preferredWidth: root.compactMode ? 136 : 170
                Layout.minimumWidth: 0
                elide: Text.ElideRight
            }

            Rectangle {
                Layout.preferredWidth: 1
                Layout.preferredHeight: 34
                color: root.lightMode ? theme.lightDivider : theme.darkDivider
                visible: !root.narrowMode
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 160
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: appController.videoName.length > 0 && appController.selectedVideoPath.length > 0
                        ? appController.videoName
                        : "No video loaded"
                    color: root.textColor
                    font.pixelSize: root.compactMode ? 13 : 15
                    font.weight: Font.DemiBold
                    elide: Text.ElideMiddle
                }

                Text {
                    Layout.fillWidth: true
                    text: appController.selectedVideoPath.length > 0
                        ? "Stream-copy preview  |  " + appController.selectedVideoPath
                        : "Open a video to start marking removal intervals"
                    color: root.mutedTextColor
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                    visible: !root.compactMode || root.width > 1300
                }
            }

            AppButton {
                id: mediaButton

                text: "+ Add / Open Video"
                variant: "secondary"
                size: "md"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 132 : 160
                Layout.preferredHeight: 40
                onClicked: mediaMenu.showAt(mediaButton)
            }

            AppButton {
                id: subtitleButton

                text: root.selectedSubtitleLabel() + " v"
                variant: "secondary"
                size: "md"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 124 : 156
                Layout.preferredHeight: 40
                enabled: appController.subtitleCandidates.length > 0
                    || appController.subtitleDetectionState === "loading"
                onClicked: if (appController.subtitleCandidates.length > 0) subtitleSelector.showAt(subtitleButton)
            }

            Rectangle {
                Layout.preferredWidth: root.compactMode ? 134 : 166
                Layout.preferredHeight: 40
                radius: 12
                color: root.lightMode ? theme.lightSuccessSoft : "#0D2F1D"
                border.color: root.lightMode ? "#A7F3D0" : "#1B6F3A"
                visible: !root.narrowMode

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    text: root.subtitleCountLabel()
                    color: root.lightMode ? theme.lightSuccess : theme.darkSuccess
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            Rectangle {
                Layout.preferredWidth: root.compactMode ? 118 : 138
                Layout.preferredHeight: 40
                radius: 12
                color: root.lightMode ? theme.lightSuccessSoft : "#0D2F1D"
                border.color: root.lightMode ? "#A7F3D0" : "#1B6F3A"

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    text: appController.projectStatus
                    color: root.lightMode ? theme.lightSuccess : theme.darkSuccess
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            AppButton {
                text: root.lightMode ? "Dark" : "Light"
                variant: "ghost"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: 70
                Layout.preferredHeight: 40
                ToolTip.visible: hovered
                ToolTip.text: "Toggle dark/light theme"
                onClicked: root.toggleTheme()
            }

            AppButton {
                text: "Settings"
                variant: "ghost"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 72 : 88
                Layout.preferredHeight: 40
                ToolTip.visible: hovered
                ToolTip.text: "Settings"
                onClicked: root.settingsClicked()
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

    SubtitleSelectorPopup {
        id: subtitleSelector

        lightMode: root.lightMode
        textColor: root.textColor
        mutedTextColor: root.mutedTextColor
        options: appController.analysisSubtitleOptions
        detectedCount: appController.subtitleCandidates.length
        onCandidateSelected: function(candidateId) {
            if (appController.selectAnalysisSubtitle(candidateId))
                subtitleSelector.closeAfterAction()
        }
    }

    Connections {
        target: appController

        function onSelectedVideoPathChanged() {
            subtitleSelector.closeAfterAction()
        }

        function onSubtitleCandidatesChanged() {
            if (appController.subtitleCandidates.length === 0)
                subtitleSelector.closeAfterAction()
        }
    }

    Shortcut {
        sequence: "Ctrl+O"
        onActivated: root.openFileRequested()
    }
}
