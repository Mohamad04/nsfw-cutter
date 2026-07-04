pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../Shared"
import "time_utils.js" as TimeUtils
import "timeline_utils.js" as TimelineUtils

Rectangle {
    id: root

    required property var cutsModel

    property bool lightMode: false
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"

    property bool hasVideo: false
    property bool isPlaying: false
    property real positionMs: 0
    property real durationMs: 0
    property real volumeLevel: 0.85

    property string requestedStart: "00:00:00"
    property string requestedEnd: "00:00:00"
    property bool startPointSet: false
    property bool endPointSet: false
    property int draggingCutIndex: -1

    signal togglePlaybackRequested()
    signal seekByRequested(real seconds)
    signal seekRequested(real positionMs)
    signal volumeLevelChangeRequested(real value)

    signal beginCutTimelineDragRequested(int index, string mode, real trackX, real trackWidth)
    signal updateCutTimelineDragRequested(real trackX, real trackWidth)
    signal finishCutTimelineDragRequested()

    implicitHeight: 56

    radius: 12
    color: root.lightMode ? "#FFFFFF" : "#07101D"
    border.color: root.lightMode ? root.strokeColor : "#1C2E49"

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        spacing: 8

        PlayPauseButton {
            playing: root.isPlaying
            lightMode: root.lightMode
            enabled: root.hasVideo
            Layout.preferredWidth: 96
            Layout.preferredHeight: 40
            onClicked: root.togglePlaybackRequested()
        }

        BackwardFiveSeekButton {
            lightMode: root.lightMode
            enabled: root.hasVideo
            Layout.preferredWidth: 84
            Layout.preferredHeight: 36
            onClicked: root.seekByRequested(-5)
        }

        ForwardFiveSeekButton {
            lightMode: root.lightMode
            enabled: root.hasVideo
            Layout.preferredWidth: 84
            Layout.preferredHeight: 36
            onClicked: root.seekByRequested(5)
        }

        Text {
            text: TimeUtils.formatTime(root.positionMs) + " / " + TimeUtils.formatTime(root.durationMs)
            color: root.textColor
            font.pixelSize: 12
            Layout.preferredWidth: 142
            verticalAlignment: Text.AlignVCenter
        }

        Item {
            id: seekArea
            Layout.fillWidth: true
            Layout.preferredHeight: 32

            readonly property real selectionStartSeconds: TimelineUtils.markerSeconds(root.requestedStart, root.startPointSet)
            readonly property real selectionEndSeconds: TimelineUtils.markerSeconds(root.requestedEnd, root.endPointSet)
            readonly property bool hasStartMarker: Number.isFinite(selectionStartSeconds) && root.durationMs > 0
            readonly property bool hasEndMarker: Number.isFinite(selectionEndSeconds) && root.durationMs > 0
            readonly property bool hasPendingRange: hasStartMarker && hasEndMarker && selectionEndSeconds > selectionStartSeconds

            Slider {
                id: seekSlider

                anchors.fill: parent
                enabled: root.hasVideo && root.durationMs > 0 && root.draggingCutIndex < 0
                from: 0
                to: Math.max(1, root.durationMs)
                value: root.positionMs
                onMoved: root.seekRequested(value)

                background: Item {
                    id: timelineTrack

                    x: seekSlider.leftPadding
                    y: seekSlider.topPadding
                    width: seekSlider.availableWidth
                    height: seekSlider.availableHeight

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        height: 4
                        radius: 3
                        color: root.lightMode ? "#CBD5E1" : "#111B2B"

                        Rectangle {
                            width: seekSlider.visualPosition * parent.width
                            height: parent.height
                            radius: parent.radius
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: "#2F7BFF" }
                                GradientStop { position: 1.0; color: "#7CCBFF" }
                            }
                        }
                    }

                    Repeater {
                        model: root.cutsModel

                        delegate: Item {
                            id: cutTimelineItem

                            required property int index
                            readonly property var requestedRange: TimelineUtils.requestedCutRange(root.cutsModel.get(index))
                            readonly property real requestedStartSeconds: TimelineUtils.clampedTimelineSeconds(requestedRange.start, root.durationMs)
                            readonly property real requestedEndSeconds: TimelineUtils.clampedTimelineSeconds(requestedRange.end, root.durationMs)
                            readonly property real requestedX: TimelineUtils.timelineX(requestedStartSeconds, width, root.durationMs)
                            readonly property real requestedWidth: TimelineUtils.timelineX(requestedEndSeconds, width, root.durationMs) - requestedX
                            readonly property bool dragActive: root.draggingCutIndex === index

                            width: parent ? parent.width : 0
                            height: parent ? parent.height : 0
                            visible: root.durationMs > 0 && requestedRange.valid && requestedEndSeconds > requestedStartSeconds
                            z: dragActive ? 30 : 12

                            Rectangle {
                                id: requestedCutRange

                                visible: cutTimelineItem.visible
                                x: Math.max(0, Math.min(cutTimelineItem.width - width, cutTimelineItem.requestedX))
                                y: parent.height / 2 - 8
                                width: visible ? Math.max(3, cutTimelineItem.requestedWidth) : 0
                                height: 10
                                radius: 5
                                color: "#FF7448"
                                opacity: 0.35
                                border.color: "#E35B38"
                                border.width: 1
                                z: 2
                            }

                            MouseArea {
                                id: moveCutMouse

                                x: requestedCutRange.x + 5
                                y: requestedCutRange.y - 5
                                width: Math.max(0, requestedCutRange.width - 10)
                                height: requestedCutRange.height + 10
                                enabled: cutTimelineItem.visible && width > 0
                                hoverEnabled: true
                                cursorShape: Qt.OpenHandCursor
                                preventStealing: true

                                function trackX(mouseX, mouseY) {
                                    return mapToItem(timelineTrack, mouseX, mouseY).x
                                }

                                onPressed: function(mouse) {
                                    cursorShape = Qt.ClosedHandCursor
                                    root.beginCutTimelineDragRequested(
                                        cutTimelineItem.index,
                                        "move",
                                        trackX(mouse.x, mouse.y),
                                        timelineTrack.width
                                    )
                                }
                                onPositionChanged: function(mouse) {
                                    if (pressed)
                                        root.updateCutTimelineDragRequested(trackX(mouse.x, mouse.y), timelineTrack.width)
                                }
                                onReleased: {
                                    cursorShape = Qt.OpenHandCursor
                                    root.finishCutTimelineDragRequested()
                                }
                                onCanceled: {
                                    cursorShape = Qt.OpenHandCursor
                                    root.finishCutTimelineDragRequested()
                                }
                            }

                            Rectangle {
                                id: requestedStartHandle

                                visible: cutTimelineItem.visible
                                x: Math.max(0, Math.min(parent.width - width, requestedCutRange.x - width / 2))
                                y: 3
                                width: 7
                                height: parent.height - 6
                                radius: 3
                                color: "#7CFF6B"
                                border.color: "#102719"
                                border.width: 1

                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.SplitHCursor
                                    preventStealing: true

                                    function trackX(mouseX, mouseY) {
                                        return mapToItem(timelineTrack, mouseX, mouseY).x
                                    }

                                    onPressed: function(mouse) {
                                        root.beginCutTimelineDragRequested(
                                            cutTimelineItem.index,
                                            "start",
                                            trackX(mouse.x, mouse.y),
                                            timelineTrack.width
                                        )
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (pressed)
                                            root.updateCutTimelineDragRequested(trackX(mouse.x, mouse.y), timelineTrack.width)
                                    }
                                    onReleased: root.finishCutTimelineDragRequested()
                                    onCanceled: root.finishCutTimelineDragRequested()
                                }
                            }

                            Rectangle {
                                id: requestedEndHandle

                                visible: cutTimelineItem.visible
                                x: Math.max(0, Math.min(parent.width - width, requestedCutRange.x + requestedCutRange.width - width / 2))
                                y: 3
                                width: 7
                                height: parent.height - 6
                                radius: 3
                                color: "#FF7448"
                                border.color: "#2A1712"
                                border.width: 1

                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.SplitHCursor
                                    preventStealing: true

                                    function trackX(mouseX, mouseY) {
                                        return mapToItem(timelineTrack, mouseX, mouseY).x
                                    }

                                    onPressed: function(mouse) {
                                        root.beginCutTimelineDragRequested(
                                            cutTimelineItem.index,
                                            "end",
                                            trackX(mouse.x, mouse.y),
                                            timelineTrack.width
                                        )
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (pressed)
                                            root.updateCutTimelineDragRequested(trackX(mouse.x, mouse.y), timelineTrack.width)
                                    }
                                    onReleased: root.finishCutTimelineDragRequested()
                                    onCanceled: root.finishCutTimelineDragRequested()
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: pendingSelectionRange

                        readonly property real startSeconds: TimelineUtils.clampedTimelineSeconds(seekArea.selectionStartSeconds, root.durationMs)
                        readonly property real endSeconds: TimelineUtils.clampedTimelineSeconds(seekArea.selectionEndSeconds, root.durationMs)
                        readonly property real calculatedX: TimelineUtils.timelineX(startSeconds, parent.width, root.durationMs)
                        readonly property real calculatedWidth: TimelineUtils.timelineX(endSeconds, parent.width, root.durationMs) - calculatedX

                        enabled: false
                        visible: seekArea.hasPendingRange && endSeconds > startSeconds
                        x: Math.max(0, Math.min(parent.width - width, calculatedX))
                        y: parent.height / 2 - height / 2
                        width: visible ? Math.max(3, calculatedWidth) : 0
                        height: 10
                        radius: 5
                        color: "#FF7448"
                        opacity: 0.35
                        border.color: "#E35B38"
                        border.width: 1
                        z: 15
                    }

                    Rectangle {
                        id: startMarker

                        enabled: false
                        visible: seekArea.hasStartMarker
                        x: Math.max(0, Math.min(parent.width - width, TimelineUtils.timelineX(seekArea.selectionStartSeconds, parent.width, root.durationMs) - width / 2))
                        y: 4
                        width: 3
                        height: parent.height - 8
                        radius: 2
                        color: "#7CFF6B"
                        z: 18
                    }

                    Rectangle {
                        id: endMarker

                        enabled: false
                        visible: seekArea.hasEndMarker
                        x: Math.max(0, Math.min(parent.width - width, TimelineUtils.timelineX(seekArea.selectionEndSeconds, parent.width, root.durationMs) - width / 2))
                        y: 4
                        width: 3
                        height: parent.height - 8
                        radius: 2
                        color: "#FF7448"
                        z: 18
                    }
                }

                handle: Rectangle {
                    x: seekSlider.leftPadding + seekSlider.visualPosition * (seekSlider.availableWidth - width)
                    y: seekSlider.topPadding + seekSlider.availableHeight / 2 - height / 2
                    width: 12
                    height: 12
                    radius: 6
                    color: root.lightMode ? "#FFFFFF" : "#E0F2FE"
                    border.color: root.accentColor
                    border.width: 2
                }
            }

            Item {
                id: cutDragLayer

                x: seekSlider.leftPadding
                y: seekSlider.topPadding
                width: seekSlider.availableWidth
                height: seekSlider.availableHeight
                visible: root.hasVideo && root.durationMs > 0
                z: 50

                Repeater {
                    model: root.cutsModel

                    delegate: Item {
                        id: cutDragDelegate

                        required property int index
                        readonly property var requestedRange: TimelineUtils.requestedCutRange(root.cutsModel.get(index))
                        readonly property real requestedStartSeconds: TimelineUtils.clampedTimelineSeconds(requestedRange.start, root.durationMs)
                        readonly property real requestedEndSeconds: TimelineUtils.clampedTimelineSeconds(requestedRange.end, root.durationMs)
                        readonly property real requestedX: TimelineUtils.timelineX(requestedStartSeconds, width, root.durationMs)
                        readonly property real requestedWidth: TimelineUtils.timelineX(requestedEndSeconds, width, root.durationMs) - requestedX
                        readonly property real edgeHitWidth: 18
                        readonly property bool dragActive: root.draggingCutIndex === index

                        width: parent ? parent.width : 0
                        height: parent ? parent.height : 0
                        visible: root.durationMs > 0 && requestedRange.valid && requestedEndSeconds > requestedStartSeconds
                        z: dragActive ? 100 : 10

                        function trackXFrom(mouseArea, mouseX, mouseY) {
                            return mouseArea.mapToItem(cutDragLayer, mouseX, mouseY).x
                        }

                        MouseArea {
                            id: moveCutDragArea

                            x: Math.max(0, Math.min(parent.width - width, cutDragDelegate.requestedX + cutDragDelegate.edgeHitWidth / 2))
                            y: 0
                            width: Math.max(0, cutDragDelegate.requestedWidth - cutDragDelegate.edgeHitWidth)
                            height: parent.height
                            enabled: cutDragDelegate.visible && width > 0
                            acceptedButtons: Qt.LeftButton
                            hoverEnabled: true
                            preventStealing: true
                            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor

                            onPressed: function(mouse) {
                                mouse.accepted = true
                                root.beginCutTimelineDragRequested(
                                    cutDragDelegate.index,
                                    "move",
                                    cutDragDelegate.trackXFrom(moveCutDragArea, mouse.x, mouse.y),
                                    cutDragLayer.width
                                )
                            }
                            onPositionChanged: function(mouse) {
                                if (pressed)
                                    root.updateCutTimelineDragRequested(
                                        cutDragDelegate.trackXFrom(moveCutDragArea, mouse.x, mouse.y),
                                        cutDragLayer.width
                                    )
                            }
                            onReleased: function(mouse) {
                                mouse.accepted = true
                                root.finishCutTimelineDragRequested()
                            }
                            onCanceled: root.finishCutTimelineDragRequested()
                        }

                        MouseArea {
                            id: startCutDragArea

                            x: Math.max(0, Math.min(parent.width - width, cutDragDelegate.requestedX - width / 2))
                            y: 0
                            width: cutDragDelegate.edgeHitWidth
                            height: parent.height
                            enabled: cutDragDelegate.visible
                            acceptedButtons: Qt.LeftButton
                            hoverEnabled: true
                            preventStealing: true
                            cursorShape: Qt.SplitHCursor
                            z: 2

                            onPressed: function(mouse) {
                                mouse.accepted = true
                                root.beginCutTimelineDragRequested(
                                    cutDragDelegate.index,
                                    "start",
                                    cutDragDelegate.trackXFrom(startCutDragArea, mouse.x, mouse.y),
                                    cutDragLayer.width
                                )
                            }
                            onPositionChanged: function(mouse) {
                                if (pressed)
                                    root.updateCutTimelineDragRequested(
                                        cutDragDelegate.trackXFrom(startCutDragArea, mouse.x, mouse.y),
                                        cutDragLayer.width
                                    )
                            }
                            onReleased: function(mouse) {
                                mouse.accepted = true
                                root.finishCutTimelineDragRequested()
                            }
                            onCanceled: root.finishCutTimelineDragRequested()
                        }

                        MouseArea {
                            id: endCutDragArea

                            x: Math.max(0, Math.min(parent.width - width, cutDragDelegate.requestedX + cutDragDelegate.requestedWidth - width / 2))
                            y: 0
                            width: cutDragDelegate.edgeHitWidth
                            height: parent.height
                            enabled: cutDragDelegate.visible
                            acceptedButtons: Qt.LeftButton
                            hoverEnabled: true
                            preventStealing: true
                            cursorShape: Qt.SplitHCursor
                            z: 3

                            onPressed: function(mouse) {
                                mouse.accepted = true
                                root.beginCutTimelineDragRequested(
                                    cutDragDelegate.index,
                                    "end",
                                    cutDragDelegate.trackXFrom(endCutDragArea, mouse.x, mouse.y),
                                    cutDragLayer.width
                                )
                            }
                            onPositionChanged: function(mouse) {
                                if (pressed)
                                    root.updateCutTimelineDragRequested(
                                        cutDragDelegate.trackXFrom(endCutDragArea, mouse.x, mouse.y),
                                        cutDragLayer.width
                                    )
                            }
                            onReleased: function(mouse) {
                                mouse.accepted = true
                                root.finishCutTimelineDragRequested()
                            }
                            onCanceled: root.finishCutTimelineDragRequested()
                        }
                    }
                }
            }
        }

        VectorIcon {
            Layout.preferredWidth: 18
            Layout.preferredHeight: 18
            name: root.volumeLevel <= 0.01 ? "mute" : "volume"
            iconColor: root.mutedTextColor
        }

        Slider {
            id: volumeSlider

            Layout.preferredWidth: 92
            Layout.preferredHeight: 32
            from: 0
            to: 1
            value: root.volumeLevel
            onMoved: root.volumeLevelChangeRequested(value)

            background: Rectangle {
                x: volumeSlider.leftPadding
                y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                width: volumeSlider.availableWidth
                height: 4
                radius: 3
                color: root.lightMode ? "#CBD5E1" : "#17263B"

                Rectangle {
                    width: volumeSlider.visualPosition * parent.width
                    height: parent.height
                    radius: parent.radius
                    color: "#5AA4FF"
                }
            }

            handle: Rectangle {
                x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                width: 12
                height: 12
                radius: 6
                color: root.lightMode ? "#FFFFFF" : "#E0F2FE"
                border.color: root.accentColor
            }
        }

        AppButton {
            text: ""
            iconName: "fullscreen"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: false
            Layout.preferredWidth: 42
            Layout.preferredHeight: 36
            ToolTip.visible: hovered
            ToolTip.text: qsTr("Fullscreen is not connected in this phase")
        }
    }
}
