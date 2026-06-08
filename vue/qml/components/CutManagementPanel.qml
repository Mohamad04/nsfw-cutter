pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "cutManagementPanel"

    required property var cutsModel
    property int selectedIndex: -1
    property real durationMs: 0
    property bool lightMode: false
    property color panelColor: "#0C1625"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property color requestedColor: root.lightMode ? "#D97706" : "#F59E3D"
    property color safeColor: root.lightMode ? "#15803D" : "#86EFAC"

    signal cutSelected(int index)

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

    AppTheme { id: theme }

    function selectedCut() {
        if (root.selectedIndex < 0 || root.selectedIndex >= root.cutsModel.count) return null
        return root.cutsModel.get(root.selectedIndex)
    }

    function parseTimeSeconds(value) {
        var parts = String(value || "").trim().split(":")
        if (parts.length !== 3) return NaN
        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var seconds = Number(parts[2])
        if (!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(seconds)) return NaN
        return hours * 3600 + minutes * 60 + seconds
    }

    function numericSeconds(cut, secondsKey, timeKey) {
        if (!cut) return NaN
        var value = cut[secondsKey]
        if (value !== undefined && value !== null && value !== "") {
            var numeric = Number(value)
            if (Number.isFinite(numeric)) return numeric
        }
        return root.parseTimeSeconds(cut[timeKey])
    }

    function requestedStartSeconds(cut) {
        return root.numericSeconds(cut, "requestedStartSeconds", "start")
    }

    function requestedEndSeconds(cut) {
        return root.numericSeconds(cut, "requestedEndSeconds", "end")
    }

    function safeStartSeconds(cut) {
        return root.numericSeconds(cut, "safeStartSeconds", "safeStart")
    }

    function safeEndSeconds(cut) {
        return root.numericSeconds(cut, "safeEndSeconds", "safeEnd")
    }

    function requestedDurationSeconds(cut) {
        var start = root.requestedStartSeconds(cut)
        var end = root.requestedEndSeconds(cut)
        return Number.isFinite(start) && Number.isFinite(end) && end > start ? end - start : 0
    }

    function safeDurationSeconds(cut) {
        var start = root.safeStartSeconds(cut)
        var end = root.safeEndSeconds(cut)
        return Number.isFinite(start) && Number.isFinite(end) && end > start ? end - start : root.requestedDurationSeconds(cut)
    }

    function isAdjusted(cut) {
        if (!cut) return false
        var requestedStart = root.requestedStartSeconds(cut)
        var requestedEnd = root.requestedEndSeconds(cut)
        var safeStart = root.safeStartSeconds(cut)
        var safeEnd = root.safeEndSeconds(cut)
        if (!Number.isFinite(requestedStart) || !Number.isFinite(requestedEnd)) return false
        if (!Number.isFinite(safeStart) || !Number.isFinite(safeEnd)) return false
        return Math.abs(safeStart - requestedStart) > 0.001 || Math.abs(safeEnd - requestedEnd) > 0.001
    }

    function statusText(cut) {
        return root.isAdjusted(cut) ? "Adjusted" : "Safe"
    }

    function totalRemovedSeconds() {
        var total = 0
        for (var index = 0; index < root.cutsModel.count; index += 1) {
            total += root.safeDurationSeconds(root.cutsModel.get(index))
        }
        return total
    }

    function formatHms(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
        var totalSeconds = Math.round(seconds)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var secs = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(secs)
    }

    function formatCompact(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
        var totalSeconds = Math.round(seconds)
        var hours = Math.floor(totalSeconds / 3600)
        var minutes = Math.floor((totalSeconds % 3600) / 60)
        var secs = totalSeconds % 60
        function pad(value) { return value < 10 ? "0" + value : "" + value }
        if (hours > 0) return pad(hours) + ":" + pad(minutes) + ":" + pad(secs)
        return pad(minutes) + ":" + pad(secs)
    }

    function formatSignedDelta(seconds) {
        if (!Number.isFinite(seconds) || Math.abs(seconds) < 0.001) return "00:00"
        return (seconds > 0 ? "+" : "-") + root.formatCompact(Math.abs(seconds))
    }

    function displayTime(cut, timeKey, secondsKey) {
        if (!cut) return "--"
        var text = cut[timeKey]
        if (text !== undefined && text !== null && String(text).length > 0) return String(text)
        var seconds = cut[secondsKey]
        return Number.isFinite(Number(seconds)) ? root.formatHms(Number(seconds)) : "--"
    }

    function videoAfterCutsText() {
        if (!Number.isFinite(root.durationMs) || root.durationMs <= 0) return "--:--:--"
        var remaining = Math.max(0, root.durationMs / 1000 - root.totalRemovedSeconds())
        return root.formatHms(remaining)
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

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            spacing: 3

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                VectorIcon {
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                    name: "list"
                    iconColor: root.accentColor
                }

                Text {
                    Layout.fillWidth: true
                    text: "Cut List"
                    color: root.textColor
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
            }

            Text {
                Layout.fillWidth: true
                text: root.cutsModel.count + (root.cutsModel.count === 1 ? " cut" : " cuts")
                      + "  •  Total removed: " + root.formatHms(root.totalRemovedSeconds())
                color: root.mutedTextColor
                font.pixelSize: 12
                elide: Text.ElideRight
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 170
            radius: 12
            color: root.lightMode ? "#F8FAFC" : "#050B14"
            border.color: root.lightMode ? "#E2E8F0" : "#17263E"
            clip: true

            Column {
                anchors.centerIn: parent
                width: parent.width - 32
                spacing: 11
                visible: root.cutsModel.count === 0

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 48
                    height: 48
                    radius: 18
                    color: root.lightMode ? "#EFF6FF" : "#0B1D33"
                    border.color: root.lightMode ? "#BFDBFE" : "#213A5E"

                    VectorIcon {
                        anchors.centerIn: parent
                        width: 24
                        height: 24
                        name: "scissors"
                        iconColor: root.lightMode ? "#2563EB" : "#5AA4FF"
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "No cuts added yet"
                    color: root.textColor
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    text: "Use Set Start and Set End below the video,\nthen select Add Cut."
                    color: root.mutedTextColor
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 1.2
                }
            }

            ListView {
                id: cutListView

                anchors.fill: parent
                anchors.margins: 8
                visible: root.cutsModel.count > 0
                model: root.cutsModel
                spacing: 7
                clip: true
                ScrollBar.vertical: AppScrollBar { lightMode: root.lightMode }

                delegate: Rectangle {
                    id: rowRoot

                    required property int index
                    required property var start
                    required property var end
                    required property var safeStart
                    required property var safeEnd
                    required property var requestedStartSeconds
                    required property var requestedEndSeconds
                    required property var safeStartSeconds
                    required property var safeEndSeconds

                    readonly property bool selected: root.selectedIndex === rowRoot.index
                    readonly property var rowCut: root.cutsModel.get(rowRoot.index)
                    readonly property string rowStatus: root.statusText(rowCut)
                    readonly property real rowDuration: root.safeDurationSeconds(rowCut)

                    width: cutListView.width - 4
                    height: 72
                    radius: 10
                    color: selected
                        ? (root.lightMode ? "#EFF6FF" : "#102A43")
                        : (rowMouse.containsMouse ? (root.lightMode ? "#FFFFFF" : "#0B1324") : "transparent")
                    border.color: selected
                        ? root.accentColor
                        : (rowMouse.containsMouse ? (root.lightMode ? "#CBD5E1" : "#243244") : "transparent")
                    border.width: selected || rowMouse.containsMouse ? 1 : 0

                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        color: root.accentColor
                        opacity: rowRoot.selected ? 0.08 : 0
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 3
                        radius: 2
                        color: root.accentColor
                        visible: rowRoot.selected
                    }

                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.cutSelected(rowRoot.index)
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 8
                        spacing: 8

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 5

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: "Cut " + (rowRoot.index + 1)
                                    color: root.textColor
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }

                                Rectangle {
                                    Layout.preferredWidth: rowStatusText.implicitWidth + 34
                                    Layout.preferredHeight: 22
                                    radius: 11
                                    color: rowRoot.rowStatus === "Adjusted"
                                        ? (root.lightMode ? "#FEF3C7" : "#2A160B")
                                        : (root.lightMode ? "#DCFCE7" : "#103D22")
                                    border.color: rowRoot.rowStatus === "Adjusted"
                                        ? (root.lightMode ? "#F59E0B" : "#F59E3D")
                                        : (root.lightMode ? "#22C55E" : "#22B454")

                                    RowLayout {
                                        anchors.centerIn: parent
                                        spacing: 4

                                        VectorIcon {
                                            Layout.preferredWidth: 12
                                            Layout.preferredHeight: 12
                                            name: rowRoot.rowStatus === "Adjusted" ? "warning" : "shield"
                                            iconColor: rowRoot.rowStatus === "Adjusted"
                                                ? (root.lightMode ? "#A16207" : "#FDE68A")
                                                : root.safeColor
                                        }

                                        Text {
                                            id: rowStatusText
                                            text: rowRoot.rowStatus
                                            color: rowRoot.rowStatus === "Adjusted"
                                                ? (root.lightMode ? "#A16207" : "#FDE68A")
                                                : root.safeColor
                                            font.pixelSize: 10
                                            font.weight: Font.DemiBold
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: rowRoot.start + "  →  " + rowRoot.end
                                    color: root.mutedTextColor
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }

                                Text {
                                    text: root.formatCompact(rowRoot.rowDuration)
                                    color: root.textColor
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignRight
                                }
                            }
                        }

                        AppButton {
                            text: ""
                            iconName: "trash"
                            variant: "ghost"
                            size: "sm"
                            lightMode: root.lightMode
                            Layout.preferredWidth: 38
                            Layout.preferredHeight: 32
                            ToolTip.visible: hovered
                            ToolTip.text: "Delete cut"
                            onClicked: root.deleteCut(rowRoot.index)
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.cutsModel.count > 0 ? 230 : 86
            radius: 12
            color: root.lightMode ? "#F8FAFC" : "#07101D"
            border.color: root.lightMode ? "#E2E8F0" : "#17263E"

            Text {
                anchors.centerIn: parent
                width: parent.width - 28
                visible: root.cutsModel.count > 0 && root.selectedCut() === null
                text: "Select a cut to view safe-adjustment details."
                color: root.mutedTextColor
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 9
                visible: root.selectedCut() !== null

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 26
                    spacing: 8

                    Text {
                        Layout.fillWidth: true
                        text: "Cut " + (root.selectedIndex + 1) + " Details"
                        color: root.textColor
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Rectangle {
                        Layout.preferredWidth: detailStatusText.implicitWidth + 16
                        Layout.preferredHeight: 22
                        radius: 11
                        color: root.isAdjusted(root.selectedCut())
                            ? (root.lightMode ? "#FEF3C7" : "#2A160B")
                            : (root.lightMode ? "#DCFCE7" : "#103D22")
                        border.color: root.isAdjusted(root.selectedCut())
                            ? (root.lightMode ? "#F59E0B" : "#F59E3D")
                            : (root.lightMode ? "#22C55E" : "#22B454")

                        RowLayout {
                            anchors.centerIn: parent
                            spacing: 4

                            VectorIcon {
                                Layout.preferredWidth: 12
                                Layout.preferredHeight: 12
                                name: root.isAdjusted(root.selectedCut()) ? "warning" : "shield"
                                iconColor: root.isAdjusted(root.selectedCut())
                                    ? (root.lightMode ? "#A16207" : "#FDE68A")
                                    : root.safeColor
                            }

                            Text {
                                id: detailStatusText
                                text: root.statusText(root.selectedCut())
                                color: root.isAdjusted(root.selectedCut())
                                    ? (root.lightMode ? "#A16207" : "#FDE68A")
                                    : root.safeColor
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 4
                    columnSpacing: 8
                    rowSpacing: 7

                    Text { text: ""; Layout.preferredWidth: 54 }
                    Text { text: "Requested"; color: root.requestedColor; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                    Text { text: "Safe Adjusted"; color: root.safeColor; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                    Text { text: "Delta"; color: root.mutedTextColor; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.preferredWidth: 54; horizontalAlignment: Text.AlignRight }

                    Text { text: "Start"; color: root.mutedTextColor; font.pixelSize: 11 }
                    Text { text: root.displayTime(root.selectedCut(), "start", "requestedStartSeconds"); color: root.requestedColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text { text: root.displayTime(root.selectedCut(), "safeStart", "safeStartSeconds"); color: root.safeColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text { text: root.formatSignedDelta(root.safeStartSeconds(root.selectedCut()) - root.requestedStartSeconds(root.selectedCut())); color: root.textColor; font.pixelSize: 11; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 54 }

                    Text { text: "End"; color: root.mutedTextColor; font.pixelSize: 11 }
                    Text { text: root.displayTime(root.selectedCut(), "end", "requestedEndSeconds"); color: root.requestedColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text { text: root.displayTime(root.selectedCut(), "safeEnd", "safeEndSeconds"); color: root.safeColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text { text: root.formatSignedDelta(root.safeEndSeconds(root.selectedCut()) - root.requestedEndSeconds(root.selectedCut())); color: root.textColor; font.pixelSize: 11; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 54 }

                    Text { text: "Duration"; color: root.mutedTextColor; font.pixelSize: 11 }
                    Text { text: root.formatCompact(root.requestedDurationSeconds(root.selectedCut())); color: root.requestedColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text { text: root.formatCompact(root.safeDurationSeconds(root.selectedCut())); color: root.safeColor; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text { text: root.formatSignedDelta(root.safeDurationSeconds(root.selectedCut()) - root.requestedDurationSeconds(root.selectedCut())); color: root.textColor; font.pixelSize: 11; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 54 }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Safe adjustments align cuts to nearby keyframes for stream-copy export."
                    color: root.mutedTextColor
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 74
            radius: 12
            color: root.lightMode ? "#F8FAFC" : "#050B14"
            border.color: root.lightMode ? "#E2E8F0" : "#17263E"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: "Total Removed"
                        color: root.mutedTextColor
                        font.pixelSize: 12
                    }
                    Text {
                        text: root.formatHms(root.totalRemovedSeconds())
                        color: root.textColor
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: "Video After Cuts"
                        color: root.mutedTextColor
                        font.pixelSize: 12
                    }
                    Text {
                        text: root.videoAfterCutsText()
                        color: root.durationMs > 0 ? root.textColor : root.mutedTextColor
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
    }
}
