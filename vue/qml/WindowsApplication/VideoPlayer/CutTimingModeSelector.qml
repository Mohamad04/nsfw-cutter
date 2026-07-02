import QtQuick
import QtQuick.Layouts

import "../Shared"

Rectangle {
    id: root

    property string cutTimingMode: "safe"
    property bool lightMode: false

    signal timingModeSelected(string mode)

    radius: 8
    color: root.lightMode ? "#EEF4FB" : "#0C1728"
    border.color: root.lightMode ? "#CBD5E1" : "#243244"

    RowLayout {
        anchors.fill: parent
        anchors.margins: 5
        spacing: 10

        AppButton {
            text: "Smart"
            variant: root.cutTimingMode === "safe" ? "primary" : "ghost"
            size: "sm"
            lightMode: root.lightMode
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            onClicked: root.timingModeSelected("safe")
        }

        AppButton {
            text: "Fast"
            variant: root.cutTimingMode === "requested" ? "primary" : "ghost"
            size: "sm"
            lightMode: root.lightMode
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            onClicked: root.timingModeSelected("requested")
        }
    }
}

