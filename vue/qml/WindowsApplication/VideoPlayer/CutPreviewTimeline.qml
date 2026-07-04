pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../Shared"

Rectangle {
    id: root
    objectName: "cutPreviewTimeline"

    property real durationSeconds: 0
    property real currentSeconds: 0
    property bool hasRequestedStart: false
    property bool hasRequestedEnd: false
    property real requestedStartSeconds: 0
    property real requestedEndSeconds: 0
    property bool hasSafeStart: false
    property bool hasSafeEnd: false
    property real safeStartSeconds: 0
    property real safeEndSeconds: 0
    // Kept for compatibility with existing callers; this timeline no longer renders keyframes.
    property var keyframesSeconds: []

    readonly property color requestedColor: "#FF7448"
    readonly property color startColor: "#7CFF6B"
    readonly property color endColor: "#FF7448"
    readonly property color playheadColor: "#FFFFFF"
    readonly property color panelBg: "#07101D"
    readonly property color trackBg: "#0A1626"
    readonly property color strokeColor: "#1B3658"
    readonly property color textColor: "#EAF2FF"
    readonly property color mutedText: "#8FA6C5"
    readonly property bool compact: root.width < 760 || root.height <= 110
    readonly property bool narrow: root.width < 620
    readonly property bool showLeftTimeBlock: !root.narrow
    readonly property bool showDecorativeLabels: !root.compact && root.width >= 720
    readonly property bool showLegend: !root.compact && root.width >= 760
    readonly property int outerMargin: root.compact ? 8 : 10
    readonly property int timelineAreaHeight: root.compact ? 48 : 64
    readonly property int timelineTrackHeight: root.compact ? 34 : 42
    readonly property bool hasDuration: Number.isFinite(root.durationSeconds) && root.durationSeconds > 0
    readonly property bool hasValidRequestedStart: root.hasDuration
        && root.hasRequestedStart
        && Number.isFinite(root.requestedStartSeconds)
    readonly property bool hasValidRequestedEnd: root.hasDuration
        && root.hasRequestedEnd
        && Number.isFinite(root.requestedEndSeconds)
    readonly property bool hasRequestedRange: root.hasValidRequestedStart
        && root.hasValidRequestedEnd
        && root.requestedEndSeconds > root.requestedStartSeconds

    signal seekRequested(real seconds)

    implicitHeight: root.compact ? 96 : 150
    implicitWidth: 900
    radius: 14
    color: root.panelBg
    border.color: root.strokeColor
    border.width: 1
    clip: true

    function clampSeconds(seconds) {
        if (!Number.isFinite(seconds) || !root.hasDuration)
            return 0
        return Math.max(0, Math.min(seconds, root.durationSeconds))
    }

    function xForTime(seconds) {
        if (!root.hasDuration || timelineTrack.width <= 0)
            return 0
        var clamped = Math.max(0, Math.min(seconds, root.durationSeconds))
        return (clamped / root.durationSeconds) * timelineTrack.width
    }

    function formatTime(seconds) {
        var value = root.clampSeconds(seconds)
        var totalSeconds = Math.floor(value)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var wholeSeconds = totalSeconds % 60

        function pad(number) {
            return number < 10 ? "0" + number : "" + number
        }

        return pad(hours) + ":" + pad(minutes) + ":" + pad(wholeSeconds)
    }

    function rangeX(startSeconds) {
        return Math.max(0, Math.min(timelineTrack.width, root.xForTime(startSeconds)))
    }

    function rangeWidth(startSeconds, endSeconds) {
        if (!root.hasDuration)
            return 0
        var startX = root.xForTime(startSeconds)
        var endX = root.xForTime(endSeconds)
        return Math.max(3, Math.abs(endX - startX))
    }

    function secondsAtTrackX(trackX) {
        if (!root.hasDuration || timelineTrack.width <= 0)
            return 0
        var clampedX = Math.max(0, Math.min(trackX, timelineTrack.width))
        return clampedX / timelineTrack.width * root.durationSeconds
    }

    function tooltipTextForPoint(trackX, trackY) {
        var seconds = root.secondsAtTrackX(trackX)
        var overRequested = root.hasRequestedRange
            && seconds >= root.requestedStartSeconds
            && seconds <= root.requestedEndSeconds
            && trackY >= requestedRange.y - 3
            && trackY <= requestedRange.y + requestedRange.height + 3

        if (overRequested)
            return qsTr("Requested: %1 -> %2").arg(root.formatTime(root.requestedStartSeconds)).arg(root.formatTime(root.requestedEndSeconds))
        return root.formatTime(seconds)
    }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: "transparent"
        border.color: "#2B466A"
        opacity: 0.35
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 1
        color: "#4F9BFF"
        opacity: 0.28
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: root.outerMargin
        spacing: root.compact ? 10 : 16

        Rectangle {
            visible: root.showLeftTimeBlock
            Layout.preferredWidth: root.compact ? 126 : 180
            Layout.fillHeight: true
            radius: 12
            color: "#091827"
            border.color: "#172D49"
            border.width: 1

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: root.compact ? 12 : 18
                anchors.rightMargin: root.compact ? 12 : 18
                spacing: root.compact ? 4 : 8

                Text {
                    width: parent.width
                    text: root.formatTime(root.currentSeconds)
                    color: root.textColor
                    font.pixelSize: root.compact ? 22 : 34
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }

                Text {
                    width: parent.width
                    text: "/ " + root.formatTime(root.durationSeconds)
                    color: root.mutedText
                    font.pixelSize: root.compact ? 14 : 22
                    font.weight: Font.Medium
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: root.compact ? 4 : 6

            Item {
                id: timelinePreviewArea

                Layout.fillWidth: true
                Layout.preferredHeight: root.timelineAreaHeight
                clip: false

                property bool tooltipVisible: false
                property real tooltipX: 0
                property string tooltipText: ""

                Rectangle {
                    id: timelineTrack

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    height: root.timelineTrackHeight
                    radius: 8
                    color: root.trackBg
                    border.color: "#263C5E"
                    border.width: 1
                    clip: true

                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#07101D" }
                            GradientStop { position: 0.5; color: "#102033" }
                            GradientStop { position: 1.0; color: "#07101D" }
                        }
                        opacity: 0.68
                    }

                    Rectangle {
                        id: requestedRange

                        visible: root.hasRequestedRange
                        x: root.rangeX(root.requestedStartSeconds)
                        y: root.compact ? 5 : 5
                        width: root.rangeWidth(root.requestedStartSeconds, root.requestedEndSeconds)
                        height: root.compact ? 13 : 18
                        radius: 6
                        color: root.requestedColor
                        opacity: 0.30
                        border.color: "#E35B38"
                        border.width: 1
                        z: 6
                    }

                    Rectangle {
                        visible: root.hasValidRequestedStart
                        x: Math.max(0, Math.min(timelineTrack.width - width, root.xForTime(root.requestedStartSeconds) - width / 2))
                        y: 0
                        width: 4
                        height: timelineTrack.height
                        radius: 2
                        color: root.startColor
                        z: 8
                    }

                    Rectangle {
                        visible: root.hasValidRequestedEnd
                        x: Math.max(0, Math.min(timelineTrack.width - width, root.xForTime(root.requestedEndSeconds) - width / 2))
                        y: 0
                        width: 4
                        height: timelineTrack.height
                        radius: 2
                        color: root.endColor
                        z: 8
                    }

                    Rectangle {
                        visible: root.hasDuration
                        x: Math.max(0, Math.min(timelineTrack.width - width, root.xForTime(root.currentSeconds) - width / 2))
                        y: -4
                        width: 2
                        height: timelineTrack.height + 8
                        radius: 1
                        color: root.playheadColor
                        z: 10
                    }
                }

                Text {
                    anchors.left: timelineTrack.left
                    anchors.bottom: timelineTrack.top
                    anchors.bottomMargin: 4
                    visible: root.showDecorativeLabels && root.hasRequestedRange
                    text: qsTr("REQUESTED CUT")
                    color: root.requestedColor
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }

                MouseArea {
                    id: timelineMouseArea

                    anchors.fill: timelineTrack
                    acceptedButtons: Qt.LeftButton
                    cursorShape: root.hasDuration ? Qt.PointingHandCursor : Qt.ArrowCursor
                    enabled: root.hasDuration
                    hoverEnabled: true
                    z: 60

                    function updateTooltip(mouse) {
                        var trackX = Math.max(0, Math.min(mouse.x, timelineTrack.width))
                        timelinePreviewArea.tooltipX = timelineTrack.x + trackX
                        timelinePreviewArea.tooltipText = root.tooltipTextForPoint(trackX, mouse.y)
                        timelinePreviewArea.tooltipVisible = root.hasDuration
                    }

                    onEntered: timelinePreviewArea.tooltipVisible = root.hasDuration
                    onPositionChanged: function(mouse) {
                        updateTooltip(mouse)
                    }
                    onPressed: function(mouse) {
                        updateTooltip(mouse)
                        root.seekRequested(root.secondsAtTrackX(mouse.x))
                        mouse.accepted = true
                    }
                    onExited: timelinePreviewArea.tooltipVisible = false
                    onCanceled: timelinePreviewArea.tooltipVisible = false
                }

                Rectangle {
                    id: hoverTooltip

                    visible: timelinePreviewArea.tooltipVisible && timelinePreviewArea.tooltipText.length > 0
                    x: Math.max(0, Math.min(timelinePreviewArea.width - width, timelinePreviewArea.tooltipX - width / 2))
                    y: Math.max(0, timelineTrack.y - height - 8)
                    z: 80
                    width: hoverTooltipText.implicitWidth + 20
                    height: 30
                    radius: 8
                    color: "#0A1626"
                    border.color: "#1B3658"
                    border.width: 1

                    Text {
                        id: hoverTooltipText

                        anchors.centerIn: parent
                        text: timelinePreviewArea.tooltipText
                        color: "#EAF2FF"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: root.compact ? 16 : 20

                Text {
                    text: "00:00:00"
                    color: root.mutedText
                    font.pixelSize: root.compact ? 10 : 12
                    Layout.preferredWidth: root.compact ? 72 : 92
                }

                Text {
                    text: root.formatTime(root.currentSeconds)
                    color: root.mutedText
                    font.pixelSize: root.compact ? 10 : 12
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }

                Text {
                    text: root.formatTime(root.durationSeconds)
                    color: root.mutedText
                    font.pixelSize: root.compact ? 10 : 12
                    horizontalAlignment: Text.AlignRight
                    Layout.preferredWidth: root.compact ? 72 : 92
                }
            }

            Flow {
                visible: root.showLegend
                Layout.fillWidth: true
                Layout.preferredHeight: root.showLegend ? 26 : 0
                spacing: 12

                Row {
                    spacing: 7
                    height: 24

                    Rectangle {
                        width: 10
                        height: 16
                        radius: 4
                        color: "transparent"
                        border.color: root.startColor
                        border.width: 2
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        text: qsTr("Start Requested")
                        color: root.mutedText
                        font.pixelSize: 11
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Row {
                    spacing: 7
                    height: 24

                    Rectangle {
                        width: 10
                        height: 16
                        radius: 4
                        color: "transparent"
                        border.color: root.endColor
                        border.width: 2
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        text: qsTr("End Requested")
                        color: root.mutedText
                        font.pixelSize: 11
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

            }
        }
    }
}

