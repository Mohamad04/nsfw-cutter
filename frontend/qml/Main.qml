import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

import "components"

ApplicationWindow {
    id: root
    visible: true
    width: 1500
    height: 940
    minimumWidth: 1240
    minimumHeight: 760
    title: "NSFW Cutter"
    color: "#0F172A"

    property color bg: "#0F172A"
    property color panel: "#0B1324"
    property color panel2: "#111827"
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

    function applyRecommendation(start, end, reason, tags, score) {
        startInput.text = start
        endInput.text = end
        reasonInput.text = reason
        tagsInput.text = tags
    }

    component DarkScrollBar : ScrollBar {
        policy: ScrollBar.AsNeeded

        contentItem: Rectangle {
            implicitWidth: 8
            implicitHeight: 8
            radius: 4
            color: parent.pressed ? "#64748B" : "#475569"
            opacity: parent.active ? 0.95 : 0.75
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
            y: -220
            color: "#0EA5E9"
            opacity: 0.06
        }

        Rectangle {
            width: 680
            height: 680
            radius: 340
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: -280
            anchors.bottomMargin: -260
            color: "#2563EB"
            opacity: 0.05
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 16

            Panel {
                Layout.fillWidth: true
                Layout.preferredHeight: 68
                panelColor: "#0B1324"
                strokeColor: "#1F2F4A"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 18
                    anchors.rightMargin: 18
                    spacing: 14

                    Rectangle {
                        Layout.preferredWidth: 36
                        Layout.preferredHeight: 36
                        radius: 12
                        color: "#0B2038"
                        border.color: "#1E9BFF"

                        Text {
                            anchors.centerIn: parent
                            text: "CUT"
                            color: root.accent
                            font.pixelSize: 11
                            font.bold: true
                        }
                    }

                    Text {
                        text: "NSFW Cutter"
                        color: root.textMain
                        font.pixelSize: 22
                        font.bold: true
                    }

                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 32
                        color: "#1F2F4A"
                        Layout.leftMargin: 10
                        Layout.rightMargin: 8
                    }

                    AppButton {
                        text: "Browse Folder"
                        variant: "primary"
                        size: "md"
                        Layout.preferredWidth: 160
                        onClicked: appController.browseFolder()
                    }

                    AppButton {
                        text: "Clear Video"
                        variant: "secondary"
                        size: "md"
                        Layout.preferredWidth: 140
                        onClicked: {
                            appController.clearVideo()
                            player.stop()
                        }
                    }

                    Text {
                        text: "Current Video: " + appController.videoName
                        color: "#DDE7F6"
                        font.pixelSize: 15
                        elide: Text.ElideRight
                        Layout.leftMargin: 18
                        Layout.maximumWidth: 330
                    }

                    Rectangle {
                        Layout.preferredHeight: 34
                        Layout.preferredWidth: 330
                        radius: 17
                        color: "#103D22"
                        border.color: "#1B6F3A"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            spacing: 8

                            Rectangle {
                                Layout.preferredWidth: 8
                                Layout.preferredHeight: 8
                                radius: 4
                                color: "#22C55E"
                            }

                            Text {
                                text: appController.subtitleStatus
                                color: "#86EFAC"
                                font.pixelSize: 13
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: "Active  " + appController.projectStatus
                        color: "#22C55E"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }

                    AppButton {
                        text: "UI"
                        variant: "ghost"
                        size: "icon"
                        Layout.preferredWidth: 48
                        Layout.preferredHeight: 44
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 16

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 970
                    spacing: 16

                    Panel {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 620
                        panelColor: "#0B1324"
                        strokeColor: "#21324D"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 14

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 28

                                Text {
                                    text: "VIDEO WORKSPACE"
                                    color: root.accent
                                    font.pixelSize: 13
                                    font.bold: true
                                    font.letterSpacing: 0.8
                                }

                                Rectangle {
                                    Layout.preferredWidth: 1
                                    Layout.preferredHeight: 18
                                    color: "#263754"
                                    Layout.leftMargin: 10
                                    Layout.rightMargin: 10
                                }

                                Text {
                                    text: player.duration > 0 ? "Preview ready" : "Waiting for media"
                                    color: root.textMuted
                                    font.pixelSize: 13
                                }

                                Item { Layout.fillWidth: true }

                                Text {
                                    text: "Format: MP4 / MKV"
                                    color: root.textMuted
                                    font.pixelSize: 13
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 16
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
                                    spacing: 12
                                    visible: appController.videoUrl.length === 0

                                    Rectangle {
                                        width: 92
                                        height: 92
                                        radius: 46
                                        color: "#050A12"
                                        border.color: "#111827"

                                        Text {
                                            anchors.centerIn: parent
                                            text: "Play"
                                            color: "#F8FAFC"
                                            font.pixelSize: 20
                                            font.bold: true
                                        }
                                    }

                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: "No video loaded"
                                        color: root.textMuted
                                        font.pixelSize: 14
                                    }
                                }

                                Rectangle {
                                    anchors.centerIn: parent
                                    width: 92
                                    height: 92
                                    radius: 46
                                    color: "#020617"
                                    opacity: player.playbackState === MediaPlayer.PlayingState || appController.videoUrl.length === 0 ? 0 : 0.86
                                    visible: appController.videoUrl.length > 0

                                    Text {
                                        anchors.centerIn: parent
                                        text: "Play"
                                        color: "#F8FAFC"
                                        font.pixelSize: 20
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
                                spacing: 12

                                Text {
                                    id: currentTimeLabel
                                    text: "00:00:00"
                                    color: root.textMain
                                    font.pixelSize: 14
                                    Layout.preferredWidth: 72
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
                                    font.pixelSize: 14
                                    horizontalAlignment: Text.AlignRight
                                    Layout.preferredWidth: 72
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 68
                                radius: 18
                                color: "#0A1120"
                                border.color: "#1F2F4A"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 18
                                    anchors.rightMargin: 18
                                    spacing: 12

                                    AppButton { text: "-1 min"; variant: "control"; size: "sm"; onClicked: seekBy(-60) }
                                    AppButton { text: "-15 sec"; variant: "control"; size: "sm"; onClicked: seekBy(-15) }
                                    AppButton { text: "-5 sec"; variant: "control"; size: "sm"; onClicked: seekBy(-5) }

                                    Item { Layout.fillWidth: true }

                                    AppButton {
                                        text: "Play"
                                        variant: "primary"
                                        size: "icon"
                                        Layout.preferredWidth: 74
                                        Layout.preferredHeight: 50
                                        onClicked: player.play()
                                    }

                                    AppButton {
                                        text: "Pause"
                                        variant: "secondary"
                                        size: "icon"
                                        Layout.preferredWidth: 74
                                        Layout.preferredHeight: 50
                                        onClicked: player.pause()
                                    }

                                    Item { Layout.fillWidth: true }

                                    AppButton { text: "+5 sec"; variant: "control"; size: "sm"; onClicked: seekBy(5) }
                                    AppButton { text: "+15 sec"; variant: "control"; size: "sm"; onClicked: seekBy(15) }
                                    AppButton { text: "+1 min"; variant: "control"; size: "sm"; onClicked: seekBy(60) }
                                }
                            }
                        }
                    }

                    Panel {
                        id: currentCutsPanel
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        panelColor: "#0B1324"
                        strokeColor: "#21324D"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 12

                            RowLayout {
                                Layout.fillWidth: true

                                Column {
                                    spacing: 2
                                    Text {
                                        text: "CURRENT CUTS (" + cutsModel.count + ")"
                                        color: root.accent
                                        font.pixelSize: 16
                                        font.bold: true
                                    }
                                    Text {
                                        text: "Manual and AI-assisted cut decisions"
                                        color: root.textMuted
                                        font.pixelSize: 12
                                    }
                                }

                                Item { Layout.fillWidth: true }

                                AppButton { text: "Import Cuts"; variant: "secondary"; size: "sm" }
                                AppButton { text: "Export Cuts"; variant: "secondary"; size: "sm" }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 42
                                radius: 12
                                color: "#111C30"
                                border.color: "#243244"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    spacing: 16

                                    Text { text: "#"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 38 }
                                    Text { text: "Start"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 100 }
                                    Text { text: "End"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 100 }
                                    Text { text: "Reason"; color: root.textMuted; font.pixelSize: 12; Layout.fillWidth: true }
                                    Text { text: "Tags"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 160 }
                                    Text { text: "Score"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 70 }
                                    Text { text: "Actions"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 110 }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 14
                                color: "#08111F"
                                border.color: "#1F2F4A"
                                clip: true

                                Text {
                                    anchors.centerIn: parent
                                    visible: cutsModel.count === 0
                                    text: "No cuts yet. Choose start and end time, add a reason, then click Add Cut."
                                    color: root.textMuted
                                    font.pixelSize: 14
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
                                        width: cutsListView.width
                                        height: 48
                                        color: index % 2 === 0 ? "#0B1324" : "#0E1728"
                                        border.color: "#1B2A42"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 14
                                            anchors.rightMargin: 14
                                            spacing: 16

                                            Text { text: index + 1; color: root.textMain; Layout.preferredWidth: 38 }
                                            Text { text: start; color: root.textMain; Layout.preferredWidth: 100 }
                                            Text { text: end; color: root.textMain; Layout.preferredWidth: 100 }
                                            Text { text: reason; color: "#E5E7EB"; Layout.fillWidth: true; elide: Text.ElideRight }
                                            Text { text: tags; color: root.textMuted; Layout.preferredWidth: 160; elide: Text.ElideRight }
                                            Text { text: score; color: score === "--" ? root.textMuted : "#86EFAC"; Layout.preferredWidth: 70 }

                                            RowLayout {
                                                Layout.preferredWidth: 110
                                                spacing: 8

                                                AppButton {
                                                    text: "Edit"
                                                    variant: "ghost"
                                                    size: "sm"
                                                    Layout.preferredWidth: 54
                                                }

                                                AppButton {
                                                    text: "Del"
                                                    variant: "danger"
                                                    size: "sm"
                                                    Layout.preferredWidth: 50
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

                ScrollView {
                    id: rightSidebarScroll
                    Layout.preferredWidth: 430
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.vertical: DarkScrollBar {}

                    ColumnLayout {
                        width: rightSidebarScroll.availableWidth
                        spacing: 18

                        Panel {
                            id: cutEditorPanel
                            Layout.fillWidth: true
                            Layout.preferredHeight: 580
                            Layout.minimumHeight: 560
                            panelColor: "#0B1324"
                            strokeColor: "#21324D"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 20
                                spacing: 12

                                RowLayout {
                                    Layout.fillWidth: true

                                    Text {
                                        text: "CUT EDITOR"
                                        color: root.accent
                                        font.pixelSize: 16
                                        font.bold: true
                                        font.letterSpacing: 0.6
                                    }

                                    Item { Layout.fillWidth: true }

                                    Rectangle {
                                        Layout.preferredHeight: 28
                                        Layout.preferredWidth: 88
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

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 14

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 8

                                        Text { text: "Start Time"; color: root.textMain; font.pixelSize: 13 }

                                        AppTextField {
                                            id: startInput
                                            Layout.fillWidth: true
                                            placeholderText: "00:00:00"
                                            text: "00:00:00"
                                        }

                                        AppButton {
                                            text: "Take start"
                                            variant: "ghost"
                                            size: "sm"
                                            Layout.fillWidth: true
                                            onClicked: setStartFromVideo()
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 8

                                        Text { text: "End Time"; color: root.textMain; font.pixelSize: 13 }

                                        AppTextField {
                                            id: endInput
                                            Layout.fillWidth: true
                                            placeholderText: "00:00:00"
                                            text: "00:00:00"
                                        }

                                        AppButton {
                                            text: "Take end"
                                            variant: "ghost"
                                            size: "sm"
                                            Layout.fillWidth: true
                                            onClicked: setEndFromVideo()
                                        }
                                    }
                                }

                                Text { text: "Reason"; color: root.textMain; font.pixelSize: 13 }

                                AppTextArea {
                                    id: reasonInput
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 92
                                    placeholderText: "Reason for this cut..."
                                }

                                Text { text: "Tags"; color: root.textMain; font.pixelSize: 13 }

                                AppTextField {
                                    id: tagsInput
                                    Layout.fillWidth: true
                                    placeholderText: "kissing, romance, nsfw"
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12

                                    AppButton {
                                        text: "+ Add Cut"
                                        variant: "primary"
                                        size: "md"
                                        Layout.fillWidth: true
                                        onClicked: addCut("Manual", "--")
                                    }

                                    AppButton {
                                        text: "Clear"
                                        variant: "danger"
                                        size: "md"
                                        Layout.preferredWidth: 110
                                        onClicked: clearCutEditor()
                                    }
                                }

                                AppButton {
                                    text: "Generate New Video"
                                    variant: "success"
                                    size: "lg"
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        Panel {
                            id: aiRecommendationsPanel
                            Layout.fillWidth: true
                            Layout.preferredHeight: 420
                            Layout.minimumHeight: 360
                            panelColor: "#0B1324"
                            strokeColor: "#21324D"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 20
                                spacing: 12

                                Text {
                                    text: "AI RECOMMENDATIONS"
                                    color: root.accent
                                    font.pixelSize: 16
                                    font.bold: true
                                    font.letterSpacing: 0.6
                                }

                                ListView {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    model: aiModel
                                    spacing: 10
                                    clip: true
                                    ScrollBar.vertical: DarkScrollBar {}

                                    delegate: Rectangle {
                                        width: ListView.view.width
                                        height: 74
                                        radius: 14
                                        color: "#0A1120"
                                        border.color: index === 1 ? "#155E9E" : "#1F2F4A"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 14
                                            anchors.rightMargin: 10
                                            spacing: 12

                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 5

                                                Text {
                                                    text: start + " - " + end
                                                    color: index === 1 ? root.accent : root.textMain
                                                    font.pixelSize: 14
                                                    font.weight: Font.DemiBold
                                                }

                                                Text {
                                                    text: label
                                                    color: root.textMuted
                                                    font.pixelSize: 12
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                            }

                                            Rectangle {
                                                Layout.preferredWidth: 56
                                                Layout.preferredHeight: 30
                                                radius: 15
                                                color: "#103D22"
                                                border.color: "#1B6F3A"

                                                Text {
                                                    anchors.centerIn: parent
                                                    text: score
                                                    color: "#86EFAC"
                                                    font.pixelSize: 13
                                                    font.bold: true
                                                }
                                            }

                                            AppButton {
                                                text: "Use"
                                                variant: "primary"
                                                size: "sm"
                                                Layout.preferredWidth: 58
                                                onClicked: applyRecommendation(start, end, label, tags, score)
                                            }
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 54
                                    radius: 14
                                    color: "#0A1120"
                                    border.color: "#1F2F4A"

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 14
                                        anchors.rightMargin: 14
                                        spacing: 10

                                        Text { text: "AI score"; color: root.textMuted; font.pixelSize: 12 }
                                        Rectangle { Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4; color: "#64748B" }
                                        Text { text: "Low"; color: root.textMuted; font.pixelSize: 12 }
                                        Rectangle { Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4; color: "#F59E0B" }
                                        Text { text: "Medium"; color: root.textMuted; font.pixelSize: 12 }
                                        Rectangle { Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4; color: "#22C55E" }
                                        Text { text: "High"; color: root.textMuted; font.pixelSize: 12 }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Panel {
                Layout.fillWidth: true
                Layout.preferredHeight: 50
                panelColor: "#0B1324"
                strokeColor: "#1F2F4A"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 18
                    anchors.rightMargin: 18
                    spacing: 20

                    Text { text: "Project: local session"; color: root.textMuted; font.pixelSize: 13 }
                    Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 24; color: "#1F2F4A" }
                    Text { text: "Output: MKV without re-encoding"; color: root.textMuted; font.pixelSize: 13 }
                    Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 24; color: "#1F2F4A" }
                    Text { text: "Subtitle sync: enabled"; color: root.textMuted; font.pixelSize: 13 }
                    Item { Layout.fillWidth: true }
                    Text { text: "Database: SQLite local"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: "Autosave ON"; color: "#22C55E"; font.pixelSize: 13 }
                    AppButton { text: "Cfg"; variant: "ghost"; size: "icon"; Layout.preferredWidth: 42; Layout.preferredHeight: 36 }
                }
            }
        }
    }
}
