import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property bool lightMode: false
    property bool narrowMode: false
    property bool shortMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int scrollbarGutter: 14
    readonly property bool denseMode: root.narrowMode || root.width < 360

    signal editRequested(string startTime, string endTime, string reason, string tags)
    signal addRequested(string startTime, string endTime, string reason, string tags, string score)

    radius: 14
    color: root.lightMode ? "#FFFFFF" : "#08111F"
    border.color: root.lightMode ? "#CBD5E1" : "#1F2F4A"
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
                font.pixelSize: 15
                font.bold: true
                font.letterSpacing: 0.8
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
            ScrollBar.vertical: AppScrollBar { lightMode: root.lightMode }

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
                color: root.lightMode ? (index === 1 ? "#EFF6FF" : "#F8FAFC") : "#0A1120"
                border.color: root.lightMode ? (index === 1 ? "#60A5FA" : "#CBD5E1") : (index === 1 ? "#155E9E" : "#1F2F4A")

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 8
                    spacing: root.denseMode ? 4 : 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 2

                        Text {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: start + " - " + end
                            color: index === 1 ? root.accent : root.textMain
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
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
                        color: root.lightMode ? "#16A34A" : "#86EFAC"
                        font.pixelSize: 12
                        font.bold: true
                        Layout.preferredWidth: 34
                        visible: !root.denseMode
                    }

                    AppButton {
                        text: "Edit"
                        variant: "ghost"
                        size: "sm"
                        lightMode: root.lightMode
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: root.denseMode ? 44 : 52
                        onClicked: root.editRequested(start, end, label, tags)
                    }

                    AppButton {
                        text: "Add"
                        variant: "primary"
                        size: "sm"
                        lightMode: root.lightMode
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: root.denseMode ? 44 : 52
                        onClicked: root.addRequested(start, end, label, tags, score)
                    }
                }
            }
        }
    }
}
