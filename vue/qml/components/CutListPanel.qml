pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    required property var cutsModel
    property bool narrowMode: false
    property bool shortMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property int scrollbarGutter: 14
    property string outputDir: ""
    property int selectedIndex: -1
    property real durationMs: 0
    property real videoPositionMs: 0
    readonly property bool denseMode: root.width < 760
    readonly property bool cardRows: root.width < 1120
    readonly property bool compactTable: root.width < 1500
    readonly property int tableSpacing: root.compactTable ? 6 : 8
    readonly property int indexColumnWidth: root.compactTable ? 32 : 44
    readonly property int timeColumnWidth: root.compactTable ? 96 : 125
    readonly property int durationColumnWidth: root.compactTable ? 96 : 135
    readonly property int extraColumnWidth: root.compactTable ? 112 : 150
    readonly property int statusColumnWidth: root.compactTable ? 58 : 62
    readonly property int jumpButtonWidth: root.compactTable ? 52 : 58
    readonly property int editButtonWidth: root.compactTable ? 48 : 52
    readonly property int deleteButtonWidth: root.compactTable ? 64 : 68
    readonly property int actionsColumnWidth: root.jumpButtonWidth + root.editButtonWidth + root.deleteButtonWidth + (root.compactTable ? 12 : 16)

    signal importRequested()
    signal exportRequested()
    signal cutSelected(int index)
    signal editCutRequested(string startTime, string endTime, string reason, string tags)
    signal previewCutRequested(string startTime)
    signal jumpCutRequested(string timeText)
    signal fastExportAllRequested(string outputDir, string exportMode)

    radius: 12
    color: "#08111F"
    border.color: "#1F2F4A"
    clip: true

    Component.onCompleted: root.outputDir = settingsController.getExportDir()

    function parseTimeMs(value) {
        var parts = String(value).trim().split(":")
        if (parts.length !== 3) return 0
        return (Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])) * 1000
    }

    function setAllStatuses(value) {
        for (var index = 0; index < root.cutsModel.count; index += 1) {
            root.cutsModel.setProperty(index, "status", value)
        }
    }

    function chooseOutputFolder() {
        var folder = settingsController.chooseExportDir()
        if (folder.length === 0) return
        root.outputDir = folder
        settingsController.setExportDir(folder)
    }

    function deleteCut(index) {
        if (index < 0 || index >= root.cutsModel.count) return

        var nextSelected = root.selectedIndex
        if (root.selectedIndex === index) {
            nextSelected = Math.min(index, root.cutsModel.count - 2)
        } else if (root.selectedIndex > index) {
            nextSelected = root.selectedIndex - 1
        }

        root.cutsModel.remove(index)
        root.cutSelected(root.cutsModel.count > 0 ? nextSelected : -1)
    }

    Connections {
        target: videoCutController
        function onCutStarted() { root.setAllStatuses("Exporting") }
        function onCutFinished() { root.setAllStatuses(videoCutController.cutWarning.length > 0 ? "Warning" : "Done") }
        function onCutFailed() { root.setAllStatuses("Failed") }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: root.shortMode ? 36 : 44

            Text {
                Layout.minimumWidth: 0
                text: "CUT LIST (" + root.cutsModel.count + ")"
                color: root.accent
                font.pixelSize: 13
                font.bold: true
                elide: Text.ElideRight
            }

            Item { Layout.fillWidth: true }

            AppButton {
                text: "Import"
                variant: "secondary"
                size: "sm"
                Layout.preferredWidth: 62
                onClicked: root.importRequested()
            }

            AppButton {
                text: "JSON"
                variant: "secondary"
                size: "sm"
                Layout.preferredWidth: 56
                enabled: root.cutsModel.count > 0
                onClicked: root.exportRequested()
            }

            AppButton {
                text: "Clear"
                variant: "ghost"
                size: "sm"
                Layout.preferredWidth: 58
                enabled: root.cutsModel.count > 0
                onClicked: {
                    root.cutsModel.clear()
                    root.cutSelected(-1)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.shortMode ? 58 : 84
            Layout.minimumHeight: root.shortMode ? 52 : 70
            radius: 10
            color: "#050B14"
            border.color: "#142033"

            Text {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 10
                anchors.topMargin: 8
                text: root.durationMs > 0 ? "Removal timeline | cyan requested, orange safe stream-copy cut" : "Removal timeline waits for loaded video duration"
                color: root.textMuted
                font.pixelSize: 11
            }

            Text {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: 10
                anchors.topMargin: 8
                text: root.durationMs > 0 ? "Full video: 00:00:00 -> " + root.formatTime(root.durationMs) : ""
                color: root.textMuted
                font.pixelSize: 11
            }

            Rectangle {
                id: markerLane
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                anchors.bottomMargin: 18
                height: 16
                radius: 8
                color: "#243244"

                Repeater {
                    model: root.cutsModel

                    delegate: Item {
                        required property int index
                        required property var start
                        required property var end
                        required property var safeStart
                        required property var safeEnd
                        required property var reason
                        required property var tags

                        readonly property real startMs: root.parseTimeMs(start)
                        readonly property real endMs: root.parseTimeMs(end)
                        readonly property real safeStartMs: root.parseTimeMs(safeStart)
                        readonly property real safeEndMs: root.parseTimeMs(safeEnd)
                        readonly property real safeX: root.durationMs > 0 ? safeStartMs / root.durationMs * parent.width : 0
                        readonly property real safeW: root.durationMs > 0 ? Math.max(8, (safeEndMs - safeStartMs) / root.durationMs * parent.width) : 0
                        x: 0
                        width: parent.width
                        height: parent.height

                        Rectangle {
                            x: parent.safeX
                            width: parent.safeW
                            height: parent.height
                            radius: 8
                            color: root.selectedIndex === parent.index ? "#F97316" : "#EA580C"
                            border.color: "#FDE68A"
                            border.width: root.selectedIndex === parent.index ? 1 : 0
                        }

                        Rectangle {
                            x: root.durationMs > 0 ? parent.startMs / root.durationMs * parent.width : 0
                            y: 4
                            width: root.durationMs > 0 ? Math.max(6, (parent.endMs - parent.startMs) / root.durationMs * parent.width) : 0
                            height: parent.height - 8
                            radius: 4
                            color: root.selectedIndex === parent.index ? "#38BDF8" : "#0891B2"
                        }

                        MouseArea {
                            x: parent.safeX
                            width: parent.safeW
                            height: parent.height
                            hoverEnabled: true
                            onClicked: root.cutSelected(parent.index)
                            ToolTip.visible: containsMouse
                            ToolTip.text: "Requested: " + parent.start + " -> " + parent.end
                                          + "\nSafe cut: " + parent.safeStart + " -> " + parent.safeEnd
                                          + "\nReason: " + parent.reason + "\nTags: " + parent.tags
                        }
                    }
                }

                Rectangle {
                    width: 2
                    height: parent.height + 12
                    y: -6
                    x: root.durationMs > 0 ? Math.max(0, Math.min(parent.width - width, root.videoPositionMs / root.durationMs * parent.width)) : 0
                    color: "#E0F2FE"
                    visible: root.durationMs > 0
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.shortMode ? 26 : 30
            radius: 9
            color: "#111C30"
            border.color: "#243244"
            visible: root.cutsModel.count > 0 && !root.cardRows

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: root.tableSpacing
                Text { text: "#"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.indexColumnWidth; Layout.minimumWidth: 0 }
                Text { text: "Requested Start"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: "Requested End"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: "Safe Start"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: "Safe End"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: "Removed Duration"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.durationColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: "Extra Removed"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.extraColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: "Reason"; color: root.textMuted; font.pixelSize: 11; Layout.fillWidth: true; Layout.minimumWidth: 56; elide: Text.ElideRight }
                Text { text: "Status"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.statusColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: "Actions"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.actionsColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: root.shortMode ? 82 : 190
            Layout.minimumHeight: root.shortMode ? 70 : (root.narrowMode ? 120 : 140)
            radius: 10
            color: "#050B14"
            border.color: "#142033"
            clip: true

            Text {
                anchors.centerIn: parent
                visible: root.cutsModel.count === 0
                text: "Mark Start and End, then Add Cut. The interval appears here immediately."
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

                delegate: Item {
                    required property int index
                    required property var start
                    required property var end
                    required property var safeStart
                    required property var safeEnd
                    required property var extraBefore
                    required property var extraAfter
                    required property var cutType
                    required property var reason
                    required property var tags
                    required property var source
                    required property var score
                    required property var status

                    width: cutsListView.width - root.scrollbarGutter
                    height: row.height

                    CutSegmentRow {
                        id: row
                        width: parent.width
                        segmentIndex: parent.index + 1
                        startTime: parent.start
                        endTime: parent.end
                        safeStartTime: parent.safeStart
                        safeEndTime: parent.safeEnd
                        extraBefore: parent.extraBefore
                        extraAfter: parent.extraAfter
                        cutType: parent.cutType
                        reason: parent.reason
                        tags: parent.tags
                        source: parent.source
                        score: parent.score
                        status: parent.status
                        narrowMode: root.cardRows
                        compactTable: root.compactTable
                        indexColumnWidth: root.indexColumnWidth
                        timeColumnWidth: root.timeColumnWidth
                        durationColumnWidth: root.durationColumnWidth
                        extraColumnWidth: root.extraColumnWidth
                        statusColumnWidth: root.statusColumnWidth
                        jumpButtonWidth: root.jumpButtonWidth
                        editButtonWidth: root.editButtonWidth
                        deleteButtonWidth: root.deleteButtonWidth
                        selected: root.selectedIndex === parent.index
                        textMain: root.textMain
                        textMuted: root.textMuted
                        accent: root.accent
                        onSelectedRequested: root.cutSelected(parent.index)
                        onEditRequested: root.editCutRequested(parent.start, parent.end, parent.reason, parent.tags)
                        onPreviewRequested: root.previewCutRequested(parent.start)
                        onJumpStartRequested: root.jumpCutRequested(parent.start)
                        onJumpEndRequested: root.jumpCutRequested(parent.end)
                        onRemoveRequested: root.deleteCut(parent.index)
                    }
                }
            }
        }

        CutExportControls {
            Layout.fillWidth: true
            Layout.preferredHeight: root.shortMode ? 72 : 92
            Layout.minimumHeight: root.shortMode ? 64 : 80
            outputDir: root.outputDir
            narrowMode: root.narrowMode
            hasSegments: root.cutsModel.count > 0
            textMain: root.textMain
            textMuted: root.textMuted
            accent: root.accent
            onChooseFolderRequested: root.chooseOutputFolder()
            onExportRemoveRequested: root.fastExportAllRequested(root.outputDir, "remove_intervals")
        }
    }

    function formatTime(ms) {
        var totalSeconds = Math.floor(ms / 1000)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var seconds = totalSeconds % 60

        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
    }
}
