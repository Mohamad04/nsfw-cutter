import QtQuick
import QtMultimedia

Rectangle {
    id: root

    property bool compactMode: false
    property bool lightMode: false
    property bool playing: false
    property real positionMs: 0
    property real durationMs: 0
    property real volume: 0.85
    property var cutsModel
    property int selectedCutIndex: -1
    property var cutPreview: ({ "visible": false })
    property string previewSubtitleText: ""
    property bool overlayActive: true
    property color videoTone: "#1E293B"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property alias videoOutput: output

    signal playRequested()
    signal seekRequested(real positionMs)
    signal skipRequested(int seconds)
    signal playbackToggled()
    signal startRequested()
    signal endRequested()
    signal addCutRequested()
    signal volumeRequested(real value)
    signal markerSelected(int index, real positionMs)
    signal cutSelected(int index)
    signal cutRangeChanged(int index, real startMs, real endMs)

    radius: 16
    color: root.videoTone
    border.color: root.lightMode ? "#CBD5E1" : "#233452"
    clip: true

    function revealControls() {
        root.overlayActive = true
        if (root.playing) hideControls.restart()
    }

    onPlayingChanged: root.revealControls()

    Timer {
        id: hideControls
        interval: 1800
        repeat: false
        onTriggered: if (root.playing) root.overlayActive = false
    }

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectFit
    }

    Rectangle {
        id: subtitleOverlay

        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.overlayActive && controlsOverlay.opacity > 0.15
            ? controlsOverlay.height + (root.compactMode ? 18 : 22)
            : (root.compactMode ? 22 : 28)
        width: Math.min(parent.width * 0.82, subtitleText.implicitWidth + 28)
        height: subtitleText.implicitHeight + 14
        radius: 10
        color: "#000000"
        opacity: root.previewSubtitleText.length > 0 ? 0.78 : 0
        visible: opacity > 0
        z: 4

        Behavior on opacity { NumberAnimation { duration: 80 } }

        Text {
            id: subtitleText

            anchors.centerIn: parent
            width: Math.min(root.width * 0.78, implicitWidth)
            text: root.previewSubtitleText
            color: "#FFFFFF"
            font.pixelSize: root.compactMode ? 18 : 23
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
            style: Text.Outline
            styleColor: "#000000"
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        hoverEnabled: true
        onEntered: root.revealControls()
        onPositionChanged: root.revealControls()
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
        opacity: root.playing || appController.videoUrl.length === 0 ? 0 : 0.86
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
            onClicked: root.playRequested()
        }
    }

    Rectangle {
        id: controlsOverlay
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: root.compactMode ? 8 : 12
        height: root.compactMode ? 78 : 88
        radius: 12
        color: root.lightMode ? "#F8FAFC" : "#050B14"
        opacity: root.playing && !root.overlayActive ? 0 : 0.96
        border.color: root.lightMode ? "#CBD5E1" : "#233452"

        Behavior on opacity { NumberAnimation { duration: 160 } }

        Column {
            id: overlayControls
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: root.compactMode ? 10 : 12
            anchors.rightMargin: root.compactMode ? 10 : 12
            spacing: root.compactMode ? 3 : 4

            VideoTimeline {
                id: timeline
                width: parent.width
                height: root.compactMode ? 24 : 28
                positionMs: root.positionMs
                durationMs: root.durationMs
                cutsModel: root.cutsModel
                selectedCutIndex: root.selectedCutIndex
                cutPreview: root.cutPreview
                lightMode: root.lightMode
                textMain: root.lightMode ? "#0F172A" : root.textMain
                accent: root.lightMode ? "#2563EB" : root.accent
                onSeekRequested: function(positionMs) { root.seekRequested(positionMs) }
                onMarkerSelected: function(index, positionMs) { root.markerSelected(index, positionMs) }
                onCutSelected: function(index) { root.cutSelected(index) }
                onCutRangeChanged: function(index, startMs, endMs) {
                    root.cutRangeChanged(index, startMs, endMs)
                }
            }

            VideoControls {
                id: controls
                width: parent.width
                height: root.compactMode ? 34 : 38
                compactMode: root.compactMode
                lightMode: root.lightMode
                playing: root.playing
                volume: root.volume
                onSeekRequested: function(seconds) { root.skipRequested(seconds) }
                onPlaybackToggled: root.playbackToggled()
                onStartRequested: root.startRequested()
                onEndRequested: root.endRequested()
                onAddCutRequested: root.addCutRequested()
                onVolumeRequested: function(value) { root.volumeRequested(value) }
            }
        }
    }
}
