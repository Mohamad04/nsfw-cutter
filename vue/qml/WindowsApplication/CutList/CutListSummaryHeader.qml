import QtQuick
import QtQuick.Layouts

import "../Shared"

ColumnLayout {
    id: root

    property int cutsCount: 0
    property string totalRemovedText: "00:00:00"
    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"

    signal clearListRequested()

    TextMetrics {
        id: clearListTextMetrics
        text: qsTr("Clear List")
        font.pixelSize: 12
        font.weight: Font.Medium
    }

    spacing: 3

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        VectorIcon {
            Layout.preferredWidth: 18
            Layout.preferredHeight: 18
            name: "list"
            iconColor: root.accentColor
        }

        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: qsTr("Cut List")
            color: root.textColor
            font.pixelSize: 18
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }

        AppButton {
            text: qsTr("Clear List")
            iconName: "trash"
            variant: "secondary"
            size: "sm"
            lightMode: root.lightMode
            enabled: root.cutsCount > 0
            accessibilityLabel: qsTr("Clear List")
            Layout.preferredWidth: Math.ceil(clearListTextMetrics.width) + 48
            Layout.minimumWidth: Layout.preferredWidth
            Layout.preferredHeight: 34
            onClicked: root.clearListRequested()
        }
    }

    Text {
        Layout.fillWidth: true
        text: qsTr("%1 %2 - Total removed: %3")
              .arg(root.cutsCount)
              .arg(root.cutsCount === 1 ? qsTr("cut") : qsTr("cuts"))
              .arg(root.totalRemovedText)
        color: root.mutedTextColor
        font.pixelSize: 12
        elide: Text.ElideRight
    }
}

