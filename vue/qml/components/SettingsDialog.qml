import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root

    modal: true
    focus: true
    width: Math.min(560, parent ? parent.width - 32 : 560)
    height: Math.min(720, parent ? parent.height - 32 : 720)
    anchors.centerIn: parent
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    property bool darkMode: settingsController.theme !== "light"
    property bool lightMode: !root.darkMode
    property color dialogBg: darkMode ? "#0B1324" : "#FFFFFF"
    property color sectionBg: darkMode ? "#08111F" : "#F8FAFC"
    property color stroke: darkMode ? "#243244" : "#CBD5E1"
    property color textMain: darkMode ? "#F8FAFC" : "#0F172A"
    property color textMuted: darkMode ? "#94A3B8" : "#475569"
    property string lastVideoPath: ""
    property var recentVideos: []

    function modelIndex(model, value) {
        for (var index = 0; index < model.length; index += 1) {
            if (model[index] === value) return index
        }
        return 0
    }

    function openWithCurrentSettings() {
        themeCombo.currentIndex = modelIndex(themeCombo.model, settingsController.getTheme())
        languageCombo.currentIndex = modelIndex(languageCombo.model, settingsController.getLanguage())
        providerCombo.currentIndex = modelIndex(providerCombo.model, settingsController.getAIProvider())
        exportFolderField.text = settingsController.getExportDir()
        exportModeCombo.currentIndex = modelIndex(exportModeCombo.model, settingsController.getLastExportMode())
        promptArea.text = settingsController.getUserPrompt()
        modelNameField.text = settingsController.getAIModelName()
        gpuCheckbox.checked = settingsController.getEnableGpu()
        batchSizeSpin.value = settingsController.getBatchSize()
        confidenceSlider.value = settingsController.getConfidenceThreshold()
        lastVideoPath = settingsController.getLastVideoPath()
        recentVideos = settingsController.getRecentVideos()
        open()
    }

    background: Rectangle {
        radius: 12
        color: root.dialogBg
        border.color: root.stroke
        border.width: 1
    }

    contentItem: ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12

        RowLayout {
            Layout.fillWidth: true

            Text {
                text: "Settings"
                color: root.textMain
                font.pixelSize: 22
                font.bold: true
            }

            Item { Layout.fillWidth: true }

            AppButton {
                text: "X"
                variant: "ghost"
                size: "sm"
                lightMode: root.lightMode
                Layout.preferredWidth: 42
                onClicked: root.close()
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: Math.max(0, parent.width - 14)
                spacing: 12

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: preferencesContent.implicitHeight + 24
                    radius: 10
                    color: root.sectionBg
                    border.color: root.stroke

                    ColumnLayout {
                        id: preferencesContent
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Text { text: "User Preferences"; color: root.textMain; font.pixelSize: 14; font.bold: true }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: "Theme"; color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox { id: themeCombo; Layout.fillWidth: true; model: ["dark", "light", "system"] }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: "Language"; color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox { id: languageCombo; Layout.fillWidth: true; model: ["en", "fr"] }
                        }

                        Text { text: "Export folder"; color: root.textMuted; font.pixelSize: 12 }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            AppTextField {
                                id: exportFolderField
                                Layout.fillWidth: true
                                lightMode: root.lightMode
                                placeholderText: "Leave blank for project defaults"
                            }
                            AppButton {
                                text: "Browse"
                                variant: "secondary"
                                size: "sm"
                                lightMode: root.lightMode
                                Layout.preferredWidth: 72
                                onClicked: {
                                    var folder = settingsController.chooseExportDir()
                                    if (folder.length > 0) exportFolderField.text = folder
                                }
                            }
                            AppButton {
                                text: "Clear"
                                variant: "ghost"
                                size: "sm"
                                lightMode: root.lightMode
                                Layout.preferredWidth: 62
                                onClicked: exportFolderField.text = ""
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: "Export mode"; color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox {
                                id: exportModeCombo
                                Layout.fillWidth: true
                                model: ["remove_intervals", "export_clips_separate", "export_clips_merged"]
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: videoContent.implicitHeight + 24
                    radius: 10
                    color: root.sectionBg
                    border.color: root.stroke

                    ColumnLayout {
                        id: videoContent
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 6

                        Text { text: "Video Preferences"; color: root.textMain; font.pixelSize: 14; font.bold: true }
                        Text { text: "Last opened video"; color: root.textMuted; font.pixelSize: 12 }
                        Text {
                            Layout.fillWidth: true
                            text: root.lastVideoPath.length > 0 ? root.lastVideoPath : "No video remembered yet"
                            color: root.textMain
                            font.pixelSize: 12
                            elide: Text.ElideMiddle
                        }
                        Text { text: "Recent videos"; color: root.textMuted; font.pixelSize: 12 }
                        Repeater {
                            model: root.recentVideos.length > 0 ? root.recentVideos : ["No recent videos"]
                            Text {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData
                                color: root.recentVideos.length > 0 ? root.textMain : root.textMuted
                                font.pixelSize: 11
                                elide: Text.ElideMiddle
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 176
                    radius: 10
                    color: root.sectionBg
                    border.color: root.stroke

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Text { text: "Prompt"; color: root.textMain; font.pixelSize: 14; font.bold: true }

                        AppTextArea {
                            id: promptArea
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            lightMode: root.lightMode
                            placeholderText: "Write your custom AI prompt here..."
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: aiContent.implicitHeight + 24
                    radius: 10
                    color: root.sectionBg
                    border.color: root.stroke

                    ColumnLayout {
                        id: aiContent
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Text { text: "AI Settings"; color: root.textMain; font.pixelSize: 14; font.bold: true }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: "Provider"; color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox { id: providerCombo; Layout.fillWidth: true; model: ["local", "openai", "custom"] }
                        }

                        AppTextField {
                            id: modelNameField
                            Layout.fillWidth: true
                            lightMode: root.lightMode
                            placeholderText: "Model name"
                        }

                        CheckBox {
                            id: gpuCheckbox
                            text: "Enable GPU"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: "Batch size"; color: root.textMuted; Layout.preferredWidth: 84 }
                            SpinBox { id: batchSizeSpin; from: 1; to: 64; value: 8 }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text { text: "Confidence threshold " + confidenceSlider.value.toFixed(2); color: root.textMuted }
                            Slider { id: confidenceSlider; Layout.fillWidth: true; from: 0; to: 1; value: 0.5 }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Settings file: " + settingsController.getSettingsJsonPath()
                    color: root.textMuted
                    font.pixelSize: 10
                    elide: Text.ElideMiddle
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Item { Layout.fillWidth: true }

            AppButton {
                text: "Cancel"
                variant: "ghost"
                lightMode: root.lightMode
                onClicked: root.close()
            }

            AppButton {
                text: "Save"
                variant: "primary"
                lightMode: root.lightMode
                onClicked: {
                    settingsController.setTheme(themeCombo.currentText)
                    settingsController.setLanguage(languageCombo.currentText)
                    settingsController.setExportDir(exportFolderField.text)
                    settingsController.setLastExportMode(exportModeCombo.currentText)
                    settingsController.setUserPrompt(promptArea.text)
                    settingsController.setAIProvider(providerCombo.currentText)
                    settingsController.setAIModelName(modelNameField.text)
                    settingsController.setEnableGpu(gpuCheckbox.checked)
                    settingsController.setBatchSize(batchSizeSpin.value)
                    settingsController.setConfidenceThreshold(confidenceSlider.value)
                    root.close()
                }
            }
        }
    }
}
