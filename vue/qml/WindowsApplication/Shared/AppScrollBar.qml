import QtQuick
import QtQuick.Controls

ScrollBar {
    id: root

    property bool lightMode: false

    policy: ScrollBar.AsNeeded

    contentItem: Rectangle {
        implicitWidth: 8
        implicitHeight: 8
        radius: 4
        color: root.lightMode ? (root.pressed ? "#64748B" : "#94A3B8") : (root.pressed ? "#64748B" : "#475569")
        opacity: root.active ? 0.95 : 0.75
    }

    background: Rectangle {
        implicitWidth: 8
        radius: 4
        color: root.lightMode ? "#E2E8F0" : "#111827"
        opacity: 0.9
    }
}

