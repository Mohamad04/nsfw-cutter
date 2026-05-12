pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

import "components"

ApplicationWindow {
    id: root
    visible: true
    width: 1360
    height: 820
    minimumWidth: 960
    minimumHeight: 620
    title: "NSFW Cutter"
    color: "#0F172A"

    property bool compactMode: root.width < 1180 || root.height < 720
    property bool narrowMode: root.width < 1060
    property bool shortMode: root.height < 700

    property color bg: "#0F172A"
    property color panel: "#0B1324"
    property color videoBg: "#1E293B"
    property color stroke: "#243244"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property color primary: "#2563EB"
    property color success: "#15803D"
    property color danger: "#991B1B"

    MediaPlayer {
        id: player
        source: appController.videoUrl
        videoOutput: videoOutput
        audioOutput: AudioOutput {}

        onPositionChanged: currentTimeLabel.text = formatTime(position)
        onDurationChanged: totalTimeLabel.text = duration > 0 ? formatTime(duration) : "00:00:00"
    }

    ListModel { id: cutsModel }

    ListModel {
        id: aiModel
        ListElement { start: "00:05:21"; end: "00:05:45"; label: "Kissing scene"; score: "0.87"; tags: "kissing, romance" }
        ListElement { start: "00:12:36"; end: "00:12:55"; label: "AI suggested scene"; score: "0.92"; tags: "nsfw, kissing" }
        ListElement { start: "00:18:43"; end: "00:19:10"; label: "Intimate scene"; score: "0.78"; tags: "intimate, nsfw" }
    }

    function formatTime(ms) {
        var totalSeconds = Math.floor(ms / 1000)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var seconds = totalSeconds % 60

        function pad(n) { return n < 10 ? "0" + n : "" + n }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
    }

    function seekBy(seconds) {
        var newPosition = player.position + seconds * 1000
        if (newPosition < 0) newPosition = 0
        if (player.duration > 0 && newPosition > player.duration) newPosition = player.duration
        player.position = newPosition
    }

    function setStartFromVideo() { startInput.text = formatTime(player.position) }
    function setEndFromVideo() { endInput.text = formatTime(player.position) }

    function clearCutEditor() {
        startInput.text = "00:00:00"
        endInput.text = "00:00:00"
        reasonInput.text = ""
        tagsInput.text = ""
    }

    function addCut(source, score) {
        if (startInput.text.length === 0 || endInput.text.length === 0) return
        cutsModel.append({
            "start": startInput.text,
            "end": endInput.text,
            "reason": reasonInput.text.length > 0 ? reasonInput.text : "Manual cut",
            "tags": tagsInput.text.length > 0 ? tagsInput.text : "manual",
            "source": source,
            "score": score
        })
    }

    function addSuggestedCut(start, end, reason, tags, score) {
        cutsModel.append({
            "start": start,
            "end": end,
            "reason": reason,
            "tags": tags,
            "source": "AI",
            "score": score
        })
    }

    function applyRecommendation(start, end, reason, tags, score) {
        startInput.text = start
        endInput.text = end
        reasonInput.text = reason
        tagsInput.text = tags
    }

    component DarkScrollBar : ScrollBar {
        id: scrollBar
        policy: ScrollBar.AsNeeded

        contentItem: Rectangle {
            implicitWidth: 8
            implicitHeight: 8
            radius: 4
            color: scrollBar.pressed ? "#64748B" : "#475569"
            opacity: scrollBar.active ? 0.95 : 0.75
        }

        background: Rectangle {
            implicitWidth: 8
            color: "#111827"
            radius: 4
            opacity: 0.9
        }
    }

    Rectangle {
        anchors.fill: parent
        color: root.bg

        Rectangle {
            width: 520
            height: 520
            radius: 260
            x: -180
            y: -230
            color: "#0EA5E9"
            opacity: 0.06
        }

        Rectangle {
            width: 620
            height: 620
            radius: 310
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: -270
            anchors.bottomMargin: -260
            color: "#2563EB"
            opacity: 0.05
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: root.compactMode ? 10 : 14
            spacing: root.compactMode ? 8 : 10

            Panel {
                Layout.fillWidth: true
                Layout.preferredHeight: root.compactMode ? 52 : 58
                panelColor: root.panel
                strokeColor: "#1F2F4A"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: root.compactMode ? 8 : 10

                    Rectangle {
                        Layout.preferredWidth: 34
                        Layout.preferredHeight: 34
                        radius: 11
                        color: "#0B2038"
                        border.color: "#1E9BFF"

                        Text {
                            anchors.centerIn: parent
                            text: "CUT"
                            color: root.accent
                            font.pixelSize: 10
                            font.bold: true
                        }
                    }

                    Text {
                        text: "NSFW Cutter"
                        color: root.textMain
                        font.pixelSize: root.compactMode ? 17 : 20
                        font.bold: true
                        visible: !root.narrowMode
                    }

                    AppButton {
                        text: "Browse"
                        variant: "primary"
                        size: "md"
                        Layout.preferredWidth: root.compactMode ? 104 : 118
                        onClicked: appController.browseFolder()
                    }

                    AppButton {
                        text: "Clear"
                        variant: "secondary"
                        size: "md"
                        Layout.preferredWidth: 86
                        onClicked: {
                            appController.clearVideo()
                            player.stop()
                        }
                    }

                    Rectangle {
                        Layout.preferredHeight: 34
                        Layout.fillWidth: true
                        radius: 17
                        color: "#0A1120"
                        border.color: "#243244"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 8

                            Text {
                                text: appController.videoName
                                color: "#DDE7F6"
                                font.pixelSize: 13
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            Rectangle {
                                Layout.preferredWidth: 1
                                Layout.preferredHeight: 18
                                color: "#243244"
                                visible: !root.narrowMode
                            }

                            Text {
                                text: appController.subtitleStatus
                                color: "#86EFAC"
                                font.pixelSize: 12
                                elide: Text.ElideRight
                                Layout.preferredWidth: root.compactMode ? 170 : 260
                                visible: !root.narrowMode
                            }
                        }
                    }

                    Rectangle {
                        Layout.preferredHeight: 30
                        Layout.preferredWidth: root.compactMode ? 96 : 130
                        radius: 15
                        color: "#103D22"
                        border.color: "#1B6F3A"

                        Text {
                            anchors.centerIn: parent
                            text: appController.projectStatus
                            color: "#86EFAC"
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                            width: parent.width - 16
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: root.compactMode ? 8 : 10

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 900
                    spacing: root.compactMode ? 8 : 10

                    Panel {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 330
                        panelColor: root.panel
                        strokeColor: "#21324D"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: root.compactMode ? 10 : 12
                            spacing: root.compactMode ? 8 : 10

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 24
                                spacing: 8

                                Text {
                                    text: "VIDEO"
                                    color: root.accent
                                    font.pixelSize: 13
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
                                    text: "Cuts: " + cutsModel.count
                                    color: root.textMuted
                                    font.pixelSize: 12
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 14
                                color: root.videoBg
                                border.color: "#233452"
                                clip: true

                                VideoOutput {
                                    id: videoOutput
                                    anchors.fill: parent
                                    fillMode: VideoOutput.PreserveAspectFit
                                }

                                Column {
                                    anchors.centerIn: parent
                                    spacing: 10
                                    visible: appController.videoUrl.length === 0

                                    Rectangle {
                                        width: root.compactMode ? 70 : 86
                                        height: width
                                        radius: width / 2
                                        color: "#050A12"
                                        border.color: "#111827"

                                        Text {
                                            anchors.centerIn: parent
                                            text: "Play"
                                            color: "#F8FAFC"
                                            font.pixelSize: root.compactMode ? 16 : 19
                                            font.bold: true
                                        }
                                    }

                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: "No video loaded"
                                        color: root.textMuted
                                        font.pixelSize: 13
                                    }
                                }

                                Rectangle {
                                    anchors.centerIn: parent
                                    width: root.compactMode ? 70 : 86
                                    height: width
                                    radius: width / 2
                                    color: "#020617"
                                    opacity: player.playbackState === MediaPlayer.PlayingState || appController.videoUrl.length === 0 ? 0 : 0.86
                                    visible: appController.videoUrl.length > 0

                                    Text {
                                        anchors.centerIn: parent
                                        text: "Play"
                                        color: "#F8FAFC"
                                        font.pixelSize: root.compactMode ? 16 : 19
                                        font.bold: true
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: player.play()
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    id: currentTimeLabel
                                    text: "00:00:00"
                                    color: root.textMain
                                    font.pixelSize: 13
                                    Layout.preferredWidth: 66
                                }

                                Slider {
                                    id: timelineSlider
                                    Layout.fillWidth: true
                                    from: 0
                                    to: player.duration > 0 ? player.duration : 1
                                    value: player.position
                                    enabled: player.duration > 0

                                    onMoved: player.position = value

                                    background: Rectangle {
                                        x: timelineSlider.leftPadding
                                        y: timelineSlider.topPadding + timelineSlider.availableHeight / 2 - height / 2
                                        implicitHeight: 6
                                        width: timelineSlider.availableWidth
                                        height: implicitHeight
                                        radius: 3
                                        color: "#334155"

                                        Rectangle {
                                            width: timelineSlider.visualPosition * parent.width
                                            height: parent.height
                                            radius: 3
                                            color: root.accent
                                        }
                                    }

                                    handle: Rectangle {
                                        x: timelineSlider.leftPadding + timelineSlider.visualPosition * (timelineSlider.availableWidth - width)
                                        y: timelineSlider.topPadding + timelineSlider.availableHeight / 2 - height / 2
                                        width: 18
                                        height: 18
                                        radius: 9
                                        color: "#E0F2FE"
                                        border.color: root.accent
                                        border.width: 3
                                    }
                                }

                                Text {
                                    id: totalTimeLabel
                                    text: "00:00:00"
                                    color: root.textMain
                                    font.pixelSize: 13
                                    horizontalAlignment: Text.AlignRight
                                    Layout.preferredWidth: 66
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: root.compactMode ? 50 : 56
                                radius: 14
                                color: "#0A1120"
                                border.color: "#1F2F4A"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 8
                                    spacing: 8

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 40
                                        radius: 12
                                        color: "#08111F"
                                        border.color: "#18263B"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 4
                                            spacing: 4

                                            AppButton { text: "-60"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: seekBy(-60) }
                                            AppButton { text: "-15"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: seekBy(-15) }
                                            AppButton { text: "-5"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: seekBy(-5) }
                                        }
                                    }

                                    AppButton {
                                        text: player.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                                        variant: "primary"
                                        size: "lg"
                                        Layout.preferredWidth: root.compactMode ? 88 : 104
                                        Layout.preferredHeight: 40
                                        onClicked: player.playbackState === MediaPlayer.PlayingState ? player.pause() : player.play()
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 40
                                        radius: 12
                                        color: "#08111F"
                                        border.color: "#18263B"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 4
                                            spacing: 4

                                            AppButton { text: "+5"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: seekBy(5) }
                                            AppButton { text: "+15"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: seekBy(15) }
                                            AppButton { text: "+60"; variant: "control"; size: "sm"; Layout.fillWidth: true; onClicked: seekBy(60) }
                                        }
                                    }

                                    Rectangle {
                                        Layout.preferredWidth: root.compactMode ? 126 : 146
                                        Layout.preferredHeight: 40
                                        radius: 12
                                        color: "#0B2038"
                                        border.color: "#1D4F73"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 4
                                            spacing: 4

                                            AppButton {
                                                text: "Start"
                                                variant: "ghost"
                                                size: "sm"
                                                Layout.fillWidth: true
                                                onClicked: setStartFromVideo()
                                            }

                                            AppButton {
                                                text: "End"
                                                variant: "ghost"
                                                size: "sm"
                                                Layout.fillWidth: true
                                                onClicked: setEndFromVideo()
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Panel {
                        Layout.fillWidth: true
                        Layout.preferredHeight: root.shortMode ? 168 : 218
                        panelColor: root.panel
                        strokeColor: "#21324D"

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: root.compactMode ? 10 : 12
                            spacing: root.compactMode ? 8 : 10

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 12
                                color: "#08111F"
                                border.color: "#1F2F4A"
                                clip: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 8

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "AI PICKS"
                                            color: root.accent
                                            font.pixelSize: 13
                                            font.bold: true
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: "Add is one click"
                                            color: root.textMuted
                                            font.pixelSize: 12
                                            visible: !root.narrowMode
                                        }
                                    }

                                    ListView {
                                        id: aiListView
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        model: aiModel
                                        spacing: 6
                                        clip: true
                                        ScrollBar.vertical: DarkScrollBar {}

                                        delegate: Rectangle {
                                            required property int index
                                            required property string start
                                            required property string end
                                            required property string label
                                            required property string score
                                            required property string tags

                                            width: aiListView.width
                                            height: root.shortMode ? 44 : 50
                                            radius: 10
                                            color: "#0A1120"
                                            border.color: index === 1 ? "#155E9E" : "#1F2F4A"

                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.leftMargin: 10
                                                anchors.rightMargin: 8
                                                spacing: 8

                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 2

                                                    Text {
                                                        text: start + " - " + end
                                                        color: index === 1 ? root.accent : root.textMain
                                                        font.pixelSize: 13
                                                        font.weight: Font.DemiBold
                                                    }

                                                    Text {
                                                        text: label
                                                        color: root.textMuted
                                                        font.pixelSize: 11
                                                        elide: Text.ElideRight
                                                        Layout.fillWidth: true
                                                        visible: !root.shortMode
                                                    }
                                                }

                                                Text {
                                                    text: score
                                                    color: "#86EFAC"
                                                    font.pixelSize: 12
                                                    font.bold: true
                                                    Layout.preferredWidth: 34
                                                }

                                                AppButton {
                                                    text: "Edit"
                                                    variant: "ghost"
                                                    size: "sm"
                                                    Layout.preferredWidth: 52
                                                    onClicked: applyRecommendation(start, end, label, tags, score)
                                                }

                                                AppButton {
                                                    text: "Add"
                                                    variant: "primary"
                                                    size: "sm"
                                                    Layout.preferredWidth: 52
                                                    onClicked: addSuggestedCut(start, end, label, tags, score)
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 12
                                color: "#08111F"
                                border.color: "#1F2F4A"
                                clip: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 8

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "CUT LIST (" + cutsModel.count + ")"
                                            color: root.accent
                                            font.pixelSize: 13
                                            font.bold: true
                                        }
                                        Item { Layout.fillWidth: true }
                                        AppButton {
                                            text: "Clear form"
                                            variant: "ghost"
                                            size: "sm"
                                            Layout.preferredWidth: 82
                                            onClicked: clearCutEditor()
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 30
                                        radius: 9
                                        color: "#111C30"
                                        border.color: "#243244"
                                        visible: cutsModel.count > 0

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 10
                                            spacing: 10
                                            Text { text: "#"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: 24 }
                                            Text { text: "Start"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: 72 }
                                            Text { text: "End"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: 72 }
                                            Text { text: "Reason"; color: root.textMuted; font.pixelSize: 11; Layout.fillWidth: true }
                                            Text { text: "Score"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: 44; visible: !root.narrowMode }
                                            Text { text: ""; Layout.preferredWidth: 54 }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        radius: 10
                                        color: "#050B14"
                                        border.color: "#142033"
                                        clip: true

                                        Text {
                                            anchors.centerIn: parent
                                            visible: cutsModel.count === 0
                                            text: "No cuts yet. Mark start/end, then Add Cut."
                                            color: root.textMuted
                                            font.pixelSize: 13
                                        }

                                        ListView {
                                            id: cutsListView
                                            anchors.fill: parent
                                            visible: cutsModel.count > 0
                                            model: cutsModel
                                            clip: true
                                            spacing: 1
                                            ScrollBar.vertical: DarkScrollBar {}

                                        delegate: Rectangle {
                                            required property int index
                                            required property string start
                                            required property string end
                                            required property string reason
                                            required property string score

                                            width: cutsListView.width
                                            height: 38
                                                color: index % 2 === 0 ? "#0B1324" : "#0E1728"
                                                border.color: "#142033"

                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 10
                                                    anchors.rightMargin: 8
                                                    spacing: 10

                                                    Text { text: index + 1; color: root.textMain; font.pixelSize: 12; Layout.preferredWidth: 24 }
                                                    Text { text: start; color: root.textMain; font.pixelSize: 12; Layout.preferredWidth: 72 }
                                                    Text { text: end; color: root.textMain; font.pixelSize: 12; Layout.preferredWidth: 72 }
                                                    Text { text: reason; color: "#E5E7EB"; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                                    Text { text: score; color: score === "--" ? root.textMuted : "#86EFAC"; font.pixelSize: 12; Layout.preferredWidth: 44; visible: !root.narrowMode }

                                                    AppButton {
                                                        text: "Del"
                                                        variant: "danger"
                                                        size: "sm"
                                                        Layout.preferredWidth: 48
                                                        onClicked: cutsModel.remove(index)
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Panel {
                    id: cutEditorPanel
                    Layout.preferredWidth: root.narrowMode ? 330 : 380
                    Layout.minimumWidth: 320
                    Layout.fillHeight: true
                    panelColor: root.panel
                    strokeColor: "#21324D"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: root.compactMode ? 12 : 16
                        spacing: root.compactMode ? 8 : 10

                        RowLayout {
                            Layout.fillWidth: true

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: "FAST CUT"
                                    color: root.accent
                                    font.pixelSize: 15
                                    font.bold: true
                                    font.letterSpacing: 0.6
                                }

                                Text {
                                    text: "Mark time, type context, add"
                                    color: root.textMuted
                                    font.pixelSize: 12
                                }
                            }

                            Rectangle {
                                Layout.preferredHeight: 28
                                Layout.preferredWidth: 78
                                radius: 14
                                color: "#12223A"
                                border.color: "#284566"

                                Text {
                                    anchors.centerIn: parent
                                    text: "Manual"
                                    color: root.textMuted
                                    font.pixelSize: 12
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 1
                            color: "#1F2F4A"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Text {
                                text: "Start"
                                color: root.textMain
                                font.pixelSize: 12
                                Layout.preferredWidth: 40
                            }

                            AppTextField {
                                id: startInput
                                Layout.fillWidth: true
                                placeholderText: "00:00:00"
                                text: "00:00:00"
                            }

                            AppButton {
                                text: "Now"
                                variant: "ghost"
                                size: "sm"
                                Layout.preferredWidth: 58
                                onClicked: setStartFromVideo()
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Text {
                                text: "End"
                                color: root.textMain
                                font.pixelSize: 12
                                Layout.preferredWidth: 40
                            }

                            AppTextField {
                                id: endInput
                                Layout.fillWidth: true
                                placeholderText: "00:00:00"
                                text: "00:00:00"
                                onAccepted: addCut("Manual", "--")
                            }

                            AppButton {
                                text: "Now"
                                variant: "ghost"
                                size: "sm"
                                Layout.preferredWidth: 58
                                onClicked: setEndFromVideo()
                            }
                        }

                        Text { text: "Reason"; color: root.textMain; font.pixelSize: 12 }

                        AppTextArea {
                            id: reasonInput
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(root.shortMode ? 92 : 128, Math.max(38, contentHeight + topPadding + bottomPadding))
                            placeholderText: "Reason for this cut..."
                        }

                        Text { text: "Tags"; color: root.textMain; font.pixelSize: 12 }

                        AppTextField {
                            id: tagsInput
                            Layout.fillWidth: true
                            placeholderText: "kissing, romance, nsfw"
                            onAccepted: addCut("Manual", "--")
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            AppButton {
                                text: "+ Add Cut"
                                variant: "primary"
                                size: "lg"
                                Layout.fillWidth: true
                                onClicked: addCut("Manual", "--")
                            }

                            AppButton {
                                text: "Reset"
                                variant: "danger"
                                size: "md"
                                Layout.preferredWidth: 80
                                onClicked: clearCutEditor()
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 1
                            color: "#1F2F4A"
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: root.shortMode ? 92 : 120
                            radius: 12
                            color: "#0A1120"
                            border.color: "#1F2F4A"
                            clip: true

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 5

                                Text {
                                    text: "STATUS"
                                    color: root.accent
                                    font.pixelSize: 12
                                    font.bold: true
                                }

                                Text {
                                    text: "Output: MKV without re-encoding"
                                    color: root.textMuted
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }

                                Text {
                                    text: "Subtitle sync: enabled"
                                    color: root.textMuted
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }

                                Text {
                                    text: "Autosave ON"
                                    color: "#22C55E"
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                }
                            }
                        }

                        Item { Layout.fillHeight: true }

                        AppButton {
                            text: "Generate New Video"
                            variant: "success"
                            size: "lg"
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
    }
}
