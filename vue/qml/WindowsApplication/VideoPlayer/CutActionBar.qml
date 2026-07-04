import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../Shared"

Rectangle {
    id: root

    property bool lightMode: false
    property bool hasVideo: false
    property bool startPointSet: false
    property bool endPointSet: false
    property bool canAddCut: false
    property string cutTimingMode: "safe"
    property string safeSelectionText: ""
    property bool hasSafeKeyframeInfo: false
    property color mutedTextColor: "#92A2B8"
    property color strokeColor: "#223247"

    signal markStartRequested()
    signal markEndRequested()
    signal addCutRequested()
    signal previewCutRequested()
    signal timingModeSelected(string mode)

    implicitHeight: 76

    radius: 12
    color: root.lightMode ? "#FFFFFF" : "#07101D"
    border.color: root.lightMode ? root.strokeColor : "#1C2E49"

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        spacing: 8

        AppButton {
            text: ""
            accessibilityLabel: qsTr("Set start point of selected cut")
            iconSource: Qt.resolvedUrl("../../../../assets/icons/set_start.png")
            imageIconWidth: 60
            imageIconHeight: 34
            imageSourceWidth: 1024
            imageSourceHeight: 548
            variant: "ghost"
            size: "icon"
            active: root.startPointSet
            lightMode: root.lightMode
            enabled: root.hasVideo
            Layout.preferredWidth: 68
            Layout.preferredHeight: 44
            ToolTip.visible: hovered
            ToolTip.text: qsTr("Set start")
            onClicked: root.markStartRequested()
        }

        AppButton {
            text: ""
            accessibilityLabel: qsTr("Set end point of selected cut")
            iconSource: Qt.resolvedUrl("../../../../assets/icons/set_end.png")
            imageIconWidth: 60
            imageIconHeight: 34
            imageSourceWidth: 1136
            imageSourceHeight: 554
            variant: "ghost"
            size: "icon"
            active: root.endPointSet
            activeAccentColor: root.lightMode ? "#F97316" : "#FB923C"
            lightMode: root.lightMode
            enabled: root.hasVideo
            Layout.preferredWidth: 68
            Layout.preferredHeight: 44
            ToolTip.visible: hovered
            ToolTip.text: qsTr("Set end")
            onClicked: root.markEndRequested()
        }

        AppButton {
            text: ""
            accessibilityLabel: qsTr("Cut video segment")
            iconSource: Qt.resolvedUrl("../../../../assets/icons/cut.png")
            imageIconSize: 32
            variant: "primary"
            size: "icon"
            lightMode: root.lightMode
            enabled: root.canAddCut
            Layout.preferredWidth: 44
            Layout.preferredHeight: 44
            ToolTip.visible: hovered
            ToolTip.text: root.canAddCut ? (root.hasSafeKeyframeInfo ? qsTr("Cut") : root.safeSelectionText) : qsTr("Set start and end")
            onClicked: root.addCutRequested()
        }

        AppButton {
            text: qsTr("Preview Cut")
            iconName: "eye"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: root.canAddCut
            Layout.preferredWidth: 132
            Layout.preferredHeight: 36
            onClicked: root.previewCutRequested()
        }

        Item { Layout.fillWidth: true }

        CutModeControl {
            Layout.fillWidth: true
            Layout.maximumWidth: 520
            Layout.preferredHeight: 44
            Layout.alignment: Qt.AlignVCenter

            cutTimingMode: root.cutTimingMode
            lightMode: root.lightMode
            mutedTextColor: root.mutedTextColor

            onTimingModeSelected: function(mode) {
                root.timingModeSelected(mode)
            }
        }
    }
}
