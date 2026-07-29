pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

Popup {
    id: root

    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"

    property bool subtitlesSelected: true
    property bool videoFramesSelected: true
    property bool audioSelected: true
    property bool analysisRunning: false
    property int analysisProgress: 0

    readonly property int menuWidth: 360
    readonly property bool hasSelectedSource: root.subtitlesSelected
        || root.videoFramesSelected
        || root.audioSelected
    property var anchorTarget: null

    AppTheme { id: theme }

    function reposition() {
        if (!root.anchorTarget || !root.parent) return

        var position = root.anchorTarget.mapToItem(root.parent, 0, 0)
        var windowMargin = 16
        var parentScenePosition = root.parent.mapToItem(null, 0, 0)
        var hostWindow = root.anchorTarget.Window.window
        var maximumX = Math.max(windowMargin, root.parent.width - root.width - windowMargin)
        var preferredY = position.y + root.anchorTarget.height + 8
        var minimumY = hostWindow ? windowMargin - parentScenePosition.y : 0
        var maximumY = hostWindow
            ? hostWindow.height - parentScenePosition.y - root.height - windowMargin
            : preferredY

        root.x = Math.max(windowMargin, Math.min(position.x, maximumX))
        root.y = Math.max(minimumY, Math.min(preferredY, maximumY))
    }

    function showAt(target) {
        root.anchorTarget = target
        root.reposition()
        root.open()
        root.forceActiveFocus()
    }

    function closeAfterAction() {
        root.close()
    }

    function startMockAnalysis() {
        if (!root.hasSelectedSource || root.analysisRunning) return

        root.analysisProgress = 0
        root.analysisRunning = true
        mockProgressTimer.restart()
    }

    function stopMockAnalysis() {
        mockProgressTimer.stop()
        root.analysisRunning = false
        root.analysisProgress = 0
    }

    modal: false
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: root.menuWidth
    height: popupColumn.implicitHeight + 28

    onHeightChanged: {
        if (root.opened) root.reposition()
    }
    onOpened: root.reposition()

    background: Item {}

    Connections {
        target: root.anchorTarget
        enabled: root.opened
        ignoreUnknownSignals: true

        function onXChanged() { root.reposition() }
        function onYChanged() { root.reposition() }
        function onWidthChanged() { root.reposition() }
        function onHeightChanged() { root.reposition() }
    }

    Connections {
        target: root.anchorTarget ? root.anchorTarget.Window.window : null
        enabled: root.opened
        ignoreUnknownSignals: true

        function onWidthChanged() { Qt.callLater(root.reposition) }
        function onHeightChanged() { Qt.callLater(root.reposition) }
    }

    contentItem: Item {
        implicitWidth: root.width
        implicitHeight: root.height

        Rectangle {
            x: 0
            y: 5
            width: parent.width
            height: parent.height - 5
            radius: theme.panelRadius
            color: "#000000"
            opacity: 0.34
        }

        Rectangle {
            anchors.fill: parent
            radius: theme.panelRadius
            color: root.lightMode ? theme.lightSurface : theme.darkAppBg
            border.color: root.lightMode ? theme.lightBorder : theme.darkBorder
            border.width: 1
        }

        Column {
            id: popupColumn

            x: 14
            y: 14
            width: root.width - 28
            spacing: theme.sectionGap

            Row {
                width: parent.width
                height: 22
                spacing: 8

                VectorIcon {
                    width: 18
                    height: 18
                    anchors.verticalCenter: parent.verticalCenter
                    name: "sparkle"
                    iconColor: root.accentColor
                }

                Text {
                    width: parent.width - 26
                    height: parent.height
                    text: qsTr("AI Picks")
                    color: root.textColor
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
            }

            Text {
                width: parent.width
                text: qsTr("Want to update the AI prompt? Go to Settings and add the categories to detect, such as Nudity, Violence, etc.")
                color: root.mutedTextColor
                font.pixelSize: 12
                lineHeight: 1.25
                wrapMode: Text.WordWrap
            }

            Column {
                width: parent.width
                spacing: 8

                AnalysisOptionCard {
                    objectName: "subtitlesOptionCard"
                    width: parent.width
                    label: qsTr("Subtitles")
                    iconName: "cc"
                    selected: root.subtitlesSelected
                    onClicked: root.subtitlesSelected = !root.subtitlesSelected
                }

                AnalysisOptionCard {
                    objectName: "videoFramesOptionCard"
                    width: parent.width
                    label: qsTr("Video Frames")
                    iconName: "eye"
                    selected: root.videoFramesSelected
                    onClicked: root.videoFramesSelected = !root.videoFramesSelected
                }

                AnalysisOptionCard {
                    objectName: "audioOptionCard"
                    width: parent.width
                    label: qsTr("Audio")
                    iconName: "volume"
                    selected: root.audioSelected
                    onClicked: root.audioSelected = !root.audioSelected
                }
            }

            Column {
                width: parent.width
                spacing: 7
                visible: root.analysisRunning

                Rectangle {
                    width: parent.width
                    height: 1
                    color: root.lightMode ? theme.lightDivider : theme.darkDivider
                }

                Text {
                    width: parent.width
                    text: qsTr("Analysis in progress")
                    color: root.textColor
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    text: qsTr("AI is scanning your video. You can stop it at any time.")
                    color: root.mutedTextColor
                    font.pixelSize: 12
                    lineHeight: 1.2
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    text: qsTr("Analyzing...") + " " + root.analysisProgress + "%"
                    color: root.accentColor
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }

                ProgressBar {
                    id: analysisProgressBar
                    objectName: "aiPicksProgressBar"

                    width: parent.width
                    height: 8
                    padding: 0
                    from: 0
                    to: 100
                    value: root.analysisProgress

                    background: Rectangle {
                        implicitWidth: analysisProgressBar.width
                        implicitHeight: 8
                        radius: 4
                        color: root.lightMode ? theme.lightBorderSoft : theme.darkBorderSoft
                    }

                    contentItem: Item {
                        implicitWidth: analysisProgressBar.width
                        implicitHeight: 8

                        Rectangle {
                            width: analysisProgressBar.visualPosition * parent.width
                            height: parent.height
                            radius: 4
                            color: root.accentColor
                        }
                    }
                }
            }

            AppButton {
                objectName: "aiPicksActionButton"
                width: parent.width
                height: 40
                text: root.analysisRunning ? qsTr("Break") : qsTr("Confirm")
                variant: root.analysisRunning ? "danger" : "primary"
                size: "md"
                lightMode: root.lightMode
                enabled: root.analysisRunning || root.hasSelectedSource
                onClicked: {
                    if (root.analysisRunning)
                        root.stopMockAnalysis()
                    else
                        root.startMockAnalysis()
                }
            }
        }
    }

    // Frontend-only mock progress. Replace with backend progress signals later.
    Timer {
        id: mockProgressTimer

        interval: 220
        repeat: true
        onTriggered: {
            root.analysisProgress = Math.min(100, root.analysisProgress + 2)
            if (root.analysisProgress >= 100) {
                mockProgressTimer.stop()
                root.analysisRunning = false
                root.analysisProgress = 0
            }
        }
    }

    component AnalysisOptionCard: AbstractButton {
        id: optionCard

        required property string label
        required property string iconName
        property bool selected: false

        Accessible.name: optionCard.label
        Accessible.role: Accessible.CheckBox
        Accessible.checked: optionCard.selected

        enabled: !root.analysisRunning
        activeFocusOnTab: true
        implicitHeight: 52

        background: Rectangle {
            radius: theme.innerRadius
            color: {
                if (optionCard.selected)
                    return root.lightMode ? theme.lightAccentSoft : "#0C3B88"
                if (optionCard.hovered && optionCard.enabled)
                    return root.lightMode ? theme.lightHover : theme.darkHover
                return root.lightMode ? theme.lightSurfaceAlt : theme.darkSurfaceAlt
            }
            border.color: optionCard.selected
                ? root.accentColor
                : (optionCard.activeFocus
                    ? root.accentColor
                    : (root.lightMode ? theme.lightBorder : theme.darkBorder))
            border.width: optionCard.activeFocus ? 2 : 1
            opacity: optionCard.enabled ? 1.0 : 0.76

            Behavior on color {
                ColorAnimation {
                    duration: 120
                    easing.type: Easing.OutQuad
                }
            }
        }

        contentItem: RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 10

            VectorIcon {
                Layout.preferredWidth: 21
                Layout.preferredHeight: 21
                name: optionCard.iconName
                iconColor: optionCard.selected
                    ? (root.lightMode ? theme.lightAccent : "#F8FAFC")
                    : root.mutedTextColor
            }

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: optionCard.label
                color: optionCard.selected
                    ? (root.lightMode ? theme.lightAccentPressed : "#F8FAFC")
                    : root.textColor
                font.pixelSize: 13
                font.weight: Font.Medium
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }

            Rectangle {
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24
                radius: 12
                color: optionCard.selected ? root.accentColor : "transparent"
                border.color: optionCard.selected
                    ? root.accentColor
                    : (root.lightMode ? theme.lightTextMuted : theme.darkTextMuted)
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    text: "✓"
                    color: "#F8FAFC"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    visible: optionCard.selected
                }
            }
        }
    }
}
