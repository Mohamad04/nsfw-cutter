pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

RowLayout {
    id: root

    property real positionMs: 0
    property real durationMs: 0
    property var cutsModel
    property int selectedCutIndex: -1
    property var cutPreview: ({ "visible": false })
    property bool lightMode: false
    property color textMain: "#F8FAFC"
    property color accent: "#38BDF8"

    signal seekRequested(real positionMs)
    signal markerSelected(int index, real positionMs)
    signal cutSelected(int index)
    signal cutRangeChanged(int index, real startMs, real endMs)

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
        var seconds = Number(parts[2])
        if (!Number.isFinite(seconds)) return 0
        return (Number(parts[0]) * 3600 + Number(parts[1]) * 60 + seconds) * 1000
    }

    function clampMs(value) {
        if (!Number.isFinite(value)) return 0
        return Math.max(0, Math.min(root.durationMs, value))
    }

    function draftSeconds(key) {
        if (!root.cutPreview || root.cutPreview[key] === undefined || root.cutPreview[key] === null) return NaN
        return Number(root.cutPreview[key])
    }

    function draftMs(key) {
        return root.draftSeconds(key) * 1000
    }

    function hasDraftRange() {
        var startMs = root.draftMs("requested_start")
        var endMs = root.draftMs("requested_end")
        return root.durationMs > 0
            && root.cutPreview
            && root.cutPreview.visible === true
            && Number.isFinite(startMs)
            && Number.isFinite(endMs)
            && startMs !== endMs
    }

    function hasDraftSafeRange() {
        var startMs = root.draftMs("safe_start")
        var endMs = root.draftMs("safe_end")
        return root.hasDraftRange()
            && root.cutPreview.has_safe === true
            && Number.isFinite(startMs)
            && Number.isFinite(endMs)
            && endMs > startMs
    }

    Text {
        text: root.formatTime(root.positionMs)
        color: root.textMain
        font.pixelSize: 12
        Layout.preferredWidth: root.width < 900 ? 72 : 90
        Layout.preferredHeight: 24
        verticalAlignment: Text.AlignVCenter
    }

    Item {
        id: timelineArea

        Layout.fillWidth: true
        Layout.preferredHeight: 24
        enabled: root.durationMs > 0

        function msFromTrackX(trackX) {
            if (root.durationMs <= 0 || timelineTrack.width <= 0) return 0
            return root.clampMs(trackX / timelineTrack.width * root.durationMs)
        }

        function trackXFromMs(ms) {
            if (root.durationMs <= 0 || timelineTrack.width <= 0) return 0
            return root.clampMs(ms) / root.durationMs * timelineTrack.width
        }

        MouseArea {
            anchors.fill: parent
            enabled: root.durationMs > 0
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            z: -1

            function seekFromMouse(mouse) {
                var point = mapToItem(timelineTrack, mouse.x, mouse.y)
                root.seekRequested(timelineArea.msFromTrackX(point.x))
            }

            onPressed: function(mouse) {
                mouse.accepted = true
                seekFromMouse(mouse)
            }
            onPositionChanged: function(mouse) {
                if (pressed) seekFromMouse(mouse)
            }
        }

        Rectangle {
            id: timelineTrack

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            height: 6
            radius: 4
            color: root.lightMode ? "#CBD5E1" : "#334155"

            Rectangle {
                width: root.durationMs > 0 ? root.positionMs / root.durationMs * parent.width : 0
                height: parent.height
                radius: parent.radius
                color: root.accent
            }

            Repeater {
                model: root.cutsModel

                delegate: Item {
                    id: cutMarker

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
                    readonly property real requestedX: root.durationMs > 0 ? markerStartMs / root.durationMs * parent.width : 0
                    readonly property real requestedW: root.durationMs > 0 ? Math.max(6, (markerEndMs - markerStartMs) / root.durationMs * parent.width) : 0
                    x: 0
                    y: -4
                    z: root.selectedCutIndex === cutMarker.index ? 4 : 3
                    width: parent.width
                    height: parent.height + 6

                    function msFromX(trackX) {
                        if (root.durationMs <= 0 || width <= 0) return 0
                        return root.clampMs(trackX / width * root.durationMs)
                    }

                    Rectangle {
                        x: parent.safeX
                        y: 0
                        width: parent.safeW
                        height: parent.height
                        radius: 3
                        color: root.selectedCutIndex === parent.index ? "#22B454" : "#1FA34A"
                        border.color: root.lightMode ? "#86EFAC" : "#22C55E"
                        border.width: root.selectedCutIndex === parent.index ? 1 : 0
                        opacity: 0.92
                    }

                    Rectangle {
                        x: parent.requestedX
                        y: 3
                        width: parent.requestedW
                        height: parent.height - 6
                        radius: 2
                        color: root.selectedCutIndex === parent.index ? "#F59E3D" : "#F07818"
                    }

                    MouseArea {
                        property real pressMs: 0
                        property real dragStartMs: 0
                        property real dragEndMs: 0

                        x: Math.max(0, parent.requestedX - 8)
                        y: -8
                        width: Math.max(0, Math.min(parent.width - x, Math.max(parent.requestedW + 16, 28)))
                        height: parent.height + 16
                        z: 4
                        hoverEnabled: true
                        preventStealing: true
                        cursorShape: Qt.SizeAllCursor
                        onPressed: function(mouse) {
                            mouse.accepted = true
                            var point = mapToItem(cutMarker, mouse.x, mouse.y)
                            pressMs = cutMarker.msFromX(point.x)
                            dragStartMs = cutMarker.markerStartMs
                            dragEndMs = cutMarker.markerEndMs
                            root.cutSelected(cutMarker.index)
                        }
                        onPositionChanged: function(mouse) {
                            if (!pressed || root.durationMs <= 0) return
                            var point = mapToItem(cutMarker, mouse.x, mouse.y)
                            var deltaMs = cutMarker.msFromX(point.x) - pressMs
                            var lengthMs = Math.max(100, dragEndMs - dragStartMs)
                            var newStart = root.clampMs(dragStartMs + deltaMs)
                            var maxStart = Math.max(0, root.durationMs - lengthMs)
                            newStart = Math.max(0, Math.min(maxStart, newStart))
                            root.cutRangeChanged(cutMarker.index, newStart, newStart + lengthMs)
                        }
                        onClicked: root.cutSelected(cutMarker.index)

                        ToolTip.visible: containsMouse
                        ToolTip.text: "Drag to move cut\nRequested: " + cutMarker.start + " -> " + cutMarker.end
                                      + "\nSafe cut: " + cutMarker.safeStart + " -> " + cutMarker.safeEnd
                                      + "\nReason: " + cutMarker.reason + "\nTags: " + cutMarker.tags
                    }

                    Rectangle {
                        x: Math.max(0, parent.requestedX - 4)
                        y: -2
                        width: 8
                        height: parent.height + 4
                        z: 6
                        radius: 4
                        color: root.lightMode ? "#FFFFFF" : "#E0F2FE"
                        border.color: root.accent
                        border.width: 2
                        visible: root.selectedCutIndex === parent.index

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            preventStealing: true
                            cursorShape: Qt.SizeHorCursor
                            onPressed: function(mouse) {
                                mouse.accepted = true
                                root.cutSelected(cutMarker.index)
                            }
                            onPositionChanged: function(mouse) {
                                if (!pressed) return
                                var point = mapToItem(cutMarker, mouse.x, mouse.y)
                                var newStart = Math.min(cutMarker.msFromX(point.x), cutMarker.markerEndMs - 100)
                                root.cutRangeChanged(cutMarker.index, Math.max(0, newStart), cutMarker.markerEndMs)
                            }
                            ToolTip.visible: containsMouse
                            ToolTip.text: "Drag start"
                        }
                    }

                    Rectangle {
                        x: Math.min(parent.width - 8, parent.requestedX + parent.requestedW - 4)
                        y: -2
                        width: 8
                        height: parent.height + 4
                        z: 6
                        radius: 4
                        color: root.lightMode ? "#FFFFFF" : "#E0F2FE"
                        border.color: root.accent
                        border.width: 2
                        visible: root.selectedCutIndex === parent.index

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            preventStealing: true
                            cursorShape: Qt.SizeHorCursor
                            onPressed: function(mouse) {
                                mouse.accepted = true
                                root.cutSelected(cutMarker.index)
                            }
                            onPositionChanged: function(mouse) {
                                if (!pressed) return
                                var point = mapToItem(cutMarker, mouse.x, mouse.y)
                                var newEnd = Math.max(cutMarker.msFromX(point.x), cutMarker.markerStartMs + 100)
                                root.cutRangeChanged(cutMarker.index, cutMarker.markerStartMs, Math.min(root.durationMs, newEnd))
                            }
                            ToolTip.visible: containsMouse
                            ToolTip.text: "Drag end"
                        }
                    }

                    MouseArea {
                        z: -1
                        x: parent.safeX
                        y: 0
                        width: parent.safeW
                        height: parent.height
                        hoverEnabled: true
                        onClicked: root.cutSelected(parent.index)

                        ToolTip.visible: containsMouse
                        ToolTip.text: "Requested: " + parent.start + " -> " + parent.end
                                      + "\nSafe cut: " + parent.safeStart + " -> " + parent.safeEnd
                                      + "\nReason: " + parent.reason + "\nTags: " + parent.tags
                    }
                }
            }

            Rectangle {
                readonly property real startMs: root.draftMs("safe_start")
                readonly property real endMs: root.draftMs("safe_end")

                visible: root.hasDraftSafeRange()
                z: 1
                x: visible ? startMs / root.durationMs * parent.width : 0
                y: -5
                width: visible ? Math.max(8, (endMs - startMs) / root.durationMs * parent.width) : 0
                height: parent.height + 10
                radius: 4
                color: "#22B454"
                opacity: 0.68
                border.color: root.lightMode ? "#86EFAC" : "#22C55E"
                border.width: 1
            }

            Rectangle {
                readonly property real startMs: root.draftMs("requested_start")
                readonly property real endMs: root.draftMs("requested_end")
                readonly property real leftMs: Math.min(startMs, endMs)
                readonly property real rightMs: Math.max(startMs, endMs)

                visible: root.hasDraftRange()
                z: 1
                x: visible ? leftMs / root.durationMs * parent.width : 0
                y: -2
                width: visible ? Math.max(8, (rightMs - leftMs) / root.durationMs * parent.width) : 0
                height: parent.height + 4
                radius: 4
                color: root.cutPreview.valid === true ? "#F59E3D" : "#EF4444"
                opacity: 0.82
                border.color: root.lightMode ? "#FFFFFF" : "#F8FAFC"
                border.width: 1

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    hoverEnabled: true
                    ToolTip.visible: containsMouse
                    ToolTip.text: root.cutPreview.valid === true
                        ? "Draft requested cut\nOrange: requested range\nGreen: safe adjusted removal"
                        : "Invalid draft cut\nEnd time must be after start time"
                }
            }
        }

        Rectangle {
            x: Math.max(0, Math.min(parent.width - width, timelineArea.trackXFromMs(root.positionMs) - width / 2))
            anchors.verticalCenter: parent.verticalCenter
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

