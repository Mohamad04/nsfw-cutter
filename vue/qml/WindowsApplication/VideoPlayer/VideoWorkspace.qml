pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "../Shared"

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
    property bool startPointSet: false
    property bool endPointSet: false
    property string cutTimingMode: "safe"
    property var keyframeInfo: defaultKeyframeInfo("Set start and end points to create a cut.")
    property var cutPreview: ({ "visible": false })
    property int draggingCutIndex: -1
    property string draggingCutMode: ""
    property real dragAnchorSeconds: 0
    property real dragOriginalStartSeconds: 0
    property real dragOriginalEndSeconds: 0
    readonly property real minimumCutDurationSeconds: 0.1
    readonly property real durationMs: player.duration
    readonly property real positionMs: player.position
    readonly property bool hasVideo: appController.videoUrl.length > 0
    readonly property bool isPlaying: player.playbackState === MediaPlayer.PlayingState

    signal cutAdded(var cut)
    signal timingModeSelected(string mode)

    radius: 14
    color: root.lightMode ? root.panelColor : "#081321"
    border.color: root.lightMode ? root.strokeColor : "#223754"
    clip: true

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 13
        color: "transparent"
        border.color: root.lightMode ? "#FFFFFF" : "#163456"
        opacity: root.lightMode ? 0.36 : 0.42
    }

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

    function numericCutSeconds(cut, secondsKey, timeKey) {
        if (!cut) return NaN

        var seconds = cut[secondsKey]
        if (seconds !== undefined && seconds !== null && seconds !== "") {
            var numeric = Number(seconds)
            if (Number.isFinite(numeric)) return numeric
        }

        var timeMs = root.parseTimeMs(cut[timeKey])
        return timeMs >= 0 ? timeMs / 1000 : NaN
    }

    function cutRange(cut) {
        if (!cut) return { "valid": false, "start": 0, "end": 0 }

        var safeStart = root.numericCutSeconds(cut, "safeStartSeconds", "safeStart")
        var safeEnd = root.numericCutSeconds(cut, "safeEndSeconds", "safeEnd")
        if (Number.isFinite(safeStart) && Number.isFinite(safeEnd) && safeEnd > safeStart)
            return { "valid": true, "start": safeStart, "end": safeEnd }

        var requestedStart = root.numericCutSeconds(cut, "requestedStartSeconds", "start")
        var requestedEnd = root.numericCutSeconds(cut, "requestedEndSeconds", "end")
        if (Number.isFinite(requestedStart) && Number.isFinite(requestedEnd) && requestedEnd > requestedStart)
            return { "valid": true, "start": requestedStart, "end": requestedEnd }

        return { "valid": false, "start": 0, "end": 0 }
    }

    function requestedCutRange(cut) {
        if (!cut) return { "valid": false, "start": 0, "end": 0 }

        var requestedStart = root.numericCutSeconds(cut, "requestedStartSeconds", "start")
        var requestedEnd = root.numericCutSeconds(cut, "requestedEndSeconds", "end")
        if (Number.isFinite(requestedStart) && Number.isFinite(requestedEnd) && requestedEnd > requestedStart)
            return { "valid": true, "start": requestedStart, "end": requestedEnd }

        return root.cutRange(cut)
    }

    function clampedTimelineSeconds(value) {
        if (!Number.isFinite(value) || !Number.isFinite(root.durationMs) || root.durationMs <= 0) return 0
        var durationSeconds = root.durationMs / 1000
        return Math.max(0, Math.min(value, durationSeconds))
    }

    function timelineX(seconds, trackWidth) {
        if (!Number.isFinite(root.durationMs) || root.durationMs <= 0 || trackWidth <= 0) return 0
        return root.clampedTimelineSeconds(seconds) / (root.durationMs / 1000) * trackWidth
    }

    function timelineSecondsAtX(trackX, trackWidth) {
        if (!Number.isFinite(root.durationMs) || root.durationMs <= 0 || trackWidth <= 0) return 0
        var clampedX = Math.max(0, Math.min(trackX, trackWidth))
        return clampedX / trackWidth * (root.durationMs / 1000)
    }

    function markerSeconds(timeText, isSet) {
        if (!isSet) return NaN
        var timeMs = root.parseTimeMs(timeText)
        return timeMs >= 0 ? timeMs / 1000 : NaN
    }

    function formatSignedDelta(seconds) {
        if (!Number.isFinite(seconds)) return "--"

        var roundedSeconds = Math.round(seconds)
        var sign = roundedSeconds >= 0 ? "+" : "-"
        var absoluteSeconds = Math.abs(roundedSeconds)
        var hours = Math.floor(absoluteSeconds / 3600)
        var minutes = Math.floor((absoluteSeconds % 3600) / 60)
        var wholeSeconds = absoluteSeconds % 60
        if (hours > 0)
            return sign + root.pad(hours) + ":" + root.pad(minutes) + ":" + root.pad(wholeSeconds)
        return sign + root.pad(minutes) + ":" + root.pad(wholeSeconds)
    }

    function requestedSelectionText() {
        if (!root.startPointSet && !root.endPointSet) return "Set start and end markers"
        if (root.startPointSet && !root.endPointSet) return root.requestedStart + " -> Set end"
        if (!root.startPointSet && root.endPointSet) return "Set start -> " + root.requestedEnd
        return root.requestedStart + " -> " + root.requestedEnd
    }

    function safeSelectionText() {
        if (root.hasSafeKeyframeInfo())
            return root.formatSeconds(root.keyframeInfo.safe_start) + " -> " + root.formatSeconds(root.keyframeInfo.safe_end)
        if (root.keyframeInfo && root.keyframeInfo.error)
            return root.keyframeInfo.error
        return root.canAddCut() ? "Waiting for valid keyframe range" : "Set start and end markers"
    }

    function deltaSelectionText() {
        if (!root.hasSafeKeyframeInfo()) return "Start -- | End -- | Duration --"

        var requestedStartSeconds = root.parseTimeMs(root.requestedStart) / 1000
        var requestedEndSeconds = root.parseTimeMs(root.requestedEnd) / 1000
        var safeStartSeconds = Number(root.keyframeInfo.safe_start)
        var safeEndSeconds = Number(root.keyframeInfo.safe_end)
        var requestedDuration = requestedEndSeconds - requestedStartSeconds
        var safeDuration = safeEndSeconds - safeStartSeconds

        return "Start " + root.formatSignedDelta(safeStartSeconds - requestedStartSeconds)
            + " | End " + root.formatSignedDelta(safeEndSeconds - requestedEndSeconds)
            + " | Duration " + root.formatSignedDelta(safeDuration - requestedDuration)
    }

    function setCutTimingFields(index, startSeconds, endSeconds) {
        if (index < 0 || index >= root.cutsModel.count) return false
        var durationSeconds = Number.isFinite(root.durationMs) && root.durationMs > 0 ? root.durationMs / 1000 : 0
        if (durationSeconds <= 0) return false

        var clampedStart = Math.max(0, Math.min(startSeconds, durationSeconds))
        var clampedEnd = Math.max(0, Math.min(endSeconds, durationSeconds))
        if (clampedEnd <= clampedStart)
            clampedEnd = Math.min(durationSeconds, clampedStart + root.minimumCutDurationSeconds)
        if (clampedEnd <= clampedStart)
            clampedStart = Math.max(0, clampedEnd - root.minimumCutDurationSeconds)
        if (clampedEnd <= clampedStart) return false

        root.cutsModel.setProperty(index, "start", root.formatSeconds(clampedStart))
        root.cutsModel.setProperty(index, "end", root.formatSeconds(clampedEnd))
        root.cutsModel.setProperty(index, "requestedStartSeconds", clampedStart)
        root.cutsModel.setProperty(index, "requestedEndSeconds", clampedEnd)
        return true
    }

    function clearCutSafeFields(index) {
        root.cutsModel.setProperty(index, "safeStart", "")
        root.cutsModel.setProperty(index, "safeEnd", "")
        root.cutsModel.setProperty(index, "safeStartSeconds", "")
        root.cutsModel.setProperty(index, "safeEndSeconds", "")
        root.cutsModel.setProperty(index, "safeAvailable", false)
        root.cutsModel.setProperty(index, "previousKeyframeStart", "")
        root.cutsModel.setProperty(index, "nextKeyframeStart", "")
        root.cutsModel.setProperty(index, "previousKeyframeEnd", "")
        root.cutsModel.setProperty(index, "nextKeyframeEnd", "")
        root.cutsModel.setProperty(index, "extraBefore", "0.0s")
        root.cutsModel.setProperty(index, "extraAfter", "0.0s")
        root.cutsModel.setProperty(index, "status", "Safe unavailable")
    }

    function recomputeCutSafeTiming(index) {
        if (index < 0 || index >= root.cutsModel.count) return false

        var cut = root.cutsModel.get(index)
        var range = root.requestedCutRange(cut)
        if (!range.valid) return false

        var startTime = root.formatSeconds(range.start)
        var endTime = root.formatSeconds(range.end)
        var info = root.safeKeyframeInfoFor(startTime, endTime)
        if (!root.isUsableKeyframeInfo(info)) {
            root.clearCutSafeFields(index)
            return false
        }

        root.cutsModel.setProperty(index, "safeStart", root.formatSeconds(info.safe_start))
        root.cutsModel.setProperty(index, "safeEnd", root.formatSeconds(info.safe_end))
        root.cutsModel.setProperty(index, "safeStartSeconds", info.safe_start)
        root.cutsModel.setProperty(index, "safeEndSeconds", info.safe_end)
        root.cutsModel.setProperty(index, "safeAvailable", true)
        root.cutsModel.setProperty(index, "previousKeyframeStart", root.formatSeconds(info.previous_keyframe_start))
        root.cutsModel.setProperty(index, "nextKeyframeStart", root.formatSeconds(info.next_keyframe_start))
        root.cutsModel.setProperty(index, "previousKeyframeEnd", root.formatSeconds(info.previous_keyframe_end))
        root.cutsModel.setProperty(index, "nextKeyframeEnd", root.formatSeconds(info.next_keyframe_end))
        root.cutsModel.setProperty(index, "extraBefore", Number(info.extra_before || 0).toFixed(1) + "s")
        root.cutsModel.setProperty(index, "extraAfter", Number(info.extra_after || 0).toFixed(1) + "s")
        root.cutsModel.setProperty(index, "status", "Pending")
        return true
    }

    function beginCutTimelineDrag(index, mode, trackX, trackWidth) {
        if (index < 0 || index >= root.cutsModel.count) return
        var range = root.requestedCutRange(root.cutsModel.get(index))
        if (!range.valid) return

        root.draggingCutIndex = index
        root.draggingCutMode = mode
        root.dragAnchorSeconds = root.timelineSecondsAtX(trackX, trackWidth)
        root.dragOriginalStartSeconds = range.start
        root.dragOriginalEndSeconds = range.end
    }

    function updateCutTimelineDrag(trackX, trackWidth) {
        if (root.draggingCutIndex < 0 || root.draggingCutMode.length === 0) return

        var pointerSeconds = root.timelineSecondsAtX(trackX, trackWidth)
        var durationSeconds = root.durationMs / 1000
        var startSeconds = root.dragOriginalStartSeconds
        var endSeconds = root.dragOriginalEndSeconds
        var originalDuration = Math.max(root.minimumCutDurationSeconds, root.dragOriginalEndSeconds - root.dragOriginalStartSeconds)

        if (root.draggingCutMode === "move") {
            var deltaSeconds = pointerSeconds - root.dragAnchorSeconds
            startSeconds = Math.max(0, Math.min(durationSeconds - originalDuration, root.dragOriginalStartSeconds + deltaSeconds))
            endSeconds = startSeconds + originalDuration
        } else if (root.draggingCutMode === "start") {
            startSeconds = Math.max(0, Math.min(pointerSeconds, root.dragOriginalEndSeconds - root.minimumCutDurationSeconds))
        } else if (root.draggingCutMode === "end") {
            endSeconds = Math.min(durationSeconds, Math.max(pointerSeconds, root.dragOriginalStartSeconds + root.minimumCutDurationSeconds))
        }

        root.setCutTimingFields(root.draggingCutIndex, startSeconds, endSeconds)
    }

    function finishCutTimelineDrag() {
        if (root.draggingCutIndex >= 0)
            root.recomputeCutSafeTiming(root.draggingCutIndex)

        root.draggingCutIndex = -1
        root.draggingCutMode = ""
        root.dragAnchorSeconds = 0
        root.dragOriginalStartSeconds = 0
        root.dragOriginalEndSeconds = 0
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
        root.startPointSet = true
        root.refreshKeyframeInfo()
    }

    function markEnd() {
        if (!root.hasVideo) return
        root.requestedEnd = root.formatTime(player.position, true)
        root.endPointSet = true
        root.refreshKeyframeInfo()
    }

    function canAddCutFromTimes(startTime, endTime) {
        if (!root.hasVideo || !Number.isFinite(root.durationMs) || root.durationMs <= 0) return false

        var startMs = root.parseTimeMs(startTime)
        var endMs = root.parseTimeMs(endTime)
        return startMs >= 0
            && endMs >= 0
            && startMs < endMs
            && startMs <= root.durationMs
            && endMs <= root.durationMs
    }

    function canAddCut() {
        return root.canAddCutFromTimes(root.requestedStart, root.requestedEnd)
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

    function safeKeyframeInfoFor(startTime, endTime) {
        if (!root.canAddCutFromTimes(startTime, endTime))
            return root.defaultKeyframeInfo("Invalid cut range.")

        return videoCutController.keyframeCutInfo(
            appController.selectedVideoPath,
            startTime,
            endTime,
            root.durationMs > 0 ? root.durationMs / 1000 : 0
        )
    }

    function isUsableKeyframeInfo(info) {
        return info.valid
            && info.safe_start !== null
            && info.safe_end !== null
            && Number.isFinite(Number(info.safe_start))
            && Number.isFinite(Number(info.safe_end))
            && Number(info.safe_start) < Number(info.safe_end)
    }

    function addCutFromTimes(startTime, endTime, source, reason, tags, score, updateSelectionInfo) {
        if (!root.canAddCutFromTimes(startTime, endTime)) return false

        var info = root.safeKeyframeInfoFor(startTime, endTime)
        if (updateSelectionInfo === true) {
            root.keyframeInfo = info
            root.updateCutPreview()
        }
        if (!root.isUsableKeyframeInfo(info)) return false

        root.cutAdded({
            "start": root.formatTime(root.parseTimeMs(startTime), true),
            "end": root.formatTime(root.parseTimeMs(endTime), true),
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
            "reason": reason || "Manual removal",
            "tags": tags || "manual",
            "source": source || "Manual",
            "score": score || "--",
            "cutType": "Remove",
            "status": "Pending"
        })

        return true
    }

    function addCutFromSuggestion(startTime, endTime, confidence, reason) {
        return root.addCutFromTimes(
            startTime,
            endTime,
            "AI",
            reason || "AI suggestion",
            "ai,suggestion",
            confidence || "--",
            false
        )
    }

    function addCurrentCut() {
        if (!root.addCutFromTimes(root.requestedStart, root.requestedEnd, "Manual", "Manual removal", "manual", "--", true))
            return

        root.requestedStart = "00:00:00"
        root.requestedEnd = "00:00:00"
        root.startPointSet = false
        root.endPointSet = false
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

    function playbackValueText(value) {
        return value === undefined || value === null ? "" : String(value)
    }

    function logPlayerState(eventName) {
        var sourceText = root.playbackValueText(player.source)
        var mediaStatusText = root.playbackValueText(player.mediaStatus)
        var errorText = root.playbackValueText(player.error)
        var errorStringText = root.playbackValueText(player.errorString)
        var message = "[Playback][VideoWorkspace] " + eventName
            + " source=" + sourceText
            + " mediaStatus=" + mediaStatusText
            + " error=" + errorText
            + " errorString=" + errorStringText

        appController.logPlaybackState(
            "VideoWorkspace",
            eventName,
            sourceText,
            mediaStatusText,
            errorText,
            errorStringText
        )

        if (errorStringText.length > 0) console.warn(message)
        else console.info(message)
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
            root.logPlayerState("sourceChanged")
            root.scheduleSubtitleTrackSync()
        }
        onMediaStatusChanged: {
            root.logPlayerState("mediaStatusChanged")
            root.scheduleSubtitleTrackSync()
        }
        onErrorOccurred: function(error, errorString) {
            root.logPlayerState("errorOccurred")
        }
        Component.onCompleted: {
            root.logPlayerState("completed")
            root.scheduleSubtitleTrackSync()
        }
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
            root.startPointSet = false
            root.endPointSet = false
            root.keyframeInfo = root.defaultKeyframeInfo("Set start and end points to create a cut.")
            root.updateCutPreview()
        }

        function onKeyframeStateChanged() {
            if (root.startPointSet || root.endPointSet)
                root.refreshKeyframeInfo()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        Rectangle {
            id: videoStage
            objectName: "videoStage"

            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 360
            radius: 16
            color: root.videoColor
            border.color: root.hasVideo
                ? (root.lightMode ? "#93C5FD" : "#2F7BFF")
                : (root.lightMode ? "#DCE4EF" : "#142033")
            border.width: 1
            clip: true

            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 15
                color: "transparent"
                border.color: root.hasVideo ? root.accentColor : "#0E1A2C"
                border.width: 1
                opacity: root.hasVideo ? 0.22 : 0.24
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: root.accentColor
                opacity: root.hasVideo ? 0.28 : 0.08
            }

            VideoOutput {
                id: videoOutput

                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectCrop
            }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                visible: !root.hasVideo

                VectorIcon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 44
                    height: 44
                    name: "play"
                    iconColor: root.lightMode ? "#94A3B8" : "#36506E"
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
                    onClicked: root.togglePlayback()
                }

                BackwardFiveSeekButton {
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    Layout.preferredWidth: 84
                    Layout.preferredHeight: 36
                    onClicked: root.seekBy(-5)
                }

                ForwardFiveSeekButton {
                    lightMode: root.lightMode
                    enabled: root.hasVideo
                    Layout.preferredWidth: 84
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

                Item {
                    id: seekArea
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32

                    readonly property real selectionStartSeconds: root.markerSeconds(root.requestedStart, root.startPointSet)
                    readonly property real selectionEndSeconds: root.markerSeconds(root.requestedEnd, root.endPointSet)
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
                        onMoved: player.position = value

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
                                    readonly property var requestedRange: root.requestedCutRange(root.cutsModel.get(index))
                                    readonly property real requestedStartSeconds: root.clampedTimelineSeconds(requestedRange.start)
                                    readonly property real requestedEndSeconds: root.clampedTimelineSeconds(requestedRange.end)
                                    readonly property real requestedX: root.timelineX(requestedStartSeconds, width)
                                    readonly property real requestedWidth: root.timelineX(requestedEndSeconds, width) - requestedX
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
                                            root.beginCutTimelineDrag(
                                                cutTimelineItem.index,
                                                "move",
                                                trackX(mouse.x, mouse.y),
                                                timelineTrack.width
                                            )
                                        }
                                        onPositionChanged: function(mouse) {
                                            if (pressed)
                                                root.updateCutTimelineDrag(trackX(mouse.x, mouse.y), timelineTrack.width)
                                        }
                                        onReleased: {
                                            cursorShape = Qt.OpenHandCursor
                                            root.finishCutTimelineDrag()
                                        }
                                        onCanceled: {
                                            cursorShape = Qt.OpenHandCursor
                                            root.finishCutTimelineDrag()
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
                                                root.beginCutTimelineDrag(
                                                    cutTimelineItem.index,
                                                    "start",
                                                    trackX(mouse.x, mouse.y),
                                                    timelineTrack.width
                                                )
                                            }
                                            onPositionChanged: function(mouse) {
                                                if (pressed)
                                                    root.updateCutTimelineDrag(trackX(mouse.x, mouse.y), timelineTrack.width)
                                            }
                                            onReleased: root.finishCutTimelineDrag()
                                            onCanceled: root.finishCutTimelineDrag()
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
                                                root.beginCutTimelineDrag(
                                                    cutTimelineItem.index,
                                                    "end",
                                                    trackX(mouse.x, mouse.y),
                                                    timelineTrack.width
                                                )
                                            }
                                            onPositionChanged: function(mouse) {
                                                if (pressed)
                                                    root.updateCutTimelineDrag(trackX(mouse.x, mouse.y), timelineTrack.width)
                                            }
                                            onReleased: root.finishCutTimelineDrag()
                                            onCanceled: root.finishCutTimelineDrag()
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                id: pendingSelectionRange

                                readonly property real startSeconds: root.clampedTimelineSeconds(seekArea.selectionStartSeconds)
                                readonly property real endSeconds: root.clampedTimelineSeconds(seekArea.selectionEndSeconds)
                                readonly property real calculatedX: root.timelineX(startSeconds, parent.width)
                                readonly property real calculatedWidth: root.timelineX(endSeconds, parent.width) - calculatedX

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
                                x: Math.max(0, Math.min(parent.width - width, root.timelineX(seekArea.selectionStartSeconds, parent.width) - width / 2))
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
                                x: Math.max(0, Math.min(parent.width - width, root.timelineX(seekArea.selectionEndSeconds, parent.width) - width / 2))
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
                                readonly property var requestedRange: root.requestedCutRange(root.cutsModel.get(index))
                                readonly property real requestedStartSeconds: root.clampedTimelineSeconds(requestedRange.start)
                                readonly property real requestedEndSeconds: root.clampedTimelineSeconds(requestedRange.end)
                                readonly property real requestedX: root.timelineX(requestedStartSeconds, width)
                                readonly property real requestedWidth: root.timelineX(requestedEndSeconds, width) - requestedX
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
                                        root.beginCutTimelineDrag(
                                            cutDragDelegate.index,
                                            "move",
                                            cutDragDelegate.trackXFrom(moveCutDragArea, mouse.x, mouse.y),
                                            cutDragLayer.width
                                        )
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (pressed)
                                            root.updateCutTimelineDrag(
                                                cutDragDelegate.trackXFrom(moveCutDragArea, mouse.x, mouse.y),
                                                cutDragLayer.width
                                            )
                                    }
                                    onReleased: function(mouse) {
                                        mouse.accepted = true
                                        root.finishCutTimelineDrag()
                                    }
                                    onCanceled: root.finishCutTimelineDrag()
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
                                        root.beginCutTimelineDrag(
                                            cutDragDelegate.index,
                                            "start",
                                            cutDragDelegate.trackXFrom(startCutDragArea, mouse.x, mouse.y),
                                            cutDragLayer.width
                                        )
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (pressed)
                                            root.updateCutTimelineDrag(
                                                cutDragDelegate.trackXFrom(startCutDragArea, mouse.x, mouse.y),
                                                cutDragLayer.width
                                            )
                                    }
                                    onReleased: function(mouse) {
                                        mouse.accepted = true
                                        root.finishCutTimelineDrag()
                                    }
                                    onCanceled: root.finishCutTimelineDrag()
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
                                        root.beginCutTimelineDrag(
                                            cutDragDelegate.index,
                                            "end",
                                            cutDragDelegate.trackXFrom(endCutDragArea, mouse.x, mouse.y),
                                            cutDragLayer.width
                                        )
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (pressed)
                                            root.updateCutTimelineDrag(
                                                cutDragDelegate.trackXFrom(endCutDragArea, mouse.x, mouse.y),
                                                cutDragLayer.width
                                            )
                                    }
                                    onReleased: function(mouse) {
                                        mouse.accepted = true
                                        root.finishCutTimelineDrag()
                                    }
                                    onCanceled: root.finishCutTimelineDrag()
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
                    onMoved: root.volumeLevel = value

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
                    ToolTip.text: "Fullscreen is not connected in this phase"
                }
            }
        }

        CutActionBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 76

            lightMode: root.lightMode
            hasVideo: root.hasVideo
            startPointSet: root.startPointSet
            endPointSet: root.endPointSet
            canAddCut: root.canAddCut()
            cutTimingMode: root.cutTimingMode
            safeSelectionText: root.safeSelectionText()
            hasSafeKeyframeInfo: root.hasSafeKeyframeInfo()
            mutedTextColor: root.mutedTextColor
            strokeColor: root.strokeColor

            onMarkStartRequested: root.markStart()
            onMarkEndRequested: root.markEnd()
            onAddCutRequested: root.addCurrentCut()
            onPreviewCutRequested: root.previewCut()
            onTimingModeSelected: function(mode) {
                root.timingModeSelected(mode)
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

