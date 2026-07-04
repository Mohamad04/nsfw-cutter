import QtQuick
import QtMultimedia

import "../Shared"

Rectangle {
    id: root
    objectName: "videoStage"

    property bool hasVideo: false
    property bool lightMode: false
    property color videoColor: "#020617"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property string previewSubtitleText: ""
    property alias videoOutput: stageVideoOutput
    property alias videoSink: stageVideoOutput.videoSink

    radius: 16
    color: root.videoColor
    border.color: root.hasVideo
        ? (root.lightMode ? "#93C5FD" : "#2F7BFF")
        : (root.lightMode ? "#DCE4EF" : "#142033")
    border.width: 1
    clip: true

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 15
        color: "transparent"
        border.color: root.hasVideo ? root.accentColor : "#0E1A2C"
        border.width: 1
        opacity: root.hasVideo ? 0.22 : 0.24
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 1
        color: root.accentColor
        opacity: root.hasVideo ? 0.28 : 0.08
    }

    VideoOutput {
        id: stageVideoOutput

        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        spacing: 10
        visible: !root.hasVideo

        VectorIcon {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 44
            height: 44
            name: "play"
            iconColor: root.lightMode ? "#94A3B8" : "#36506E"
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("Video preview will appear here")
            color: root.textColor
            font.pixelSize: 18
            font.weight: Font.DemiBold
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("Open a video to get started")
            color: root.mutedTextColor
            font.pixelSize: 13
        }
    }

    SubtitleOverlay {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 28

        subtitleText: root.previewSubtitleText
        lightMode: root.lightMode
    }
}
