pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

Rectangle {
    id: root

    required property var cutsModel
    property bool compactMode: false
    property bool lightMode: false
    property bool narrowMode: false
    property bool shortMode: false
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"
    property color panelColor: root.lightMode ? "#FFFFFF" : "#08111F"
    property int scrollbarGutter: 14
    property string outputDir: ""
    property int selectedIndex: -1
    property real durationMs: 0
    property real videoPositionMs: 0
    property bool showExportControls: true
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

    TextMetrics {
        id: clearListTextMetrics
        text: qsTr("Clear List")
        font.pixelSize: 12
        font.weight: Font.Medium
    }

    radius: 14
    color: root.panelColor
    border.color: root.lightMode ? "#CBD5E1" : "#1F2F4A"
    clip: true

    Component.onCompleted: root.outputDir = settingsController.getExportDir()

    function parseTimeMs(value) {
        var parts = String(value).trim().split(":")
        if (parts.length !== 3) return 0
        var seconds = Number(parts[2])
        if (!Number.isFinite(seconds)) return 0
        return (Number(parts[0]) * 3600 + Number(parts[1]) * 60 + seconds) * 1000
    }

    function totalRemovedMs() {
        var total = 0
        for (var index = 0; index < root.cutsModel.count; index += 1) {
            var cut = root.cutsModel.get(index)
            var start = root.parseTimeMs(cut.safeStart || cut.start)
            var end = root.parseTimeMs(cut.safeEnd || cut.end)
            if (end > start) total += end - start
        }
        return total
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

    function clearCuts() {
        if (root.cutsModel.count === 0) return

        root.cutsModel.clear()
        root.cutSelected(-1)
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
        spacing: root.cutsModel.count === 0 ? 6 : 8

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: root.cutsModel.count === 0 ? 30 : (root.shortMode ? 34 : 40)

            Text {
                Layout.minimumWidth: 0
                text: qsTr("CUT TIMELINE")
                color: root.accent
                font.pixelSize: 15
                font.bold: true
                font.letterSpacing: 0.8
                elide: Text.ElideRight
            }

            Text {
                text: qsTr("%1 cuts - Total removed: %2").arg(root.cutsModel.count).arg(root.formatTime(root.totalRemovedMs()))
                color: root.textMuted
                font.pixelSize: 12
                elide: Text.ElideRight
                visible: !root.narrowMode
            }

            Item { Layout.fillWidth: true }

            AppButton {
                text: qsTr("Import")
                variant: "primary"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: 62
                onClicked: root.importRequested()
            }

            AppButton {
                text: qsTr("JSON")
                variant: "secondary"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: 56
                enabled: root.cutsModel.count > 0
                onClicked: root.exportRequested()
            }

            AppButton {
                text: qsTr("Clear List")
                iconName: "trash"
                variant: "secondary"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: Math.ceil(clearListTextMetrics.width) + 48
                Layout.minimumWidth: Layout.preferredWidth
                enabled: root.cutsModel.count > 0
                onClicked: clearCutsConfirmation.open()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.cutsModel.count === 0 ? 42 : (root.shortMode ? 54 : 70)
            Layout.minimumHeight: root.cutsModel.count === 0 ? 38 : 50
            radius: 10
            color: root.lightMode ? "#F8FAFC" : "#050B14"
            border.color: root.lightMode ? "#E2E8F0" : "#142033"

            Text {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 10
                anchors.topMargin: root.cutsModel.count === 0 ? 6 : 8
                text: root.durationMs > 0 ? qsTr("Orange requested - green safe adjusted removal") : qsTr("Timeline waits for loaded video duration")
                color: root.textMuted
                font.pixelSize: 11
            }

            Text {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: 10
                anchors.topMargin: root.cutsModel.count === 0 ? 6 : 8
                text: root.durationMs > 0 ? qsTr("Full video: 00:00:00 -> %1").arg(root.formatTime(root.durationMs)) : ""
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
                anchors.bottomMargin: root.cutsModel.count === 0 ? 8 : 16
                height: root.cutsModel.count === 0 ? 10 : 16
                radius: 8
                color: root.lightMode ? "#CBD5E1" : "#243244"

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
                            color: root.selectedIndex === parent.index ? "#2FBF62" : "#1FA34A"
                            border.color: root.lightMode ? "#166534" : "#8AE6A2"
                            border.width: root.selectedIndex === parent.index ? 1 : 0
                        }

                        Rectangle {
                            x: root.durationMs > 0 ? parent.startMs / root.durationMs * parent.width : 0
                            y: 4
                            width: root.durationMs > 0 ? Math.max(6, (parent.endMs - parent.startMs) / root.durationMs * parent.width) : 0
                            height: parent.height - 8
                            radius: 4
                            color: root.selectedIndex === parent.index ? "#F59E3D" : "#F07818"
                        }

                        MouseArea {
                            x: parent.safeX
                            width: parent.safeW
                            height: parent.height
                            hoverEnabled: true
                            onClicked: root.cutSelected(parent.index)
                            ToolTip.visible: containsMouse
                            ToolTip.text: qsTr("Requested: %1 -> %2").arg(parent.start).arg(parent.end)
                                          + "\n" + qsTr("Safe cut: %1 -> %2").arg(parent.safeStart).arg(parent.safeEnd)
                                          + "\n" + qsTr("Reason: %1").arg(parent.reason) + "\n" + qsTr("Tags: %1").arg(parent.tags)
                        }
                    }
                }

                Rectangle {
                    width: 2
                    height: parent.height + 12
                    y: -6
                    x: root.durationMs > 0 ? Math.max(0, Math.min(parent.width - width, root.videoPositionMs / root.durationMs * parent.width)) : 0
                    color: root.lightMode ? "#0284C7" : "#E0F2FE"
                    visible: root.durationMs > 0
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.shortMode ? 26 : 30
            radius: 9
            color: root.lightMode ? "#EEF4FB" : "#111C30"
            border.color: root.lightMode ? "#CBD5E1" : "#243244"
            visible: root.cutsModel.count > 0 && !root.cardRows

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: root.tableSpacing
                Text { text: "#"; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.indexColumnWidth; Layout.minimumWidth: 0 }
                Text { text: qsTr("Status"); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.statusColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: qsTr("Requested Start"); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: qsTr("Requested End"); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: qsTr("Safe Start"); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: qsTr("Safe End"); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.timeColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Text { text: qsTr("Removed Duration"); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.durationColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
                Item { Layout.fillWidth: true; Layout.minimumWidth: root.extraColumnWidth }
                Text { text: qsTr("Actions"); color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: root.actionsColumnWidth; Layout.minimumWidth: 0; elide: Text.ElideRight }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: root.cutsModel.count > 0
            Layout.preferredHeight: root.cutsModel.count === 0 ? 32 : (root.shortMode ? 82 : 170)
            Layout.minimumHeight: root.cutsModel.count === 0 ? 30 : (root.shortMode ? 70 : (root.narrowMode ? 110 : 130))
            radius: 10
            color: root.lightMode ? "#F8FAFC" : "#050B14"
            border.color: root.lightMode ? "#E2E8F0" : "#142033"
            clip: true

            Text {
                anchors.centerIn: parent
                visible: root.cutsModel.count === 0
                text: qsTr("No cuts added yet. Use Set Start and Set End, then Add Cut.")
                color: root.textMuted
                font.pixelSize: 12
            }

            ListView {
                id: cutsListView
                anchors.fill: parent
                visible: root.cutsModel.count > 0
                model: root.cutsModel
                clip: true
                spacing: 1
                ScrollBar.vertical: AppScrollBar { lightMode: root.lightMode }

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
                        lightMode: root.lightMode
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
            visible: root.showExportControls
            Layout.fillWidth: true
            Layout.preferredHeight: root.showExportControls ? (root.shortMode ? 72 : 92) : 0
            Layout.minimumHeight: root.showExportControls ? (root.shortMode ? 64 : 80) : 0
            outputDir: root.outputDir
            narrowMode: root.narrowMode
            hasSegments: root.cutsModel.count > 0
            lightMode: root.lightMode
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

    Popup {
        id: clearCutsConfirmation

        modal: true
        focus: true
        width: Math.min(390, Math.max(280, root.width - 40))
        height: clearCutsConfirmationContent.implicitHeight + topPadding + bottomPadding
        anchors.centerIn: parent
        padding: 18
        closePolicy: Popup.CloseOnEscape

        background: Rectangle {
            radius: 12
            color: root.lightMode ? "#FFFFFF" : "#0B1324"
            border.color: root.lightMode ? "#CBD5E1" : "#243244"
            border.width: 1
        }

        contentItem: ColumnLayout {
            id: clearCutsConfirmationContent

            spacing: 18

            Text {
                Layout.fillWidth: true
                text: qsTr("Are you sure you want to delete all cuts?")
                color: root.textMain
                font.pixelSize: 14
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item {
                    Layout.fillWidth: true
                }

                AppButton {
                    text: qsTr("No")
                    variant: "secondary"
                    size: "sm"
                    lightMode: root.lightMode
                    Layout.preferredWidth: 84
                    onClicked: clearCutsConfirmation.close()
                }

                AppButton {
                    text: qsTr("Yes")
                    variant: "danger"
                    size: "sm"
                    lightMode: root.lightMode
                    Layout.preferredWidth: 84
                    onClicked: {
                        root.clearCuts()
                        clearCutsConfirmation.close()
                    }
                }
            }
        }
    }
}

