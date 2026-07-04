import QtQuick
import QtQuick.Layouts

import "../Shared"

ColumnLayout {
    id: root

    property int cutsCount: 0
    property string totalRemovedText: "00:00:00"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"

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
            text: qsTr("Cut List")
            color: root.textColor
            font.pixelSize: 18
            font.weight: Font.DemiBold
            elide: Text.ElideRight
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

