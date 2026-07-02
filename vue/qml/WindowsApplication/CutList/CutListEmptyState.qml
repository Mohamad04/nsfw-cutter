import QtQuick
import "../Shared"

Column {
    id: root

    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"

    spacing: 11

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        width: 48
        height: 48
        radius: 18
        color: root.lightMode ? "#EFF6FF" : "#0B1D33"
        border.color: root.lightMode ? "#BFDBFE" : "#213A5E"

        Image {
            anchors.centerIn: parent
            width: 34
            height: 34
            source: Qt.resolvedUrl("../../../../assets/icons/cut.png")
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            cache: true
            sourceSize.width: 512
            sourceSize.height: 512
        }
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: "No cuts added yet"
        color: root.textColor
        font.pixelSize: 15
        font.weight: Font.DemiBold
    }

    Text {
        width: parent.width
        text: "Use Set Start and Set End below the video,\nthen select Add Cut."
        color: root.mutedTextColor
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        lineHeight: 1.2
    }
}

