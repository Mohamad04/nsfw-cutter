pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

Popup {
    id: root

    property bool lightMode: false
    property var options: []
    property int detectedCount: 0
    property color textColor: "#F8FAFC"
    property color mutedTextColor: "#94A3B8"
    readonly property int menuWidth: 330

    signal candidateSelected(string candidateId)

    function showAt(target) {
        var position = target.mapToItem(root.parent, 0, 0)
        root.x = Math.max(0, position.x + target.width - root.menuWidth)
        root.y = position.y + target.height + 6
        root.open()
        root.forceActiveFocus()
    }

    function closeAfterAction() {
        root.close()
    }

    modal: false
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: root.menuWidth
    height: menuColumn.implicitHeight + 16

    Keys.onEscapePressed: root.closeAfterAction()

    background: Item {}

    contentItem: Item {
        implicitWidth: root.width
        implicitHeight: root.height

        Rectangle {
            anchors.fill: parent
            radius: 12
            color: root.lightMode ? "#FFFFFF" : "#07111E"
            border.color: root.lightMode ? "#CBD5E1" : "#243244"
            border.width: 1
        }

        Column {
            id: menuColumn

            x: 8
            y: 8
            width: root.menuWidth - 16
            spacing: 4

            Rectangle {
                width: parent.width
                height: 30
                color: "transparent"

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    anchors.topMargin: 4
                    anchors.bottomMargin: 6
                    text: qsTr("ANALYSIS SUBTITLE")
                    color: root.lightMode ? "#64748B" : root.mutedTextColor
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.8
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                visible: root.options.length === 0
                width: parent.width
                height: 36
                radius: 8
                color: "transparent"

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    text: qsTr("No subtitle candidates")
                    color: root.lightMode ? "#94A3B8" : "#64748B"
                    font.pixelSize: 13
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
            }

            Repeater {
                model: root.options

                delegate: Rectangle {
                    id: rowRoot

                    required property var modelData

                    width: parent ? parent.width : root.menuWidth - 16
                    height: 42
                    radius: 8
                    color: rowMouse.containsMouse && rowRoot.modelData.enabled
                        ? (root.lightMode ? "#EFF6FF" : "#102A43")
                        : "transparent"
                    opacity: rowRoot.modelData.enabled ? 1.0 : 0.52

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 8

                        Text {
                            Layout.preferredWidth: 18
                            text: rowRoot.modelData.selected ? "●" : "○"
                            color: rowRoot.modelData.selected
                                ? (root.lightMode ? "#16A34A" : "#86EFAC")
                                : (root.lightMode ? "#64748B" : root.mutedTextColor)
                            font.pixelSize: 13
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            Layout.fillWidth: true
                            text: rowRoot.modelData.label
                            color: rowRoot.modelData.enabled
                                ? (root.lightMode ? "#0F172A" : root.textColor)
                                : (root.lightMode ? "#94A3B8" : "#64748B")
                            font.pixelSize: 13
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            text: rowRoot.modelData.capabilityLabel
                            color: rowRoot.modelData.enabled
                                ? (root.lightMode ? "#0284C7" : "#38BDF8")
                                : (root.lightMode ? "#D97706" : "#F97316")
                            font.pixelSize: 11
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                            Layout.maximumWidth: 138
                        }
                    }

                    MouseArea {
                        id: rowMouse

                        anchors.fill: parent
                        enabled: rowRoot.modelData.enabled
                        hoverEnabled: true
                        cursorShape: rowRoot.modelData.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.candidateSelected(rowRoot.modelData.id)
                    }
                }
            }

            Rectangle {
                width: parent.width
                height: 1
                color: root.lightMode ? "#E5EAF2" : "#1F2F4A"
            }

            Rectangle {
                width: parent.width
                height: 30
                color: "transparent"

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    anchors.topMargin: 5
                    anchors.bottomMargin: 4
                    text: qsTr("%1 %2 detected")
                        .arg(root.detectedCount)
                        .arg(root.detectedCount === 1 ? qsTr("subtitle") : qsTr("subtitles"))
                    color: root.lightMode ? "#64748B" : root.mutedTextColor
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }
}

