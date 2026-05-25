import QtQuick
import QtQuick.Controls

TextArea {
    id: root

    property bool lightMode: false

    color: root.lightMode ? "#0F172A" : "#F8FAFC"
    placeholderTextColor: root.lightMode ? "#94A3B8" : "#64748B"
    selectionColor: root.lightMode ? "#BFDBFE" : "#2563EB"
    selectedTextColor: root.lightMode ? "#0F172A" : "#FFFFFF"
    font.pixelSize: 13
    padding: 10
    wrapMode: TextArea.Wrap

    background: Rectangle {
        radius: 10
        color: root.lightMode ? "#F8FAFC" : "#0F172A"
        border.color: root.activeFocus ? (root.lightMode ? "#60A5FA" : "#38BDF8") : (root.lightMode ? "#CBD5E1" : "#334155")
        border.width: 1
    }
}
