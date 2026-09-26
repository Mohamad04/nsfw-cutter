pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

Rectangle {
    id: root
    objectName: "exportActionBar"

    property string outputDir: ""
    property bool lightMode: false
    property bool hasVideo: false
    property bool hasCuts: false
    property string cutTimingMode: "safe"
    property color panelColor: "#0C1625"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    readonly property int cutProgressPercent: Math.max(0, Math.min(100, Math.round(videoCutController.cutProgressValue)))
    readonly property int cutRemainingPercent: Math.max(0, 100 - root.cutProgressPercent)
    readonly property string cuttingModeLabel: root.cutTimingMode === "requested" ? qsTr("Fast cutting") : qsTr("Smart cutting")
    readonly property string outputPathsText: root.joinOutputPaths(videoCutController.cutOutputPaths)
    readonly property bool exportFailed: !videoCutController.cutBusy && videoCutController.cutError.length > 0
    readonly property bool exportCompleted: !videoCutController.cutBusy && root.outputPathsText.length > 0
    readonly property bool hasExportResult: root.exportFailed || root.exportCompleted

    implicitHeight: 66 + (root.hasExportResult ? exportResultPanel.implicitHeight + 8 : 0)

    signal chooseFolderRequested()
    signal exportCleanVideoRequested()

    function joinOutputPaths(paths) {
        var values = []
        for (var index = 0; paths && index < paths.length; index += 1)
            values.push(String(paths[index]))
        return values.join(" • ")
    }

    function singleLine(value) {
        return String(value || "").replace(/\s*\n\s*/g, " • ")
    }

    radius: 14
    color: root.lightMode ? root.panelColor : "#081321"
    border.color: root.lightMode ? root.strokeColor : "#223754"
    clip: true

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 13
        color: "transparent"
        border.color: root.lightMode ? "#FFFFFF" : "#163456"
        opacity: root.lightMode ? 0.36 : 0.42
    }

    RowLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 12
        height: 42
        spacing: 10

        Text {
            text: qsTr("Output Folder")
            color: root.textColor
            font.pixelSize: 12
            font.weight: Font.DemiBold
            Layout.preferredWidth: 96
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.minimumWidth: 180
            Layout.preferredHeight: 42
            radius: 11
            color: root.lightMode ? "#F8FAFC" : "#06101D"
            border.color: root.lightMode ? "#DCE4EF" : "#1C3150"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8

                VectorIcon {
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                    name: "folder"
                    iconColor: root.outputDir.length > 0 ? root.accentColor : root.mutedTextColor
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: root.outputDir.length > 0 ? root.outputDir : qsTr("Choose an output folder")
                    color: root.outputDir.length > 0 ? root.textColor : root.mutedTextColor
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }

        AppButton {
            text: qsTr("Change...")
            iconName: "folder"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: !videoCutController.cutBusy
            Layout.preferredWidth: 122
            Layout.preferredHeight: 40
            onClicked: root.chooseFolderRequested()
        }

        AppButton {
            text: qsTr("Preview Cuts")
            iconName: "eye"
            variant: "ghost"
            size: "sm"
            lightMode: root.lightMode
            enabled: false
            Layout.preferredWidth: 144
            Layout.preferredHeight: 40
            ToolTip.visible: hovered
            ToolTip.text: root.hasCuts
                ? qsTr("Previewing the final all-cuts output is not connected yet")
                : qsTr("Add at least one cut to preview")
        }

        Item {
            visible: videoCutController.cutBusy
            Layout.preferredWidth: videoCutController.cutBusy ? 246 : 0
            Layout.minimumWidth: videoCutController.cutBusy ? 218 : 0
            Layout.preferredHeight: 40

            ColumnLayout {
                anchors.fill: parent
                spacing: 4

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 16
                    spacing: 8

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: root.cuttingModeLabel
                        color: root.textColor
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Text {
                        text: root.cutProgressPercent + "% / 100%"
                        color: root.accentColor
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: qsTr("%1% left").arg(root.cutRemainingPercent)
                        color: root.mutedTextColor
                        font.pixelSize: 11
                    }
                }

                ProgressBar {
                    id: smartCutProgress

                    Layout.fillWidth: true
                    Layout.preferredHeight: 6
                    from: 0
                    to: 100
                    value: root.cutProgressPercent

                    background: Rectangle {
                        radius: 3
                        color: root.lightMode ? "#E2E8F0" : "#111827"
                    }

                    contentItem: Item {
                        Rectangle {
                            width: parent.width * smartCutProgress.visualPosition
                            height: parent.height
                            radius: 3
                            color: root.accentColor
                        }
                    }
                }
            }
        }

        AppButton {
            text: qsTr("Export Clean Video")
            iconName: "export"
            variant: "success"
            size: "sm"
            lightMode: root.lightMode
            enabled: root.hasVideo && root.hasCuts && !videoCutController.cutBusy
            Layout.preferredWidth: 196
            Layout.preferredHeight: 40
            onClicked: root.exportCleanVideoRequested()
        }
    }

    Rectangle {
        id: exportResultPanel
        objectName: "exportResultPanel"

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.bottomMargin: 8
        implicitHeight: exportResultColumn.implicitHeight + 12
        visible: root.hasExportResult
        radius: 9
        color: root.exportFailed
            ? (root.lightMode ? "#FEF2F2" : "#2A1115")
            : (root.lightMode ? "#F0FDF4" : "#0D2418")
        border.color: root.exportFailed
            ? (root.lightMode ? "#FCA5A5" : "#7F1D1D")
            : (root.lightMode ? "#86EFAC" : "#166534")

        ColumnLayout {
            id: exportResultColumn

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 2

            Text {
                objectName: "exportResultStatusText"
                Layout.fillWidth: true
                text: root.exportFailed ? qsTr("Export failed") : qsTr("Export completed")
                color: root.exportFailed
                    ? (root.lightMode ? "#B91C1C" : "#FCA5A5")
                    : (root.lightMode ? "#166534" : "#86EFAC")
                font.pixelSize: 12
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            Text {
                objectName: "exportOutputPathText"
                Layout.fillWidth: true
                text: qsTr("Output: %1").arg(root.outputPathsText)
                color: root.textColor
                font.pixelSize: 11
                elide: Text.ElideMiddle
                visible: root.exportCompleted
                ToolTip.visible: outputPathMouse.containsMouse
                ToolTip.text: root.outputPathsText

                MouseArea {
                    id: outputPathMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    hoverEnabled: true
                }
            }

            Text {
                objectName: "exportWarningText"
                Layout.fillWidth: true
                text: qsTr("Warning: %1").arg(root.singleLine(videoCutController.cutWarning))
                color: root.lightMode ? "#9A3412" : "#FDBA74"
                font.pixelSize: 11
                elide: Text.ElideRight
                visible: root.exportCompleted && videoCutController.cutWarning.length > 0
                ToolTip.visible: warningMouse.containsMouse
                ToolTip.text: videoCutController.cutWarning

                MouseArea {
                    id: warningMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    hoverEnabled: true
                }
            }

            Text {
                objectName: "exportErrorText"
                Layout.fillWidth: true
                text: videoCutController.cutError
                color: root.lightMode ? "#B91C1C" : "#FCA5A5"
                font.pixelSize: 11
                elide: Text.ElideRight
                visible: root.exportFailed
                ToolTip.visible: errorMouse.containsMouse
                ToolTip.text: videoCutController.cutError

                MouseArea {
                    id: errorMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    hoverEnabled: true
                }
            }

            Text {
                objectName: "exportDetailsText"
                Layout.fillWidth: true
                text: qsTr("Details: %1").arg(root.singleLine(videoCutController.cutDetails))
                color: root.mutedTextColor
                font.pixelSize: 10
                elide: Text.ElideRight
                visible: root.exportCompleted && videoCutController.cutDetails.length > 0
                ToolTip.visible: detailsMouse.containsMouse
                ToolTip.text: videoCutController.cutDetails

                MouseArea {
                    id: detailsMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    hoverEnabled: true
                }
            }
        }
    }
}

