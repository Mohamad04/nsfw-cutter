import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

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
    readonly property var themeOptions: [
        { "code": "dark", "name": qsTr("Dark") },
        { "code": "light", "name": qsTr("Light") },
        { "code": "system", "name": qsTr("System") }
    ]
    readonly property var exportModeOptions: [
        { "code": "remove_intervals", "name": qsTr("Remove intervals") },
        { "code": "export_clips_separate", "name": qsTr("Export clips separately") },
        { "code": "export_clips_merged", "name": qsTr("Export merged clips") }
    ]
    readonly property var providerOptions: [
        { "code": "local", "name": qsTr("Local") },
        { "code": "openai", "name": qsTr("OpenAI") },
        { "code": "custom", "name": qsTr("Custom") }
    ]

    function modelIndex(model, value, roleName) {
        if (!model) return 0

        var count = model.length !== undefined ? model.length : model.count
        for (var index = 0; index < count; index += 1) {
            var item = model.get ? model.get(index) : model[index]
            var itemValue = roleName && item && item[roleName] !== undefined ? item[roleName] : item
            if (itemValue === value) return index
        }
        return 0
    }

    function openWithCurrentSettings() {
        themeCombo.currentIndex = modelIndex(themeCombo.model, settingsController.getTheme(), "code")
        languageCombo.currentIndex = modelIndex(languageCombo.model, settingsController.getLanguage(), "code")
        providerCombo.currentIndex = modelIndex(providerCombo.model, settingsController.getAIProvider(), "code")
        exportFolderField.text = settingsController.getExportDir()
        exportModeCombo.currentIndex = modelIndex(exportModeCombo.model, settingsController.getLastExportMode(), "code")
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
                text: qsTr("Settings")
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

                        Text { text: qsTr("User Preferences"); color: root.textMain; font.pixelSize: 14; font.bold: true }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: qsTr("Theme"); color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox {
                                id: themeCombo
                                Layout.fillWidth: true
                                model: root.themeOptions
                                textRole: "name"
                                valueRole: "code"
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: qsTr("Language"); color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox {
                                id: languageCombo
                                Layout.fillWidth: true
                                model: translationService.availableLanguages
                                textRole: "name"
                                valueRole: "code"
                            }
                        }

                        Text { text: qsTr("Export folder"); color: root.textMuted; font.pixelSize: 12 }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            AppTextField {
                                id: exportFolderField
                                Layout.fillWidth: true
                                lightMode: root.lightMode
                                placeholderText: qsTr("Leave blank for project defaults")
                            }
                            AppButton {
                                text: qsTr("Browse")
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
                                text: qsTr("Clear")
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
                            Text { text: qsTr("Export mode"); color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox {
                                id: exportModeCombo
                                Layout.fillWidth: true
                                model: root.exportModeOptions
                                textRole: "name"
                                valueRole: "code"
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

                        Text { text: qsTr("Video Preferences"); color: root.textMain; font.pixelSize: 14; font.bold: true }
                        Text { text: qsTr("Last opened video"); color: root.textMuted; font.pixelSize: 12 }
                        Text {
                            Layout.fillWidth: true
                            text: root.lastVideoPath.length > 0 ? root.lastVideoPath : qsTr("No video remembered yet")
                            color: root.textMain
                            font.pixelSize: 12
                            elide: Text.ElideMiddle
                        }
                        Text { text: qsTr("Recent videos"); color: root.textMuted; font.pixelSize: 12 }
                        Repeater {
                            model: root.recentVideos.length > 0 ? root.recentVideos : [qsTr("No recent videos")]
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

                        Text { text: qsTr("Prompt"); color: root.textMain; font.pixelSize: 14; font.bold: true }

                        AppTextArea {
                            id: promptArea
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            lightMode: root.lightMode
                            placeholderText: qsTr("Write your custom AI prompt here...")
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

                        Text { text: qsTr("AI Settings"); color: root.textMain; font.pixelSize: 14; font.bold: true }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: qsTr("Provider"); color: root.textMuted; Layout.preferredWidth: 84 }
                            ComboBox {
                                id: providerCombo
                                Layout.fillWidth: true
                                model: root.providerOptions
                                textRole: "name"
                                valueRole: "code"
                            }
                        }

                        AppTextField {
                            id: modelNameField
                            Layout.fillWidth: true
                            lightMode: root.lightMode
                            placeholderText: qsTr("Model name")
                        }

                        CheckBox {
                            id: gpuCheckbox
                            text: qsTr("Enable GPU")
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text { text: qsTr("Batch size"); color: root.textMuted; Layout.preferredWidth: 84 }
                            SpinBox { id: batchSizeSpin; from: 1; to: 64; value: 8 }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text { text: qsTr("Confidence threshold") + " " + confidenceSlider.value.toFixed(2); color: root.textMuted }
                            Slider { id: confidenceSlider; Layout.fillWidth: true; from: 0; to: 1; value: 0.5 }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: qsTr("Settings file:") + " " + settingsController.getSettingsJsonPath()
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
                text: qsTr("Cancel")
                variant: "ghost"
                lightMode: root.lightMode
                onClicked: root.close()
            }

            AppButton {
                text: qsTr("Save")
                variant: "primary"
                lightMode: root.lightMode
                onClicked: {
                    settingsController.setTheme(themeCombo.currentValue)
                    settingsController.setLanguage(languageCombo.currentValue)
                    settingsController.setExportDir(exportFolderField.text)
                    settingsController.setLastExportMode(exportModeCombo.currentValue)
                    settingsController.setUserPrompt(promptArea.text)
                    settingsController.setAIProvider(providerCombo.currentValue)
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

