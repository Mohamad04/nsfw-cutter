import QtQuick
import QtQuick.Controls

TextField {
    id: root

    color: "#F8FAFC"
    placeholderTextColor: "#64748B"
    selectionColor: "#2563EB"
    selectedTextColor: "#FFFFFF"
    font.pixelSize: 13
    implicitHeight: 38
    padding: 10

    background: Rectangle {
        radius: 12
        color: "#0F172A"
        border.color: root.activeFocus ? "#38BDF8" : "#334155"
        border.width: 1
    }
}
