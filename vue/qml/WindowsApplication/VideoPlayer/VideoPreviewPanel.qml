import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "../Shared"

Panel {
    id: root

    property bool compactMode: false
    property bool lightMode: false
    property bool shortMode: false
    property color panelTone: "#0C1625"
    property color videoTone: "#1E293B"
    property color textMain: "#F3F6FB"
    property color textMuted: "#92A2B8"
    property color accent: "#2F7BFF"
    property int cutCount: 0
    property var cutsModel
    property int selectedCutIndex: -1
    property var cutPreview: ({ "visible": false })
    property real volumeLevel: 0.85
    readonly property real durationMs: player.duration
    readonly property real positionMs: player.position

    signal startRequested(string timeText)
    signal endRequested(string timeText)
    signal addCutRequested()
    signal cutMarkerSelected(int index)
    signal cutRangeChanged(int index, real startMs, real endMs)

    panelColor: root.panelTone
    strokeColor: root.lightMode ? "#DCE4EF" : "#223247"

    AppTheme { id: theme }

    function formatTime(ms) {
        var totalMilliseconds = Math.max(0, Math.round(ms))
        var totalSeconds = Math.floor(totalMilliseconds / 1000)
        var milliseconds = totalMilliseconds % 1000
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var seconds = totalSeconds % 60

        function pad(value) { return value < 10 ? "0" + value : "" + value }
        function padMillis(value) {
            if (value < 10) return "00" + value
            if (value < 100) return "0" + value
            return "" + value
        }
        var text = pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
        if (milliseconds > 0) text += "." + padMillis(milliseconds)
        return text
    }

    function seekBy(seconds) {
        var newPosition = player.position + seconds * 1000
        if (newPosition < 0) newPosition = 0
        if (player.duration > 0 && newPosition > player.duration) newPosition = player.duration
        player.position = newPosition
    }

    function togglePlayback() {
        if (player.playbackState === MediaPlayer.PlayingState) player.pause()
        else player.play()
    }

    function stopPlayback() {
        player.stop()
    }

    function seekToTime(timeText) {
        player.position = parseTimeMs(timeText)
    }

    function playFromTime(timeText) {
        player.position = parseTimeMs(timeText)
        player.play()
    }

    function previewSelectedCut() {
        if (!root.cutsModel || root.selectedCutIndex < 0 || root.selectedCutIndex >= root.cutsModel.count) return
        var cut = root.cutsModel.get(root.selectedCutIndex)
        root.playFromTime(cut.safeStart || cut.start || "00:00:00")
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
        console.info(
            "[Subtitles] Preview player tracks=" + root.subtitleTrackCount()
            + ", requested=" + requestedTrack
            + ", active=" + player.activeSubtitleTrack
        )
    }

    function parseTimeMs(timeText) {
        var parts = String(timeText).trim().split(":")
        if (parts.length !== 3) return 0
        return (Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])) * 1000
    }

    function playbackValueText(value) {
        return value === undefined || value === null ? "" : String(value)
    }

    function logPlayerState(eventName) {
        var sourceText = root.playbackValueText(player.source)
        var mediaStatusText = root.playbackValueText(player.mediaStatus)
        var errorText = root.playbackValueText(player.error)
        var errorStringText = root.playbackValueText(player.errorString)
        var message = "[Playback][VideoPreviewPanel] " + eventName
            + " source=" + sourceText
            + " mediaStatus=" + mediaStatusText
            + " error=" + errorText
            + " errorString=" + errorStringText

        appController.logPlaybackState(
            "VideoPreviewPanel",
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
        videoOutput: videoPlayer.videoOutput
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
        running: appController.videoUrl.length > 0
        onTriggered: appController.updatePreviewSubtitlePosition(player.position)
    }

    Connections {
        target: appController

        function onActivePreviewSubtitleTrackIndexChanged() {
            root.applyActiveSubtitleTrack()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.compactMode ? 10 : theme.panelPadding
        spacing: root.compactMode ? 8 : 10

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 24
            spacing: 8

            Text {
                text: "VIDEO PREVIEW"
                color: root.accent
                font.pixelSize: 14
                font.bold: true
                font.letterSpacing: 0.8
            }

            Text {
                text: player.duration > 0 ? "Preview ready" : "Waiting for media"
                color: root.textMuted
                font.pixelSize: 12
            }

            Item { Layout.fillWidth: true }

            Text {
                text: "Cuts: " + root.cutCount
                color: root.textMuted
                font.pixelSize: 12
            }
        }

        VideoPlayer {
            id: videoPlayer
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: root.shortMode ? 250 : (root.compactMode ? 330 : 430)
            compactMode: root.compactMode
            lightMode: root.lightMode
            playing: player.playbackState === MediaPlayer.PlayingState
            positionMs: player.position
            durationMs: player.duration
            volume: root.volumeLevel
            cutsModel: root.cutsModel
            selectedCutIndex: root.selectedCutIndex
            cutPreview: root.cutPreview
            previewSubtitleText: appController.previewSubtitleText
            videoTone: root.videoTone
            textMain: root.textMain
            textMuted: root.textMuted
            accent: root.accent
            onPlayRequested: player.play()
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.compactMode ? 128 : 142
            radius: 12
            color: root.lightMode ? "#FFFFFF" : "#091321"
            border.color: root.lightMode ? "#DCE4EF" : "#223247"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: root.compactMode ? 8 : 10
                spacing: 8

                VideoTimeline {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 28
                    positionMs: player.position
                    durationMs: player.duration
                    cutsModel: root.cutsModel
                    selectedCutIndex: root.selectedCutIndex
                    cutPreview: root.cutPreview
                    lightMode: root.lightMode
                    textMain: root.textMain
                    accent: root.lightMode ? theme.lightPlayhead : theme.darkPlayhead
                    onSeekRequested: function(positionMs) { player.position = positionMs }
                    onMarkerSelected: function(index, positionMs) {
                        player.position = positionMs
                        root.cutMarkerSelected(index)
                    }
                    onCutSelected: function(index) { root.cutMarkerSelected(index) }
                    onCutRangeChanged: function(index, startMs, endMs) {
                        root.cutRangeChanged(index, startMs, endMs)
                    }
                }

                VideoControls {
                    id: controls
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.compactMode ? 78 : 86
                    compactMode: root.compactMode
                    lightMode: root.lightMode
                    playing: player.playbackState === MediaPlayer.PlayingState
                    volume: root.volumeLevel
                    startSet: root.cutPreview && root.cutPreview.visible === true
                    endSet: root.cutPreview && root.cutPreview.visible === true
                    addEnabled: root.cutPreview
                        && root.cutPreview.visible === true
                        && root.cutPreview.valid === true
                        && root.cutPreview.has_safe === true
                    previewEnabled: root.selectedCutIndex >= 0 && root.cutsModel && root.selectedCutIndex < root.cutsModel.count
                    subtitlesAvailable: appController.subtitleCandidates.length > 0
                    onSeekRequested: function(seconds) { root.seekBy(seconds) }
                    onPlaybackToggled: root.togglePlayback()
                    onStartRequested: root.startRequested(root.formatTime(player.position))
                    onEndRequested: root.endRequested(root.formatTime(player.position))
                    onAddCutRequested: root.addCutRequested()
                    onPreviewRequested: root.previewSelectedCut()
                    onSubtitlesRequested: if (appController.subtitleCandidates.length > 0) subtitleSelector.showAt(controls)
                    onVolumeRequested: function(value) { root.volumeLevel = value }
                }
            }
        }
    }

    SubtitleSelectorPopup {
        id: subtitleSelector

        lightMode: root.lightMode
        textColor: root.textMain
        mutedTextColor: root.textMuted
        options: appController.analysisSubtitleOptions
        detectedCount: appController.subtitleCandidates.length
        onCandidateSelected: function(candidateId) {
            if (appController.selectAnalysisSubtitle(candidateId))
                subtitleSelector.closeAfterAction()
        }
    }

    Shortcut {
        sequence: "I"
        onActivated: root.startRequested(root.formatTime(player.position))
    }

    Shortcut {
        sequence: "O"
        onActivated: root.endRequested(root.formatTime(player.position))
    }
}

