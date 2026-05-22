import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Panel {
    id: root

    property bool compactMode: false
    property bool shortMode: false
    property color panelTone: "#0B1324"
    property color textMain: "#F8FAFC"
    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"

    signal cutAdded(var cut)

    implicitHeight: content.implicitHeight + (root.compactMode ? 24 : 32)
    panelColor: root.panelTone
    strokeColor: "#21324D"

    function setStartTime(timeText) {
        startInput.text = timeText
    }

    function setEndTime(timeText) {
        endInput.text = timeText
    }

    function applyRecommendation(startTime, endTime, reason, tags) {
        startInput.text = startTime
        endInput.text = endTime
        reasonInput.text = reason
        tagsInput.text = tags
    }

    function clearEditor() {
        startInput.text = "00:00:00"
        endInput.text = "00:00:00"
        reasonInput.text = ""
        tagsInput.text = ""
    }

    function parseTimeToMs(value) {
        var parts = value.trim().split(":")
        if (parts.length !== 3) return -1

        var hours = Number(parts[0])
        var minutes = Number(parts[1])
        var seconds = Number(parts[2])
        if (!Number.isInteger(hours) || !Number.isInteger(minutes) || !Number.isInteger(seconds)) return -1
        if (hours < 0 || minutes < 0 || minutes > 59 || seconds < 0 || seconds > 59) return -1
        return ((hours * 3600) + (minutes * 60) + seconds) * 1000
    }

    function validationMessage() {
        var startMs = parseTimeToMs(startInput.text)
        var endMs = parseTimeToMs(endInput.text)

        if (startMs < 0 || endMs < 0) return "Use HH:MM:SS for start and end."
        if (startMs === 0 && endMs === 0) return ""
        if (startMs >= endMs) return "Start must be before end."
        return ""
    }

    function canAddCut() {
        var startMs = parseTimeToMs(startInput.text)
        var endMs = parseTimeToMs(endInput.text)
        return startMs >= 0 && endMs >= 0 && startMs < endMs
    }

    function addCut(source, score) {
        if (!canAddCut()) return
        root.cutAdded({
            "start": startInput.text,
            "end": endInput.text,
            "reason": reasonInput.text.length > 0 ? reasonInput.text : "Manual cut",
            "tags": tagsInput.text.length > 0 ? tagsInput.text : "manual",
            "source": source,
            "score": score
        })
    }

    ColumnLayout {
        id: content
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: root.compactMode ? 12 : 16
        spacing: root.compactMode ? 8 : 10

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    text: "FAST CUT"
                    color: root.accent
                    font.pixelSize: 15
                    font.bold: true
                    font.letterSpacing: 0.6
                }

                Text {
                    text: "Mark time, type context, add"
                    color: root.textMuted
                    font.pixelSize: 12
                }
            }

            Rectangle {
                Layout.preferredHeight: 28
                Layout.preferredWidth: 78
                radius: 14
                color: "#12223A"
                border.color: "#284566"

                Text {
                    anchors.centerIn: parent
                    text: "Manual"
                    color: root.textMuted
                    font.pixelSize: 12
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#1F2F4A" }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "Start"; color: root.textMain; font.pixelSize: 12; Layout.preferredWidth: 40 }
            AppTextField { id: startInput; Layout.fillWidth: true; placeholderText: "00:00:00"; text: "00:00:00" }
            AppButton { text: "Reset"; variant: "ghost"; size: "sm"; Layout.preferredWidth: 58; onClicked: startInput.text = "00:00:00" }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "End"; color: root.textMain; font.pixelSize: 12; Layout.preferredWidth: 40 }
            AppTextField {
                id: endInput
                Layout.fillWidth: true
                placeholderText: "00:00:00"
                text: "00:00:00"
                onAccepted: root.addCut("Manual", "--")
            }
            AppButton { text: "Reset"; variant: "ghost"; size: "sm"; Layout.preferredWidth: 58; onClicked: endInput.text = "00:00:00" }
        }

        Text { text: "Reason"; color: root.textMain; font.pixelSize: 12 }

        AppTextArea {
            id: reasonInput
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(root.shortMode ? 92 : 128, Math.max(38, contentHeight + topPadding + bottomPadding))
            placeholderText: "Reason for this cut..."
        }

        Text { text: "Tags"; color: root.textMain; font.pixelSize: 12 }

        AppTextField {
            id: tagsInput
            Layout.fillWidth: true
            placeholderText: "kissing, romance, nsfw"
            onAccepted: root.addCut("Manual", "--")
        }

        Text {
            Layout.fillWidth: true
            text: root.validationMessage()
            color: "#FCA5A5"
            font.pixelSize: 12
            visible: text.length > 0
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            AppButton {
                text: "+ Add Cut"
                variant: "primary"
                size: "lg"
                Layout.fillWidth: true
                enabled: root.canAddCut()
                onClicked: root.addCut("Manual", "--")
            }

            AppButton {
                text: "Reset"
                variant: "danger"
                size: "md"
                Layout.preferredWidth: 80
                onClicked: root.clearEditor()
            }
        }

        AppButton {
            text: appController.backendPreparationBusy ? "Preparing..." : "Prepare Export Job"
            variant: "success"
            size: "lg"
            Layout.fillWidth: true
            enabled: !appController.backendPreparationBusy && appController.selectedVideoPath.length > 0
            onClicked: appController.prepareExportJob(appController.selectedVideoPath, "")
        }

        ProgressBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 8
            visible: appController.backendPreparationBusy
            from: 0
            to: 1
            value: appController.backendPreparationProgress / 100

            background: Rectangle { radius: 4; color: "#111827" }
            contentItem: Item {
                Rectangle {
                    width: parent.width * appController.backendPreparationProgress / 100
                    height: parent.height
                    radius: 4
                    color: root.accent
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: appController.backendPreparationStatus
            color: appController.backendPreparationStatus.indexOf("failed") >= 0 ? "#FCA5A5" : root.textMuted
            font.pixelSize: 12
            elide: Text.ElideRight
            visible: appController.backendPreparationBusy || appController.backendPreparationStatus !== "No backend preparation running"
        }

        Text {
            Layout.fillWidth: true
            text: appController.currentExportJobId.length > 0 ? "Job: " + appController.currentExportJobId : ""
            color: "#86EFAC"
            font.pixelSize: 11
            elide: Text.ElideRight
            visible: appController.currentExportJobId.length > 0
        }
    }
}
