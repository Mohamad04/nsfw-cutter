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
    property color videoTone: "#1E293B"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property alias videoOutput: output

    signal playRequested()

    radius: 14
    color: root.videoTone
    border.color: root.lightMode ? "#DCE4EF" : "#223247"
    clip: true

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectFit
    }

    Rectangle {
        id: subtitleOverlay

        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.compactMode ? 22 : 30
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

    Column {
        anchors.centerIn: parent
        spacing: 10
        visible: appController.videoUrl.length === 0

        Rectangle {
            width: root.compactMode ? 70 : 86
            height: width
            radius: width / 2
            color: root.lightMode ? "#FFFFFF" : "#050A12"
            border.color: root.lightMode ? "#DCE4EF" : "#111827"

            Text {
                anchors.centerIn: parent
                text: "Open"
                color: root.lightMode ? "#142033" : "#F8FAFC"
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
        width: root.compactMode ? 68 : 82
        height: width
        radius: width / 2
        color: "#020617"
        opacity: root.playing || appController.videoUrl.length === 0 ? 0 : 0.82
        visible: appController.videoUrl.length > 0
        z: 3

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
}
