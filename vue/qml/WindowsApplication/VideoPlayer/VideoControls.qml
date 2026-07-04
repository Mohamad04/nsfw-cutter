import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

Rectangle {
    id: root

    property bool compactMode: false
    property bool lightMode: false
    property bool playing: false
    property bool previewEnabled: false
    property bool addEnabled: false
    property bool startSet: false
    property bool endSet: false
    property bool subtitlesAvailable: false
    property real volume: 0.85
    implicitHeight: root.compactMode ? 78 : 86

    signal seekRequested(int seconds)
    signal playbackToggled()
    signal startRequested()
    signal endRequested()
    signal addCutRequested()
    signal previewRequested()
    signal subtitlesRequested()
    signal volumeRequested(real value)

    radius: 0
    color: "transparent"
    border.width: 0

    ColumnLayout {
        anchors.fill: parent
        spacing: root.compactMode ? 5 : 7

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            spacing: root.compactMode ? 5 : 7

            AppButton { text: "-60"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 48; Layout.preferredHeight: 34; onClicked: root.seekRequested(-60) }
            AppButton { text: "-15"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 48; Layout.preferredHeight: 34; onClicked: root.seekRequested(-15) }
            AppButton { text: "-5"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 44; Layout.preferredHeight: 34; onClicked: root.seekRequested(-5) }

            AppButton {
                text: root.playing ? qsTr("Pause") : qsTr("Play")
                variant: "primary"
                size: "md"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 76 : 92
                Layout.preferredHeight: 36
                onClicked: root.playbackToggled()
            }

            AppButton { text: "+5"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 44; Layout.preferredHeight: 34; onClicked: root.seekRequested(5) }
            AppButton { text: "+15"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 48; Layout.preferredHeight: 34; onClicked: root.seekRequested(15) }
            AppButton { text: "+60"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: 48; Layout.preferredHeight: 34; onClicked: root.seekRequested(60) }

            Item { Layout.fillWidth: true }

            Text {
                text: qsTr("Volume")
                color: root.lightMode ? "#62738B" : "#92A2B8"
                font.pixelSize: 11
                visible: !root.compactMode
                verticalAlignment: Text.AlignVCenter
            }

            Slider {
                id: volumeSlider
                Layout.preferredWidth: root.compactMode ? 82 : 124
                Layout.preferredHeight: 28
                from: 0
                to: 1
                value: root.volume
                onMoved: root.volumeRequested(value)

                background: Rectangle {
                    x: volumeSlider.leftPadding
                    y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                    implicitHeight: 4
                    width: volumeSlider.availableWidth
                    height: implicitHeight
                    radius: 2
                    color: root.lightMode ? "#DCE4EF" : "#334155"

                    Rectangle {
                        width: volumeSlider.visualPosition * parent.width
                        height: parent.height
                        radius: parent.radius
                        color: root.lightMode ? "#1FA34A" : "#22B454"
                    }
                }

                handle: Rectangle {
                    x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                    y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                    width: 12
                    height: 12
                    radius: 6
                    color: root.lightMode ? "#FFFFFF" : "#E2E8F0"
                    border.color: root.lightMode ? "#1FA34A" : "#22B454"
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            spacing: root.compactMode ? 6 : 8

            Item { Layout.fillWidth: true }

            AppButton {
                text: qsTr("Set Start  I")
                accessibilityLabel: qsTr("Set start point of selected cut")
                iconSource: Qt.resolvedUrl("../../../../assets/icons/set_start.png")
                imageIconWidth: 42
                imageIconHeight: 24
                imageSourceWidth: 1024
                imageSourceHeight: 548
                variant: "ghost"
                size: "sm"
                active: root.startSet
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 140 : 156
                Layout.preferredHeight: 44
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Set start")
                onClicked: root.startRequested()
            }

            AppButton {
                text: qsTr("Set End  O")
                accessibilityLabel: qsTr("Set end point of selected cut")
                iconSource: Qt.resolvedUrl("../../../../assets/icons/set_end.png")
                imageIconWidth: 42
                imageIconHeight: 24
                imageSourceWidth: 1136
                imageSourceHeight: 554
                variant: "ghost"
                size: "sm"
                active: root.endSet
                activeAccentColor: root.lightMode ? "#F97316" : "#FB923C"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 136 : 150
                Layout.preferredHeight: 44
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Set end")
                onClicked: root.endRequested()
            }

            AppButton {
                text: qsTr("+ Add Cut")
                accessibilityLabel: qsTr("Cut video segment")
                iconSource: Qt.resolvedUrl("../../../../assets/icons/cut.png")
                imageIconSize: 28
                variant: "success"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 118 : 136
                Layout.preferredHeight: 40
                enabled: root.addEnabled
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Cut")
                onClicked: root.addCutRequested()
            }

            AppButton {
                text: qsTr("Preview Cut")
                variant: "secondary"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 106 : 124
                Layout.preferredHeight: 34
                enabled: root.previewEnabled
                onClicked: root.previewRequested()
            }

            AppButton {
                text: qsTr("Subtitles v")
                variant: "secondary"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: root.compactMode ? 110 : 124
                Layout.preferredHeight: 34
                enabled: root.subtitlesAvailable
                onClicked: root.subtitlesRequested()
            }
        }
    }
}

