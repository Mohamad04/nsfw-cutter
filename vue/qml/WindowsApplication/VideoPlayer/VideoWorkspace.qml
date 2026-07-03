pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtMultimedia
import "../Shared"
import "time_utils.js" as TimeUtils
import "timeline_utils.js" as TimelineUtils

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

    function safeSelectionText() {
        if (root.hasSafeKeyframeInfo())
            return TimeUtils.formatSeconds(root.keyframeInfo.safe_start) + " -> " + TimeUtils.formatSeconds(root.keyframeInfo.safe_end)
        if (root.keyframeInfo && root.keyframeInfo.error)
            return root.keyframeInfo.error
        return root.canAddCut() ? "Waiting for valid keyframe range" : "Set start and end markers"
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

        root.cutsModel.setProperty(index, "start", TimeUtils.formatSeconds(clampedStart))
        root.cutsModel.setProperty(index, "end", TimeUtils.formatSeconds(clampedEnd))
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
        var range = TimelineUtils.requestedCutRange(cut)
        if (!range.valid) return false

        var startTime = TimeUtils.formatSeconds(range.start)
        var endTime = TimeUtils.formatSeconds(range.end)
        var info = root.safeKeyframeInfoFor(startTime, endTime)
        if (!root.isUsableKeyframeInfo(info)) {
            root.clearCutSafeFields(index)
            return false
        }

        root.cutsModel.setProperty(index, "safeStart", TimeUtils.formatSeconds(info.safe_start))
        root.cutsModel.setProperty(index, "safeEnd", TimeUtils.formatSeconds(info.safe_end))
        root.cutsModel.setProperty(index, "safeStartSeconds", info.safe_start)
        root.cutsModel.setProperty(index, "safeEndSeconds", info.safe_end)
        root.cutsModel.setProperty(index, "safeAvailable", true)
        root.cutsModel.setProperty(index, "previousKeyframeStart", TimeUtils.formatSeconds(info.previous_keyframe_start))
        root.cutsModel.setProperty(index, "nextKeyframeStart", TimeUtils.formatSeconds(info.next_keyframe_start))
        root.cutsModel.setProperty(index, "previousKeyframeEnd", TimeUtils.formatSeconds(info.previous_keyframe_end))
        root.cutsModel.setProperty(index, "nextKeyframeEnd", TimeUtils.formatSeconds(info.next_keyframe_end))
        root.cutsModel.setProperty(index, "extraBefore", Number(info.extra_before || 0).toFixed(1) + "s")
        root.cutsModel.setProperty(index, "extraAfter", Number(info.extra_after || 0).toFixed(1) + "s")
        root.cutsModel.setProperty(index, "status", "Pending")
        return true
    }

    function beginCutTimelineDrag(index, mode, trackX, trackWidth) {
        if (index < 0 || index >= root.cutsModel.count) return
        var range = TimelineUtils.requestedCutRange(root.cutsModel.get(index))
        if (!range.valid) return

        root.draggingCutIndex = index
        root.draggingCutMode = mode
        root.dragAnchorSeconds = TimelineUtils.timelineSecondsAtX(trackX, trackWidth, root.durationMs)
        root.dragOriginalStartSeconds = range.start
        root.dragOriginalEndSeconds = range.end
    }

    function updateCutTimelineDrag(trackX, trackWidth) {
        if (root.draggingCutIndex < 0 || root.draggingCutMode.length === 0) return

        var pointerSeconds = TimelineUtils.timelineSecondsAtX(trackX, trackWidth, root.durationMs)
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
        root.requestedStart = TimeUtils.formatTime(player.position, true)
        root.startPointSet = true
        root.refreshKeyframeInfo()
    }

    function markEnd() {
        if (!root.hasVideo) return
        root.requestedEnd = TimeUtils.formatTime(player.position, true)
        root.endPointSet = true
        root.refreshKeyframeInfo()
    }

    function canAddCutFromTimes(startTime, endTime) {
        if (!root.hasVideo || !Number.isFinite(root.durationMs) || root.durationMs <= 0) return false

        var startMs = TimeUtils.parseTimeMs(startTime)
        var endMs = TimeUtils.parseTimeMs(endTime)
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
        var startMs = TimeUtils.parseTimeMs(root.requestedStart)
        var endMs = TimeUtils.parseTimeMs(root.requestedEnd)
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
            "start": TimeUtils.formatTime(TimeUtils.parseTimeMs(startTime), true),
            "end": TimeUtils.formatTime(TimeUtils.parseTimeMs(endTime), true),
            "safeStart": TimeUtils.formatSeconds(info.safe_start),
            "safeEnd": TimeUtils.formatSeconds(info.safe_end),
            "requestedStartSeconds": info.requested_start,
            "requestedEndSeconds": info.requested_end,
            "safeStartSeconds": info.safe_start,
            "safeEndSeconds": info.safe_end,
            "safeAvailable": true,
            "previousKeyframeStart": TimeUtils.formatSeconds(info.previous_keyframe_start),
            "nextKeyframeStart": TimeUtils.formatSeconds(info.next_keyframe_start),
            "previousKeyframeEnd": TimeUtils.formatSeconds(info.previous_keyframe_end),
            "nextKeyframeEnd": TimeUtils.formatSeconds(info.next_keyframe_end),
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
        var startMs = TimeUtils.parseTimeMs(root.requestedStart)
        player.position = startMs
        player.play()
    }

    function subtitleTrackCount() {
        return player.subtitleTracks ? player.subtitleTracks.length : 0
    }

    function audioTrackCount() {
        return player.audioTracks ? player.audioTracks.length : 0
    }

    function videoTrackCount() {
        return player.videoTracks ? player.videoTracks.length : 0
    }

    function ensureActiveMediaTracks() {
        if (root.audioTrackCount() > 0 && player.activeAudioTrack < 0)
            player.activeAudioTrack = 0

        if (root.videoTrackCount() > 0 && player.activeVideoTrack < 0)
            player.activeVideoTrack = 0
    }

    function syncSubtitleTracks() {
        root.ensureActiveMediaTracks()
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
        videoOutput: videoStage.videoOutput
        audioOutput: AudioOutput {
            volume: Math.max(0, Math.min(1, root.volumeLevel))
            muted: false
        }
        activeSubtitleTrack: -1

        onAudioTracksChanged: root.scheduleSubtitleTrackSync()
        onVideoTracksChanged: root.scheduleSubtitleTrackSync()
        onSubtitleTracksChanged: root.scheduleSubtitleTrackSync()
        onSourceChanged: {
            player.activeAudioTrack = -1
            player.activeVideoTrack = -1
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

        VideoStage {
            id: videoStage

            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 360

            hasVideo: root.hasVideo
            lightMode: root.lightMode
            videoColor: root.videoColor
            strokeColor: root.strokeColor
            textColor: root.textColor
            mutedTextColor: root.mutedTextColor
            accentColor: root.accentColor
            previewSubtitleText: appController.previewSubtitleText
        }

        PlaybackControlsBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 56

            cutsModel: root.cutsModel

            lightMode: root.lightMode
            strokeColor: root.strokeColor
            textColor: root.textColor
            mutedTextColor: root.mutedTextColor
            accentColor: root.accentColor

            hasVideo: root.hasVideo
            isPlaying: root.isPlaying
            positionMs: root.positionMs
            durationMs: root.durationMs
            volumeLevel: root.volumeLevel

            requestedStart: root.requestedStart
            requestedEnd: root.requestedEnd
            startPointSet: root.startPointSet
            endPointSet: root.endPointSet
            draggingCutIndex: root.draggingCutIndex

            onTogglePlaybackRequested: root.togglePlayback()

            onSeekByRequested: function(seconds) {
                root.seekBy(seconds)
            }

            onSeekRequested: function(positionMs) {
                player.position = positionMs
            }

            onVolumeLevelChangeRequested: function(value) {
                root.volumeLevel = value
            }

            onBeginCutTimelineDragRequested: function(index, mode, trackX, trackWidth) {
                root.beginCutTimelineDrag(index, mode, trackX, trackWidth)
            }

            onUpdateCutTimelineDragRequested: function(trackX, trackWidth) {
                root.updateCutTimelineDrag(trackX, trackWidth)
            }

            onFinishCutTimelineDragRequested: {
                root.finishCutTimelineDrag()
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
