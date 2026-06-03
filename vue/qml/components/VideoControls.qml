import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property bool compactMode: false
    property bool lightMode: false
    property bool playing: false
    property bool previewEnabled: false
    property real volume: 0.85
    implicitHeight: root.compactMode ? 38 : 42

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

    RowLayout {
        anchors.fill: parent
        anchors.margins: 0
        spacing: root.compactMode ? 5 : 8

        AppButton { text: "-10s"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: root.compactMode ? 52 : 64; Layout.preferredHeight: 36; onClicked: root.seekRequested(-10) }

        AppButton {
            text: root.playing ? "Pause" : "Play"
            variant: "primary"
            size: "md"
            lightMode: root.lightMode
            Layout.preferredWidth: root.compactMode ? 72 : 92
            Layout.preferredHeight: 38
            onClicked: root.playbackToggled()
        }

        AppButton { text: "+10s"; variant: "control"; size: "sm"; lightMode: root.lightMode; Layout.preferredWidth: root.compactMode ? 52 : 64; Layout.preferredHeight: 36; onClicked: root.seekRequested(10) }

        Text {
            text: "1.0x"
            color: root.lightMode ? "#62738B" : "#92A2B8"
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            Layout.preferredWidth: root.compactMode ? 42 : 52
            Layout.preferredHeight: 36
        }

        Item { Layout.fillWidth: true }

        AppButton {
            text: "Set Start  I"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            Layout.preferredWidth: root.compactMode ? 100 : 116
            Layout.preferredHeight: 36
            onClicked: root.startRequested()
        }

        AppButton {
            text: "Set End  O"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            Layout.preferredWidth: root.compactMode ? 92 : 108
            Layout.preferredHeight: 36
            onClicked: root.endRequested()
        }

        AppButton {
            text: "+ Add Cut"
            variant: "success"
            size: "sm"
            lightMode: root.lightMode
            Layout.preferredWidth: root.compactMode ? 96 : 116
            Layout.preferredHeight: 36
            onClicked: root.addCutRequested()
        }

        AppButton {
            text: "Preview Cut"
            variant: "secondary"
            size: "sm"
            lightMode: root.lightMode
            Layout.preferredWidth: root.compactMode ? 98 : 116
            Layout.preferredHeight: 36
            enabled: root.previewEnabled
            onClicked: root.previewRequested()
        }

        AppButton {
            text: "Subtitles v"
            variant: "secondary"
            size: "sm"
            lightMode: root.lightMode
            Layout.preferredWidth: root.compactMode ? 104 : 118
            Layout.preferredHeight: 36
            onClicked: root.subtitlesRequested()
        }

        Slider {
            id: volumeSlider
            Layout.preferredWidth: root.compactMode ? 72 : 118
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
}
