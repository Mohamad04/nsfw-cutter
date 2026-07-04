import QtQuick
import QtQuick.Layouts

import "../Shared"

Rectangle {
    id: root

    property string cutTimingMode: "safe"
    property bool lightMode: false

    signal timingModeSelected(string mode)

    implicitWidth: 220
    implicitHeight: 34

    radius: 8
    color: root.lightMode ? "#EEF4FB" : "#0C1728"
    border.color: root.lightMode ? "#CBD5E1" : "#243244"

    RowLayout {
        anchors.fill: parent
        anchors.margins: 4
        spacing: 6

        AppButton {
            text: qsTr("Smart")
            variant: root.cutTimingMode === "safe" ? "primary" : "ghost"
            size: "sm"
            lightMode: root.lightMode

            Layout.fillWidth: true
            Layout.fillHeight: true

            onClicked: root.timingModeSelected("safe")
        }

        AppButton {
            text: qsTr("Fast")
            variant: root.cutTimingMode === "requested" ? "primary" : "ghost"
            size: "sm"
            lightMode: root.lightMode

            Layout.fillWidth: true
            Layout.fillHeight: true

            onClicked: root.timingModeSelected("requested")
        }
    }
}
