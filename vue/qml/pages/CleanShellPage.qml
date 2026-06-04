pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import "../components"

Item {
    id: root

    signal settingsRequested()

    property bool darkMode: settingsController.theme !== "light"
    property bool lightMode: !root.darkMode
    property color pageBg: root.darkMode ? theme.darkAppBg : theme.lightAppBg
    property color surface: root.darkMode ? theme.darkSurface : theme.lightSurface
    property color videoSurface: root.darkMode ? theme.darkVideoSurface : theme.lightVideoSurface
    property color borderColor: root.darkMode ? theme.darkBorder : theme.lightBorder
    property color textMain: root.darkMode ? theme.darkTextPrimary : theme.lightTextPrimary
    property color textMuted: root.darkMode ? theme.darkTextMuted : theme.lightTextMuted
    property int selectedCutIndex: -1

    AppTheme { id: theme }
    ListModel { id: cutsModel }

    function appendCut(cut) {
        cutsModel.append({
            "start": cut.start || "00:00:00",
            "end": cut.end || "00:00:00",
            "safeStart": cut.safeStart || "",
            "safeEnd": cut.safeEnd || "",
            "requestedStartSeconds": cut.requestedStartSeconds !== undefined ? cut.requestedStartSeconds : "",
            "requestedEndSeconds": cut.requestedEndSeconds !== undefined ? cut.requestedEndSeconds : "",
            "safeStartSeconds": cut.safeStartSeconds !== undefined ? cut.safeStartSeconds : "",
            "safeEndSeconds": cut.safeEndSeconds !== undefined ? cut.safeEndSeconds : "",
            "safeAvailable": cut.safeAvailable === true,
            "previousKeyframeStart": cut.previousKeyframeStart || "",
            "nextKeyframeStart": cut.nextKeyframeStart || "",
            "previousKeyframeEnd": cut.previousKeyframeEnd || "",
            "nextKeyframeEnd": cut.nextKeyframeEnd || "",
            "extraBefore": cut.extraBefore || "0.0s",
            "extraAfter": cut.extraAfter || "0.0s",
            "reason": cut.reason || "Manual removal",
            "tags": cut.tags || "manual",
            "source": cut.source || "Manual",
            "score": cut.score || "--",
            "cutType": cut.cutType || "Remove",
            "status": cut.status || "Pending"
        })
        root.selectedCutIndex = cutsModel.count - 1
    }

    Rectangle {
        anchors.fill: parent
        color: root.pageBg

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            CompactAppHeader {
                Layout.fillWidth: true
                Layout.preferredHeight: 76
                lightMode: root.lightMode
                panelColor: root.surface
                strokeColor: root.borderColor
                textColor: root.textMain
                mutedTextColor: root.textMuted
                accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                onSettingsRequested: root.settingsRequested()
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12

                VideoWorkspace {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    cutsModel: cutsModel
                    lightMode: root.lightMode
                    panelColor: root.surface
                    videoColor: root.darkMode ? "#020617" : "#0F172A"
                    strokeColor: root.borderColor
                    textColor: root.textMain
                    mutedTextColor: root.textMuted
                    accentColor: root.darkMode ? theme.darkAccent : theme.lightAccent
                    onCutAdded: function(cut) { root.appendCut(cut) }
                }

                Rectangle {
                    Layout.preferredWidth: 320
                    Layout.minimumWidth: 260
                    Layout.maximumWidth: 360
                    Layout.fillHeight: true
                    radius: 10
                    color: root.surface
                    border.color: root.borderColor

                    Text {
                        anchors.centerIn: parent
                        text: "Cut list placeholder"
                        color: root.textMain
                        font.pixelSize: 16
                        font.bold: true
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                radius: 10
                color: root.surface
                border.color: root.borderColor

                Text {
                    anchors.centerIn: parent
                    text: "Export/actions bar placeholder"
                    color: root.textMuted
                    font.pixelSize: 16
                }
            }
        }
    }
}
