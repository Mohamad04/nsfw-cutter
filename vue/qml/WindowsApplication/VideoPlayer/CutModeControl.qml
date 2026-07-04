import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property string cutTimingMode: "safe"
    property bool lightMode: false
    property color mutedTextColor: "#92A2B8"

    signal timingModeSelected(string mode)

    implicitWidth: 430
    implicitHeight: 44

    radius: 12
    color: root.lightMode ? "#F8FAFC" : "#071525"
    border.color: root.lightMode ? "#DCE4EF" : "#1E3A5F"

    RowLayout {
        anchors.fill: parent
        anchors.margins: 5
        spacing: 10

        Text {
            text: qsTr("Cut Mode")
            color: root.mutedTextColor
            font.pixelSize: 11
            font.weight: Font.DemiBold

            Layout.preferredWidth: 70
            Layout.minimumWidth: 70
            Layout.maximumWidth: 70
            Layout.alignment: Qt.AlignVCenter
        }

        CutTimingModeSelector {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            Layout.minimumHeight: 34
            Layout.maximumHeight: 34
            Layout.alignment: Qt.AlignVCenter

            cutTimingMode: root.cutTimingMode
            lightMode: root.lightMode

            onTimingModeSelected: function(mode) {
                root.timingModeSelected(mode)
            }
        }
    }
}
