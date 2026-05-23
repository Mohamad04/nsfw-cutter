import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root

    property color textMuted: "#94A3B8"
    property color accent: "#38BDF8"

    spacing: 8

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
