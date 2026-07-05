pragma ComponentBehavior: Bound

import QtQuick

SeekStepButton {
    seconds: 1
    direction: "backward"
    chevronCount: 1
    accessibilityLabel: qsTr("Seek backward 1 second")
}
