import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    required property var cutsModel
    property bool narrowMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int scrollbarGutter: 14

    signal importRequested()
    signal exportRequested()

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
                text: "CUT LIST (" + root.cutsModel.count + ")"
                color: root.accent
                font.pixelSize: 13
                font.bold: true
            }

            Item { Layout.fillWidth: true }

            AppButton {
                text: "Import"
                variant: "secondary"
                size: "sm"
                Layout.preferredWidth: 68
                onClicked: root.importRequested()
            }

            AppButton {
                text: "Export"
                variant: "secondary"
                size: "sm"
                Layout.preferredWidth: 68
                enabled: root.cutsModel.count > 0
                onClicked: root.exportRequested()
            }

            AppButton {
                text: "Clear list"
                variant: "ghost"
                size: "sm"
                Layout.preferredWidth: 82
                enabled: root.cutsModel.count > 0
                onClicked: root.cutsModel.clear()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            radius: 9
            color: "#111C30"
            border.color: "#243244"
            visible: root.cutsModel.count > 0

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
                visible: root.cutsModel.count === 0
                text: "No cuts yet. Mark start/end, then Add Cut."
                color: root.textMuted
                font.pixelSize: 13
            }

            ListView {
                id: cutsListView
                anchors.fill: parent
                visible: root.cutsModel.count > 0
                model: root.cutsModel
                clip: true
                spacing: 1
                ScrollBar.vertical: AppScrollBar {}

                delegate: Rectangle {
                    required property int index
                    required property string start
                    required property string end
                    required property string reason
                    required property string score

                    width: cutsListView.width - root.scrollbarGutter
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
                            onClicked: root.cutsModel.remove(index)
                        }
                    }
                }
            }
        }
    }
}
