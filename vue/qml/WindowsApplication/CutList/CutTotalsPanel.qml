import QtQuick
import QtQuick.Layouts
import "../Shared"

Rectangle {
    id: root

    property string totalRemovedText: "00:00:00"
    property string videoAfterCutsText: "--:--:--"
    property bool hasVideoDuration: false
    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"

    radius: 12
    color: root.lightMode ? "#F8FAFC" : "#050B14"
    border.color: root.lightMode ? "#E2E8F0" : "#17263E"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        RowLayout {
            Layout.fillWidth: true

            Text {
                Layout.fillWidth: true
                text: qsTr("Total Removed")
                color: root.mutedTextColor
                font.pixelSize: 12
            }

            Text {
                text: root.totalRemovedText
                color: root.textColor
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Text {
                Layout.fillWidth: true
                text: qsTr("Video After Cuts")
                color: root.mutedTextColor
                font.pixelSize: 12
            }

            Text {
                text: root.videoAfterCutsText
                color: root.hasVideoDuration ? root.textColor : root.mutedTextColor
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
        }
    }
}

