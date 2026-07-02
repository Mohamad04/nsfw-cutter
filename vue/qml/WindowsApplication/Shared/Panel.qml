import QtQuick

Rectangle {
    id: root

    property color panelColor: "#111827"
    property color strokeColor: "#243244"

    radius: 14
    color: panelColor
    border.color: strokeColor
    border.width: 1
    clip: true
}

