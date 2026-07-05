pragma ComponentBehavior: Bound

import QtQuick

SeekStepButton {
    seconds: 1
    direction: "forward"
    chevronCount: 1
    accessibilityLabel: qsTr("Seek forward 1 second")
}
