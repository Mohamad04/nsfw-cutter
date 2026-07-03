import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

Rectangle {
    id: root

    property string outputDir: ""
    property bool lightMode: false
    property bool narrowMode: false
    property bool hasSegments: false
    property color textMain: "#F3F6FB"
    property color textMuted: "#92A2B8"
    property color accent: "#2F7BFF"
    readonly property int cutProgressPercent: Math.max(0, Math.min(100, Math.round(videoCutController.cutProgressValue)))
    readonly property int cutRemainingPercent: Math.max(0, 100 - root.cutProgressPercent)

    signal chooseFolderRequested()
    signal previewCutsRequested()
    signal exportRemoveRequested()

    implicitHeight: 78
    radius: 16
    color: root.lightMode ? theme.lightSurface : theme.darkSurface
    border.color: root.lightMode ? theme.lightBorder : theme.darkBorder
    clip: true

    AppTheme { id: theme }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            spacing: 8

            Text {
                text: "Output Folder"
                color: root.textMain
                font.pixelSize: 12
                font.bold: true
                Layout.preferredWidth: root.narrowMode ? 86 : 104
                elide: Text.ElideRight
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 140
                Layout.preferredHeight: 38
                radius: 12
                color: root.lightMode ? "#F8FAFC" : "#081321"
                border.color: root.lightMode ? "#DCE4EF" : "#1B2B45"

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    text: root.outputDir.length > 0 ? root.outputDir : "Choose an output folder"
                    color: root.outputDir.length > 0 ? root.textMain : root.textMuted
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                    verticalAlignment: Text.AlignVCenter
                }
            }

            AppButton {
                text: "Change"
                variant: "secondary"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: 82
                Layout.preferredHeight: 38
                enabled: !videoCutController.cutBusy
                onClicked: root.chooseFolderRequested()
            }

            AppButton {
                text: "Preview Cuts"
                variant: "control"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: root.narrowMode ? 108 : 126
                Layout.preferredHeight: 38
                enabled: root.hasSegments && !videoCutController.cutBusy
                onClicked: root.previewCutsRequested()
            }

            AppButton {
                text: "Export Clean Video"
                variant: "success"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: root.narrowMode ? 144 : 172
                Layout.preferredHeight: 38
                enabled: root.hasSegments && !videoCutController.cutBusy
                onClicked: root.exportRemoveRequested()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 16
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: videoCutController.cutBusy
                      ? videoCutController.cutStatus
                      : "Smart cuts exact intervals with boundary re-encoding. Fast uses stream copy."
                color: videoCutController.cutError.length > 0 ? (root.lightMode ? theme.lightDanger : theme.darkDanger) : root.textMuted
                font.pixelSize: 11
                elide: Text.ElideRight
            }

            Text {
                text: videoCutController.cutBusy ? root.cutProgressPercent + "% / 100% - " + root.cutRemainingPercent + "% left" : ""
                color: root.accent
                font.pixelSize: 11
                font.bold: true
                visible: videoCutController.cutBusy
            }
        }

        ProgressBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 5
            visible: videoCutController.cutBusy
            from: 0
            to: 1
            value: root.cutProgressPercent / 100

            background: Rectangle { radius: 3; color: root.lightMode ? "#E2E8F0" : "#111827" }
            contentItem: Item {
                Rectangle {
                    width: parent.width * root.cutProgressPercent / 100
                    height: parent.height
                    radius: 3
                    color: root.accent
                }
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: 14
            text: videoCutController.cutError
            color: root.lightMode ? theme.lightDanger : theme.darkDanger
            font.pixelSize: 10
            elide: Text.ElideRight
            visible: videoCutController.cutError.length > 0
        }
    }
}

