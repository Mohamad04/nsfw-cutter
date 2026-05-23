import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property bool compactMode: false
    property bool playing: false
    property real volume: 0.85
    implicitHeight: root.compactMode ? 34 : 38

    signal seekRequested(int seconds)
    signal playbackToggled()
    signal startRequested()
    signal endRequested()
    signal addCutRequested()
    signal volumeRequested(real value)

    radius: 0
    color: "transparent"
    border.width: 0

    RowLayout {
        anchors.fill: parent
        anchors.margins: 0
        spacing: root.compactMode ? 4 : 8

        AppButton { text: "-60"; variant: "control"; size: "sm"; Layout.preferredWidth: root.compactMode ? 50 : 72; Layout.preferredHeight: 32; onClicked: root.seekRequested(-60) }
        AppButton { text: "-15"; variant: "control"; size: "sm"; Layout.preferredWidth: root.compactMode ? 50 : 72; Layout.preferredHeight: 32; onClicked: root.seekRequested(-15) }
        AppButton { text: "-5"; variant: "control"; size: "sm"; Layout.preferredWidth: root.compactMode ? 46 : 66; Layout.preferredHeight: 32; onClicked: root.seekRequested(-5) }

        AppButton {
            text: root.playing ? "Pause" : "Play"
            variant: "primary"
            size: "md"
            Layout.preferredWidth: root.compactMode ? 68 : 96
            Layout.preferredHeight: 34
            onClicked: root.playbackToggled()
        }

        AppButton { text: "+5"; variant: "control"; size: "sm"; Layout.preferredWidth: root.compactMode ? 46 : 66; Layout.preferredHeight: 32; onClicked: root.seekRequested(5) }
        AppButton { text: "+15"; variant: "control"; size: "sm"; Layout.preferredWidth: root.compactMode ? 50 : 72; Layout.preferredHeight: 32; onClicked: root.seekRequested(15) }
        AppButton { text: "+60"; variant: "control"; size: "sm"; Layout.preferredWidth: root.compactMode ? 50 : 72; Layout.preferredHeight: 32; onClicked: root.seekRequested(60) }

        AppButton {
            text: "Set Start"
            variant: "ghost"
            size: "sm"
            Layout.preferredWidth: root.compactMode ? 68 : 88
            Layout.preferredHeight: 32
            onClicked: root.startRequested()
        }

        AppButton {
            text: "Set End"
            variant: "ghost"
            size: "sm"
            Layout.preferredWidth: root.compactMode ? 64 : 82
            Layout.preferredHeight: 32
            onClicked: root.endRequested()
        }

        AppButton {
            text: "+ Add Cut"
            variant: "success"
            size: "sm"
            Layout.preferredWidth: root.compactMode ? 82 : 116
            Layout.preferredHeight: 32
            onClicked: root.addCutRequested()
        }

        Text {
            text: "Vol"
            color: "#CBD5E1"
            font.pixelSize: 11
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            Layout.preferredWidth: 36
            Layout.preferredHeight: 32
        }

        Slider {
            id: volumeSlider
            Layout.preferredWidth: root.compactMode ? 82 : 150
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
                color: "#334155"

                Rectangle {
                    width: volumeSlider.visualPosition * parent.width
                    height: parent.height
                    radius: parent.radius
                    color: "#22C55E"
                }
            }

            handle: Rectangle {
                x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                width: 12
                height: 12
                radius: 6
                color: "#E2E8F0"
                border.color: "#22C55E"
            }
        }
    }
}
