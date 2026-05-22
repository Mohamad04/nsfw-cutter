import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property bool narrowMode: false
    property bool shortMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int scrollbarGutter: 14

    signal editRequested(string startTime, string endTime, string reason, string tags)
    signal addRequested(string startTime, string endTime, string reason, string tags, string score)

    radius: 12
    color: "#08111F"
    border.color: "#1F2F4A"
    clip: true

    ListModel {
        id: aiModel
        ListElement { start: "00:05:21"; end: "00:05:45"; label: "Kissing scene"; score: "0.87"; tags: "kissing, romance" }
        ListElement { start: "00:12:36"; end: "00:12:55"; label: "AI suggested scene"; score: "0.92"; tags: "nsfw, kissing" }
        ListElement { start: "00:18:43"; end: "00:19:10"; label: "Intimate scene"; score: "0.78"; tags: "intimate, nsfw" }
    }

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
            ScrollBar.vertical: AppScrollBar {}

            delegate: Rectangle {
                required property int index
                required property string start
                required property string end
                required property string label
                required property string score
                required property string tags

                width: aiListView.width - root.scrollbarGutter
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
                        onClicked: root.editRequested(start, end, label, tags)
                    }

                    AppButton {
                        text: "Add"
                        variant: "primary"
                        size: "sm"
                        Layout.preferredWidth: 52
                        onClicked: root.addRequested(start, end, label, tags, score)
                    }
                }
            }
        }
    }
}
