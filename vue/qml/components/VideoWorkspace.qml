pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Rectangle {
    id: root
    objectName: "videoWorkspace"

    required property var cutsModel
    property bool lightMode: false
    property color panelColor: "#0C1625"
    property color videoColor: "#020617"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property real volumeLevel: 0.85
    property string requestedStart: "00:00:00"
    property string requestedEnd: "00:00:00"
    property var keyframeInfo: defaultKeyframeInfo("Set start and end points to create a cut.")
    property var cutPreview: ({ "visible": false })
    readonly property real durationMs: player.duration
    readonly property real positionMs: player.position
    readonly property bool hasVideo: appController.videoUrl.length > 0
    readonly property bool isPlaying: player.playbackState === MediaPlayer.PlayingState

    signal cutAdded(var cut)

    radius: 10
    color: root.panelColor
    border.color: root.strokeColor
    clip: true

    AppTheme { id: theme }

    function defaultKeyframeInfo(message) {
        return {
            "valid": false,
            "error": message || "",
            "requested_start": 0,
            "requested_end": 0,
            "safe_start": null,
            "safe_end": null,
            "previous_keyframe_start": null,
            "next_keyframe_start": null,
            "previous_keyframe_end": null,
            "next_keyframe_end": null,
            "extra_before": 0,
            "extra_after": 0
        }
    }

    function pad(value) {
        return value < 10 ? "0" + value : "" + value
    }

    function padMillis(value) {
        if (value < 10) return "00" + value
        if (value < 100) return "0" + value
        return "" + value
    }

    function formatTime(ms, includeMilliseconds) {
        if (!Number.isFinite(ms) || ms <= 0) return "00:00:00"
        var totalMilliseconds = Math.max(0, Math.round(ms))
        var totalSeconds = Math.floor(totalMilliseconds / 1000)
        var milliseconds = totalMilliseconds % 1000
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var seconds = totalSeconds % 60
        var text = pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
        if (includeMilliseconds === true && milliseconds > 0) text += "." + padMillis(milliseconds)
        return text
    }

    function formatSeconds(seconds) {
        if (seconds === null || seconds === undefined || seconds === "") return ""
        var value = Number(seconds)
        if (!Number.isFinite(value)) return ""
        value = Math.max(0, value)
        var totalMilliseconds = Math.round(value * 1000)
        var totalSeconds = Math.floor(totalMilliseconds / 1000)
        var milliseconds = totalMilliseconds % 1000
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var wholeSeconds = totalSeconds % 60
        var text = pad(hours) + ":" + pad(minutes) + ":" + pad(wholeSeconds)
        if (milliseconds > 0) text += "." + padMillis(milliseconds)
        return text
    }

    function parseTimeMs(timeText) {
        var parts = String(timeText).trim().split(":")
        if (parts.length !== 3) return -1
        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var seconds = Number(parts[2])
        if (!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(seconds)) return -1
        if (hours < 0 || minutes < 0 || minutes > 59 || seconds < 0 || seconds >= 60) return -1
        return ((hours * 3600) + (minutes * 60) + seconds) * 1000
    }

    function seekBy(seconds) {
        if (!root.hasVideo) return
        var nextPosition = player.position + seconds * 1000
        if (nextPosition < 0) nextPosition = 0
        if (player.duration > 0 && nextPosition > player.duration) nextPosition = player.duration
        player.position = nextPosition
    }

    function togglePlayback() {
        if (!root.hasVideo) return
        if (root.isPlaying) player.pause()
        else player.play()
    }

    function markStart() {
        if (!root.hasVideo) return
        root.requestedStart = root.formatTime(player.position, true)
        root.refreshKeyframeInfo()
    }

    function markEnd() {
        if (!root.hasVideo) return
        root.requestedEnd = root.formatTime(player.position, true)
        root.refreshKeyframeInfo()
    }

    function canAddCut() {
        var startMs = root.parseTimeMs(root.requestedStart)
        var endMs = root.parseTimeMs(root.requestedEnd)
        return root.hasVideo && startMs >= 0 && endMs >= 0 && startMs < endMs
    }

    function hasSafeKeyframeInfo() {
        var info = root.keyframeInfo
        return info.valid
            && info.safe_start !== null
            && info.safe_end !== null
            && Number.isFinite(Number(info.safe_start))
            && Number.isFinite(Number(info.safe_end))
            && Number(info.safe_start) < Number(info.safe_end)
    }

    function canAddSafeCut() {
        return root.canAddCut() && root.hasSafeKeyframeInfo()
    }

    function updateCutPreview() {
        var startMs = root.parseTimeMs(root.requestedStart)
        var endMs = root.parseTimeMs(root.requestedEnd)
        var visible = startMs >= 0 && endMs >= 0 && (startMs !== 0 || endMs !== 0)
        if (!visible) {
            root.cutPreview = { "visible": false }
            return
        }

        var valid = startMs < endMs
        var hasSafe = valid && root.hasSafeKeyframeInfo()
        root.cutPreview = {
            "visible": true,
            "valid": valid,
            "has_safe": hasSafe,
            "requested_start": startMs / 1000,
            "requested_end": endMs / 1000,
            "safe_start": hasSafe ? root.keyframeInfo.safe_start : null,
            "safe_end": hasSafe ? root.keyframeInfo.safe_end : null,
            "error": valid ? "" : "End time must be after start time."
        }
    }

    function refreshKeyframeInfo() {
        if (!root.canAddCut()) {
            root.keyframeInfo = root.defaultKeyframeInfo(
                root.hasVideo ? "Set an end point after the start point." : "Open a video to create cuts."
            )
            root.updateCutPreview()
            return
        }

        root.keyframeInfo = videoCutController.keyframeCutInfo(
            appController.selectedVideoPath,
            root.requestedStart,
            root.requestedEnd,
            root.durationMs > 0 ? root.durationMs / 1000 : 0
        )
        root.updateCutPreview()
    }

    function addCurrentCut() {
        if (!root.canAddCut()) return
        root.refreshKeyframeInfo()
        if (!root.hasSafeKeyframeInfo()) return

        var info = root.keyframeInfo
        root.cutAdded({
            "start": root.requestedStart,
            "end": root.requestedEnd,
            "safeStart": root.formatSeconds(info.safe_start),
            "safeEnd": root.formatSeconds(info.safe_end),
            "requestedStartSeconds": info.requested_start,
            "requestedEndSeconds": info.requested_end,
            "safeStartSeconds": info.safe_start,
            "safeEndSeconds": info.safe_end,
            "safeAvailable": true,
            "previousKeyframeStart": root.formatSeconds(info.previous_keyframe_start),
            "nextKeyframeStart": root.formatSeconds(info.next_keyframe_start),
            "previousKeyframeEnd": root.formatSeconds(info.previous_keyframe_end),
            "nextKeyframeEnd": root.formatSeconds(info.next_keyframe_end),
            "extraBefore": Number(info.extra_before || 0).toFixed(1) + "s",
            "extraAfter": Number(info.extra_after || 0).toFixed(1) + "s",
            "reason": "Manual removal",
            "tags": "manual",
            "source": "Manual",
            "score": "--",
            "cutType": "Remove",
            "status": "Pending"
        })

        root.requestedStart = "00:00:00"
        root.requestedEnd = "00:00:00"
        root.keyframeInfo = root.defaultKeyframeInfo("Set start and end points to create a cut.")
        root.updateCutPreview()
    }

    function previewCut() {
        if (!root.canAddCut()) return
        var startMs = root.parseTimeMs(root.requestedStart)
        player.position = startMs
        player.play()
    }

    function subtitleTrackCount() {
        return player.subtitleTracks ? player.subtitleTracks.length : 0
    }

    function syncSubtitleTracks() {
        appController.updatePlayerSubtitleTrackCount(root.subtitleTrackCount())
        root.applyActiveSubtitleTrack()
    }

    function scheduleSubtitleTrackSync() {
        Qt.callLater(root.syncSubtitleTracks)
    }

    function applyActiveSubtitleTrack() {
        var requestedTrack = appController.activePreviewSubtitleTrackIndex
        if (player.activeSubtitleTrack !== requestedTrack)
            player.activeSubtitleTrack = requestedTrack
    }

    MediaPlayer {
        id: player

        source: appController.videoUrl
        videoOutput: videoOutput
        audioOutput: AudioOutput { volume: root.volumeLevel }
        activeSubtitleTrack: -1

        onSubtitleTracksChanged: root.scheduleSubtitleTrackSync()
        onSourceChanged: {
            player.activeSubtitleTrack = -1
            root.scheduleSubtitleTrackSync()
        }
        onMediaStatusChanged: root.scheduleSubtitleTrackSync()
        Component.onCompleted: root.scheduleSubtitleTrackSync()
    }

    Timer {
        interval: 100
        repeat: true
        running: root.hasVideo
        onTriggered: appController.updatePreviewSubtitlePosition(player.position)
    }

    Connections {
        target: appController

        function onActivePreviewSubtitleTrackIndexChanged() {
            root.applyActiveSubtitleTrack()
        }

        function onSelectedVideoPathChanged() {
            root.requestedStart = "00:00:00"
            root.requestedEnd = "00:00:00"
            root.keyframeInfo = root.defaultKeyframeInfo("Set start and end points to create a cut.")
            root.updateCutPreview()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 360
            radius: 12
            color: root.videoColor
            border.color: root.lightMode ? "#DCE4EF" : "#111827"
            clip: true

            VideoOutput {
                id: videoOutput

                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectFit
            }

            Column {
                anchors.centerIn: parent
                spacing: 10
                visible: !root.hasVideo

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "▶"
                    color: root.lightMode ? "#94A3B8" : "#475569"
                    font.pixelSize: 42
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Video preview will appear here"
                    color: root.textColor
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Open a video to get started"
                    color: root.mutedTextColor
                    font.pixelSize: 13
                }
            }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 28
                width: Math.min(parent.width * 0.82, subtitleText.implicitWidth + 28)
                height: subtitleText.implicitHeight + 14
                radius: 10
                color: "#000000"
                opacity: appController.previewSubtitleText.length > 0 ? 0.78 : 0
                visible: opacity > 0
                z: 3

                Text {
                    id: subtitleText

                    anchors.centerIn: parent
                    width: Math.min(root.width * 0.78, implicitWidth)
                    text: appController.previewSubtitleText
                    color: "#FFFFFF"
                    font.pixelSize: 22
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.Wrap
                    style: Text.Outline
                    styleColor: "#000000"
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            radius: 12
            color: root.lightMode ? "#FFFFFF" : "#091321"
            border.color: root.strokeColor

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8

                AppButton {
                    text: root.isPlaying ? "Pause" : "Play"
                    variant: "primary"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    Layout.preferredWidth: 78
                    Layout.preferredHeight: 36
                    onClicked: root.togglePlayback()
                }

                AppButton {
                    text: "-5s"
                    variant: "control"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    Layout.preferredWidth: 54
                    Layout.preferredHeight: 36
                    onClicked: root.seekBy(-5)
                }

                AppButton {
                    text: "+5s"
                    variant: "control"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    Layout.preferredWidth: 54
                    Layout.preferredHeight: 36
                    onClicked: root.seekBy(5)
                }

                Text {
                    text: root.formatTime(root.positionMs) + " / " + root.formatTime(root.durationMs)
                    color: root.textColor
                    font.pixelSize: 12
                    Layout.preferredWidth: 142
                    verticalAlignment: Text.AlignVCenter
                }

                Slider {
                    id: seekSlider

                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    enabled: root.hasVideo && root.durationMs > 0
                    from: 0
                    to: Math.max(1, root.durationMs)
                    value: root.positionMs
                    onMoved: player.position = value

                    background: Rectangle {
                        x: seekSlider.leftPadding
                        y: seekSlider.topPadding + seekSlider.availableHeight / 2 - height / 2
                        width: seekSlider.availableWidth
                        height: 5
                        radius: 3
                        color: root.lightMode ? "#CBD5E1" : "#334155"

                        Rectangle {
                            width: seekSlider.visualPosition * parent.width
                            height: parent.height
                            radius: parent.radius
                            color: root.accentColor
                        }
                    }

                    handle: Rectangle {
                        x: seekSlider.leftPadding + seekSlider.visualPosition * (seekSlider.availableWidth - width)
                        y: seekSlider.topPadding + seekSlider.availableHeight / 2 - height / 2
                        width: 14
                        height: 14
                        radius: 7
                        color: root.lightMode ? "#FFFFFF" : "#E0F2FE"
                        border.color: root.accentColor
                        border.width: 2
                    }
                }

                Text {
                    text: "Vol"
                    color: root.mutedTextColor
                    font.pixelSize: 11
                    verticalAlignment: Text.AlignVCenter
                }

                Slider {
                    id: volumeSlider

                    Layout.preferredWidth: 92
                    Layout.preferredHeight: 32
                    from: 0
                    to: 1
                    value: root.volumeLevel
                    onMoved: root.volumeLevel = value

                    background: Rectangle {
                        x: volumeSlider.leftPadding
                        y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                        width: volumeSlider.availableWidth
                        height: 5
                        radius: 3
                        color: root.lightMode ? "#CBD5E1" : "#334155"

                        Rectangle {
                            width: volumeSlider.visualPosition * parent.width
                            height: parent.height
                            radius: parent.radius
                            color: root.accentColor
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
                    text: "Full"
                    variant: "ghost"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: false
                    Layout.preferredWidth: 58
                    Layout.preferredHeight: 36
                    ToolTip.visible: hovered
                    ToolTip.text: "Fullscreen is not connected in this phase"
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            radius: 12
            color: root.lightMode ? "#FFFFFF" : "#091321"
            border.color: root.strokeColor

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8

                AppButton {
                    text: "Set Start  I"
                    variant: "ghost"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    Layout.preferredWidth: 118
                    Layout.preferredHeight: 36
                    onClicked: root.markStart()
                }

                AppButton {
                    text: "Set End  O"
                    variant: "ghost"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    Layout.preferredWidth: 108
                    Layout.preferredHeight: 36
                    onClicked: root.markEnd()
                }

                AppButton {
                    text: "Add Cut"
                    variant: "primary"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.canAddSafeCut()
                    Layout.preferredWidth: 104
                    Layout.preferredHeight: 36
                    onClicked: root.addCurrentCut()
                }

                AppButton {
                    text: "Preview Cut"
                    variant: "ghost"
                    size: "sm"
                    lightMode: root.lightMode
                    enabled: root.canAddCut()
                    Layout.preferredWidth: 118
                    Layout.preferredHeight: 36
                    onClicked: root.previewCut()
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: "Start " + root.requestedStart + "    End " + root.requestedEnd
                    color: root.mutedTextColor
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    Layout.maximumWidth: 280
                }
            }
        }
    }

    Shortcut {
        sequence: "I"
        onActivated: root.markStart()
    }

    Shortcut {
        sequence: "O"
        onActivated: root.markEnd()
    }
}
