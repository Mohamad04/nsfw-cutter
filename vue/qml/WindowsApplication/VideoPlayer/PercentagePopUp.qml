import QtQuick
import QtQuick.Controls

Popup {
    id: progressPopUp
    width: 100
    height:50
    modal: true
    focus: true
    property real progressValue: 0

    rectangle {
        Popup.fillWidth: true
    }
}