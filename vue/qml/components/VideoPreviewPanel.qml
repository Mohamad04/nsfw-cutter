import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Panel {
    id: root

    property bool compactMode: false
    property color panelTone: "#0B1324"
    property color videoTone: "#1E293B"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int cutCount: 0

    signal startRequested(string timeText)
    signal endRequested(string timeText)

    panelColor: root.panelTone
    strokeColor: "#21324D"

    function formatTime(ms) {
        var totalSeconds = Math.floor(ms / 1000)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var seconds = totalSeconds % 60

        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
    }

    function seekBy(seconds) {
        var newPosition = player.position + seconds * 1000
        if (newPosition < 0) newPosition = 0
        if (player.duration > 0 && newPosition > player.duration) newPosition = player.duration
        player.position = newPosition
    }

    function stopPlayback() {
        player.stop()
    }

    MediaPlayer {
        id: player
        source: appController.videoUrl
        videoOutput: videoOutput
        audioOutput: AudioOutput {}

        onPositionChanged: currentTimeLabel.text = root.formatTime(position)
        onDurationChanged: totalTimeLabel.text = duration > 0 ? root.formatTime(duration) : "00:00:00"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.compactMode ? 10 : 12
        spacing: root.compactMode ? 8 : 10

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 24
            spacing: 8

            Text {
                text: "VIDEO"
                color: root.accent
                font.pixelSize: 13
                font.bold: true
                font.letterSpacing: 0.8
            }

            Text {
                text: player.duration > 0 ? "Preview ready" : "Waiting for media"
                color: root.textMuted
                font.pixelSize: 12
            }

            Item { Layout.fillWidth: true }

            Text {
                text: "Cuts: " + root.cutCount
                color: root.textMuted
                font.pixelSize: 12
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 14
            color: root.videoTone
            border.color: "#233452"
            clip: true

            VideoOutput {
                id: videoOutput
                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectFit
            }

            Column {
                anchors.centerIn: parent
                spacing: 10
                visible: appController.videoUrl.length === 0

                Rectangle {
                    width: root.compactMode ? 70 : 86
                    height: width
                    radius: width / 2
                    color: "#050A12"
                    border.color: "#111827"

                    Text {
                        anchors.centerIn: parent
                        text: "Play"
                        color: "#F8FAFC"
                        font.pixelSize: root.compactMode ? 16 : 19
                        font.bold: true
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "No video loaded"
                    color: root.textMuted
                    font.pixelSize: 13
                }
            }

            Rectangle {
                anchors.centerIn: parent
                width: root.compactMode ? 70 : 86
                height: width
                radius: width / 2
                color: "#020617"
                opacity: player.playbackState === MediaPlayer.PlayingState || appController.videoUrl.length === 0 ? 0 : 0.86
                visible: appController.videoUrl.length > 0

                Text {
                    anchors.centerIn: parent
                    text: "Play"
                    color: "#F8FAFC"
                    font.pixelSize: root.compactMode ? 16 : 19
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: player.play()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                id: currentTimeLabel
                text: "00:00:00"
                color: root.textMain
                font.pixelSize: 13
                Layout.preferredWidth: 66
            }

            Slider {
                id: timelineSlider
                Layout.fillWidth: true
                from: 0
                to: player.duration > 0 ? player.duration : 1
                value: player.position
                enabled: player.duration > 0
                onMoved: player.position = value

                background: Rectangle {
                    x: timelineSlider.leftPadding
                    y: timelineSlider.topPadding + timelineSlider.availableHeight / 2 - height / 2
                    implicitHeight: 6
                    width: timelineSlider.availableWidth
                    height: implicitHeight
                    radius: 3
                    color: "#334155"

                    Rectangle {
                        width: timelineSlider.visualPosition * parent.width
                        height: parent.height
                        radius: 3
                        color: root.accent
                    }
                }

                handle: Rectangle {
                    x: timelineSlider.leftPadding + timelineSlider.visualPosition * (timelineSlider.availableWidth - width)
                    y: timelineSlider.topPadding + timelineSlider.availableHeight / 2 - height / 2
                    width: 18
                    height: 18
                    radius: 9
                    color: "#E0F2FE"
                    border.color: root.accent
                    border.width: 3
                }
            }

            Text {
                id: totalTimeLabel
                text: "00:00:00"
                color: root.textMain
                font.pixelSize: 13
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: 66
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.compactMode ? 50 : 56
            radius: 14
            color: "#0A1120"
            border.color: "#1F2F4A"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 8

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    radius: 12
                    color: "#08111F"
                    border.color: "#18263B"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 4
                        spacing: 4

                        AppButton { text: "-60"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: root.seekBy(-60) }
                        AppButton { text: "-15"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: root.seekBy(-15) }
                        AppButton { text: "-5"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: root.seekBy(-5) }
                    }
                }

                AppButton {
                    text: player.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                    variant: "primary"
                    size: "lg"
                    Layout.preferredWidth: root.compactMode ? 88 : 104
                    Layout.preferredHeight: 40
                    onClicked: player.playbackState === MediaPlayer.PlayingState ? player.pause() : player.play()
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    radius: 12
                    color: "#08111F"
                    border.color: "#18263B"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 4
                        spacing: 4

                        AppButton { text: "+5"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: root.seekBy(5) }
                        AppButton { text: "+15"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: root.seekBy(15) }
                        AppButton { text: "+60"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: root.seekBy(60) }
                    }
                }

                Rectangle {
                    Layout.preferredWidth: root.compactMode ? 126 : 146
                    Layout.preferredHeight: 40
                    radius: 12
                    color: "#0B2038"
                    border.color: "#1D4F73"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 4
                        spacing: 4

                        AppButton {
                            text: "Start"
                            variant: "ghost"
                            size: "sm"
                            Layout.fillWidth: true
                            onClicked: root.startRequested(root.formatTime(player.position))
                        }

                        AppButton {
                            text: "End"
                            variant: "ghost"
                            size: "sm"
                            Layout.fillWidth: true
                            onClicked: root.endRequested(root.formatTime(player.position))
                        }
                    }
                }
            }
        }
    }
}
