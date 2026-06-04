import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property bool lightMode: false
    property bool narrowMode: false
    property bool shortMode: false
    property color textMain: "#F3F6FB"
    property color textMuted: "#92A2B8"
    property color accent: "#2F7BFF"
    property int scrollbarGutter: 14
    property var picksModel: emptyAiModel
    readonly property int pickCount: root.picksModel ? root.picksModel.count : 0

    signal editRequested(string startTime, string endTime, string reason, string tags)
    signal addRequested(string startTime, string endTime, string reason, string tags, string score)

    implicitHeight: root.pickCount === 0 ? 44 : (root.shortMode ? 94 : 108)
    radius: 14
    color: root.lightMode ? theme.lightSurface : theme.darkSurface
    border.color: root.lightMode ? theme.lightBorder : theme.darkBorder
    clip: true

    AppTheme { id: theme }
    ListModel { id: emptyAiModel }

    function parseTimeMs(value) {
        var parts = String(value).trim().split(":")
        if (parts.length !== 3) return 0
        var seconds = Number(parts[2])
        if (!Number.isFinite(seconds)) return 0
        return (Number(parts[0]) * 3600 + Number(parts[1]) * 60 + seconds) * 1000
    }

    function durationText(start, end) {
        var durationMs = Math.max(0, root.parseTimeMs(end) - root.parseTimeMs(start))
        var totalSeconds = Math.floor(durationMs / 1000)
        var minutes = Math.floor(totalSeconds / 60)
        var seconds = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return "00:" + pad(minutes) + ":" + pad(seconds)
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: root.pickCount === 0 ? 10 : 8
        spacing: 10
        visible: root.pickCount === 0

        Text {
            text: "AI PICKS"
            color: root.accent
            font.pixelSize: 14
            font.bold: true
            font.letterSpacing: 0.8
            Layout.preferredWidth: 92
        }

        Text {
            Layout.fillWidth: true
            text: "No suggestions loaded."
            color: root.textMuted
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10
        visible: root.pickCount > 0

        ColumnLayout {
            Layout.preferredWidth: root.narrowMode ? 104 : 128
            Layout.fillHeight: true
            spacing: 2

            Text {
                Layout.fillWidth: true
                text: "AI PICKS"
                color: root.accent
                font.pixelSize: 14
                font.bold: true
                font.letterSpacing: 0.8
                elide: Text.ElideRight
            }

            Text {
                Layout.fillWidth: true
                text: root.pickCount + " suggestions"
                color: root.textMuted
                font.pixelSize: 12
                elide: Text.ElideRight
            }
        }

        ListView {
            id: aiListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: root.picksModel
            orientation: ListView.Horizontal
            spacing: 8
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.horizontal: AppScrollBar { lightMode: root.lightMode }

            delegate: Rectangle {
                required property int index
                required property string start
                required property string end
                required property string label
                required property string score
                required property string tags

                width: Math.min(310, Math.max(240, aiListView.width * 0.34))
                height: aiListView.height - root.scrollbarGutter
                radius: 12
                color: root.lightMode ? "#FFFFFF" : "#0C1625"
                border.color: root.lightMode ? "#DCE4EF" : "#223247"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 9
                    spacing: 8

                    Text {
                        text: index + 1
                        color: root.accent
                        font.pixelSize: 13
                        font.bold: true
                        Layout.preferredWidth: 18
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 2

                        Text {
                            Layout.fillWidth: true
                            text: start + " - " + end
                            color: root.textMain
                            font.pixelSize: 12
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.durationText(start, end) + " - " + score + " - " + label
                            color: root.textMuted
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }

                    AppButton {
                        text: "+"
                        variant: "primary"
                        size: "sm"
                        lightMode: root.lightMode
                        Layout.preferredWidth: 40
                        Layout.preferredHeight: 34
                        onClicked: root.addRequested(start, end, label, tags, score)
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.RightButton
                    onClicked: root.editRequested(start, end, label, tags)
                }
            }
        }
    }
}
