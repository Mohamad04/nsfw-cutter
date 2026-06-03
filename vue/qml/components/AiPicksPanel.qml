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

    radius: 16
    color: root.lightMode ? theme.lightSurface : theme.darkSurface
    border.color: root.lightMode ? theme.lightBorder : theme.darkBorder
    clip: true

    AppTheme { id: theme }
    ListModel { id: emptyAiModel }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 12

        ColumnLayout {
            Layout.preferredWidth: root.narrowMode ? 138 : 168
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
                text: root.pickCount > 0 ? (root.pickCount + " detections") : "No detections loaded"
                color: root.textMuted
                font.pixelSize: 12
                elide: Text.ElideRight
            }

            Item { Layout.fillHeight: true }

            Text {
                Layout.fillWidth: true
                text: "Horizontal suggestions"
                color: root.textMuted
                opacity: 0.78
                font.pixelSize: 10
                visible: !root.shortMode
                elide: Text.ElideRight
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 14
            color: root.lightMode ? "#F8FAFC" : "#081321"
            border.color: root.lightMode ? "#DCE4EF" : "#1B2B45"
            clip: true

            Text {
                anchors.centerIn: parent
                width: parent.width - 36
                text: "AI detections will appear here when a real detection model exposes results to the UI."
                color: root.textMuted
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                visible: root.pickCount === 0
            }

            ListView {
                id: aiListView
                anchors.fill: parent
                anchors.margins: 8
                visible: root.pickCount > 0
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

                    width: Math.min(300, Math.max(230, aiListView.width * 0.32))
                    height: aiListView.height - root.scrollbarGutter
                    radius: 12
                    color: root.lightMode ? (index === 0 ? "#EFF6FF" : "#FFFFFF") : (index === 0 ? "#12223A" : "#0C1625")
                    border.color: root.lightMode ? (index === 0 ? "#9BC2FF" : "#DCE4EF") : (index === 0 ? root.accent : "#223247")

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 9
                        spacing: 5

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: start + " - " + end
                                color: root.textMain
                                font.pixelSize: 12
                                font.bold: true
                                elide: Text.ElideRight
                            }
                            Text {
                                text: score
                                color: root.lightMode ? "#15803D" : "#8AE6A2"
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: label
                            color: root.textMuted
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: tags
                            color: root.textMuted
                            opacity: 0.82
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }

                        Item { Layout.fillHeight: true }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            AppButton {
                                text: "Edit"
                                variant: "ghost"
                                size: "sm"
                                lightMode: root.lightMode
                                Layout.fillWidth: true
                                onClicked: root.editRequested(start, end, label, tags)
                            }
                            AppButton {
                                text: "Add"
                                variant: "primary"
                                size: "sm"
                                lightMode: root.lightMode
                                Layout.fillWidth: true
                                onClicked: root.addRequested(start, end, label, tags, score)
                            }
                        }
                    }
                }
            }
        }
    }
}
