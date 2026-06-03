import QtQuick
import QtQuick.Layouts
import QtMultimedia

Panel {
    id: root

    property bool compactMode: false
    property bool lightMode: false
    property bool shortMode: false
    property color panelTone: "#0B1324"
    property color videoTone: "#1E293B"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
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
    strokeColor: root.lightMode ? "#CBD5E1" : "#21324D"

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
        if (milliseconds > 0) {
            text += "." + padMillis(milliseconds)
        }
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

    MediaPlayer {
        id: player
        source: appController.videoUrl
        videoOutput: videoPlayer.videoOutput
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

    Connections {
        target: appController

        function onActivePreviewSubtitleTrackIndexChanged() {
            root.applyActiveSubtitleTrack()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.panelPadding
        spacing: root.compactMode ? 10 : 12

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            spacing: 8

            Text {
                text: "VIDEO"
                color: root.accent
                font.pixelSize: 15
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
            Layout.minimumHeight: root.shortMode ? 210 : (root.compactMode ? 320 : 360)
            compactMode: root.compactMode
            lightMode: root.lightMode
            playing: player.playbackState === MediaPlayer.PlayingState
            positionMs: player.position
            durationMs: player.duration
            volume: root.volumeLevel
            cutsModel: root.cutsModel
            selectedCutIndex: root.selectedCutIndex
            cutPreview: root.cutPreview
            videoTone: root.videoTone
            textMain: root.textMain
            textMuted: root.textMuted
            accent: root.accent
            onPlayRequested: player.play()
            onSeekRequested: function(positionMs) { player.position = positionMs }
            onSkipRequested: function(seconds) { root.seekBy(seconds) }
            onPlaybackToggled: root.togglePlayback()
            onStartRequested: root.startRequested(root.formatTime(player.position))
            onEndRequested: root.endRequested(root.formatTime(player.position))
            onAddCutRequested: root.addCutRequested()
            onVolumeRequested: function(value) { root.volumeLevel = value }
            onMarkerSelected: function(index, positionMs) {
                player.position = positionMs
                root.cutMarkerSelected(index)
            }
            onCutSelected: function(index) {
                root.cutMarkerSelected(index)
            }
            onCutRangeChanged: function(index, startMs, endMs) {
                root.cutRangeChanged(index, startMs, endMs)
            }
        }
    }
}
