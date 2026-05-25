pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: root

    property real positionMs: 0
    property real durationMs: 0
    property var cutsModel
    property int selectedCutIndex: -1
    property bool lightMode: false
    property color textMain: "#F8FAFC"
    property color accent: "#38BDF8"

    signal seekRequested(real positionMs)
    signal markerSelected(int index, real positionMs)

    implicitHeight: 28
    spacing: 8

    function formatTime(ms) {
        var totalSeconds = Math.floor(ms / 1000)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var seconds = totalSeconds % 60

        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
    }

    function parseTimeMs(value) {
        var parts = String(value).trim().split(":")
        if (parts.length !== 3) return 0
        return (Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])) * 1000
    }

    Text {
        text: root.formatTime(root.positionMs)
        color: root.textMain
        font.pixelSize: 12
        Layout.preferredWidth: root.width < 900 ? 72 : 90
        Layout.preferredHeight: 24
        verticalAlignment: Text.AlignVCenter
    }

    Slider {
        id: timelineSlider
        Layout.fillWidth: true
        Layout.preferredHeight: 24
        from: 0
        to: root.durationMs > 0 ? root.durationMs : 1
        value: root.positionMs
        enabled: root.durationMs > 0
        onMoved: root.seekRequested(value)

        background: Rectangle {
            x: timelineSlider.leftPadding
            y: timelineSlider.topPadding + timelineSlider.availableHeight / 2 - height / 2
            implicitHeight: 6
            width: timelineSlider.availableWidth
            height: implicitHeight
            radius: 4
            color: root.lightMode ? "#CBD5E1" : "#334155"

            Rectangle {
                width: timelineSlider.visualPosition * parent.width
                height: parent.height
                radius: parent.radius
                color: root.accent
            }

            Repeater {
                model: root.cutsModel

                delegate: Item {
                    required property int index
                    required property var start
                    required property var end
                    required property var safeStart
                    required property var safeEnd
                    required property var reason
                    required property var tags

                    readonly property real markerStartMs: root.parseTimeMs(start)
                    readonly property real markerEndMs: root.parseTimeMs(end)
                    readonly property real safeStartMs: root.parseTimeMs(safeStart)
                    readonly property real safeEndMs: root.parseTimeMs(safeEnd)
                    readonly property real safeX: root.durationMs > 0 ? safeStartMs / root.durationMs * parent.width : 0
                    readonly property real safeW: root.durationMs > 0 ? Math.max(6, (safeEndMs - safeStartMs) / root.durationMs * parent.width) : 0
                    x: 0
                    y: -4
                    width: parent.width
                    height: parent.height + 6

                    Rectangle {
                        x: parent.safeX
                        y: 0
                        width: parent.safeW
                        height: parent.height
                        radius: 3
                        color: root.selectedCutIndex === parent.index ? "#F97316" : "#EA580C"
                        border.color: "#FDE68A"
                        border.width: root.selectedCutIndex === parent.index ? 1 : 0
                        opacity: 0.92
                    }

                    Rectangle {
                        x: root.durationMs > 0 ? parent.markerStartMs / root.durationMs * parent.width : 0
                        y: 3
                        width: root.durationMs > 0 ? Math.max(6, (parent.markerEndMs - parent.markerStartMs) / root.durationMs * parent.width) : 0
                        height: parent.height - 6
                        radius: 2
                        color: root.selectedCutIndex === parent.index ? "#38BDF8" : "#0891B2"
                    }

                    MouseArea {
                        x: parent.safeX
                        y: 0
                        width: parent.safeW
                        height: parent.height
                        hoverEnabled: true
                        onClicked: root.markerSelected(parent.index, parent.markerStartMs)

                        ToolTip.visible: containsMouse
                        ToolTip.text: "Requested: " + parent.start + " -> " + parent.end
                                      + "\nSafe cut: " + parent.safeStart + " -> " + parent.safeEnd
                                      + "\nReason: " + parent.reason + "\nTags: " + parent.tags
                    }
                }
            }
        }

        handle: Rectangle {
            x: timelineSlider.leftPadding + timelineSlider.visualPosition * (timelineSlider.availableWidth - width)
            y: timelineSlider.topPadding + timelineSlider.availableHeight / 2 - height / 2
            width: 16
            height: 16
            radius: 8
            color: root.lightMode ? "#FFFFFF" : "#E0F2FE"
            border.color: root.accent
            border.width: 3
        }
    }

    Text {
        text: root.durationMs > 0 ? root.formatTime(root.durationMs) : "00:00:00"
        color: root.textMain
        font.pixelSize: 12
        horizontalAlignment: Text.AlignRight
        verticalAlignment: Text.AlignVCenter
        Layout.preferredWidth: root.width < 900 ? 72 : 90
        Layout.preferredHeight: 24
    }
}
