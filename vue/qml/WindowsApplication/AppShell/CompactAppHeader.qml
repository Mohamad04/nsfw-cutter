pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../CutEditor"
import "../CutList"
import "../Discovery"
import "../Settings"
import "../Shared"
import "../VideoPlayer"

Item {
    id: root
    objectName: "compactAppHeader"

    property bool lightMode: false
    property url appIconSource: Qt.resolvedUrl("../../../../assets/icons/app.png")
    property color panelColor: "#0C1625"
    property color strokeColor: "#223247"
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    readonly property color elevatedPanel: root.lightMode ? "#FFFFFF" : "#06101D"
    readonly property color elevatedBorder: root.lightMode ? "#CBD5E1" : "#2B4260"

    signal settingsRequested()
    signal aiPickAcceptRequested(string suggestionId, string startTime, string endTime, string confidence, string reason)
    signal aiPickRejectRequested(string suggestionId)

    implicitHeight: 76

    AppTheme { id: theme }

    function selectedSubtitleOption() {
        var options = appController.analysisSubtitleOptions
        for (var index = 0; index < options.length; index += 1) {
            if (options[index].selected) return options[index]
        }
        return null
    }

    function selectableSubtitleCount() {
        var options = appController.analysisSubtitleOptions
        var count = 0
        for (var index = 0; index < options.length; index += 1) {
            if (options[index].source !== "off" && options[index].enabled) count += 1
        }
        return count
    }

    function subtitleName(option) {
        if (!option) return ""
        if (option.languageName) return option.languageName
        if (option.label) {
            var label = String(option.label).split(" - ")[0].split(" · ")[0]
            return label.toLowerCase().indexOf(".srt") >= 0 ? "" : label
        }
        return ""
    }

    function subtitleButtonLabel() {
        if (appController.subtitleDetectionState === "loading") return qsTr("Detecting subtitles")

        var selected = root.selectedSubtitleOption()
        if (selected && selected.source === "off") return qsTr("Select subtitle")

        var name = root.subtitleName(selected)
        if (name.length > 0) return qsTr("Subtitles: %1").arg(name)

        return qsTr("Select subtitle")
    }

    function formatLabel() {
        var path = appController.selectedVideoPath
        var dotIndex = String(path).lastIndexOf(".")
        if (dotIndex < 0 || dotIndex >= path.length - 1) return qsTr("Video")
        return String(path).substring(dotIndex + 1).toUpperCase()
    }

    function mediaDetailLabel() {
        if (appController.selectedVideoPath.length === 0) return qsTr("Select a video to begin")
        var parts = []
        var format = root.formatLabel()
        if (format.length > 0) parts.push(format)
        parts.push(qsTr("Stream copy"))
        return parts.join("   •   ")
    }

    function toggleTheme() {
        settingsController.setTheme(root.lightMode ? "dark" : "light")
    }

    function fileNameFromPath(pathValue) {
        var normalized = String(pathValue || "").replace(/\\/g, "/")
        var slashIndex = normalized.lastIndexOf("/")
        return slashIndex >= 0 ? normalized.substring(slashIndex + 1) : normalized
    }

    function recentDisplayName(recentVideo) {
        if (!recentVideo) return ""
        if (recentVideo.name && String(recentVideo.name).length > 0) return String(recentVideo.name)
        if (recentVideo["name"] && String(recentVideo["name"]).length > 0) return String(recentVideo["name"])

        var path = root.recentDisplayPath(recentVideo)
        return path.length > 0 ? root.fileNameFromPath(path) : ""
    }

    function recentDisplayPath(recentVideo) {
        if (!recentVideo) return ""
        if (recentVideo.path && String(recentVideo.path).length > 0) return String(recentVideo.path)
        if (recentVideo["path"] && String(recentVideo["path"]).length > 0) return String(recentVideo["path"])
        return typeof recentVideo === "string" ? recentVideo : ""
    }

    function markAiPickAdded(suggestionId) {
        for (var index = 0; index < aiPicksModel.count; index += 1) {
            var pick = aiPicksModel.get(index)
            if (pick.suggestionId !== suggestionId) continue
            aiPicksModel.setProperty(index, "added", true)
            aiPicksModel.setProperty(index, "selected", false)
            return
        }
    }

    function normalizedAiTime(value) {
        return String(value || "").trim().split(".")[0]
    }

    function syncAiPickAddedState(cutsModel) {
        for (var pickIndex = 0; pickIndex < aiPicksModel.count; pickIndex += 1) {
            var pick = aiPicksModel.get(pickIndex)
            var added = false

            for (var cutIndex = 0; cutIndex < cutsModel.count; cutIndex += 1) {
                var cut = cutsModel.get(cutIndex)
                if (String(cut.source || "") !== "AI") continue

                if (root.normalizedAiTime(cut.start) === root.normalizedAiTime(pick.start)
                        && root.normalizedAiTime(cut.end) === root.normalizedAiTime(pick.end)) {
                    added = true
                    break
                }
            }

            if (pick.added !== added)
                aiPicksModel.setProperty(pickIndex, "added", added)
            if (added && pick.selected)
                aiPicksModel.setProperty(pickIndex, "selected", false)
        }
    }

    function aiSuggestionValue(suggestion, key, fallback) {
        if (!suggestion) return fallback || ""
        var value = suggestion[key]
        return value === undefined || value === null ? (fallback || "") : String(value)
    }

    function stableAiSuggestionId(suggestion, startTime, endTime, category, reason) {
        var suggestionId = root.aiSuggestionValue(suggestion, "id", "").trim()
        if (suggestionId.length > 0) return suggestionId
        return "legacy:" + [startTime, endTime, category, reason].join("|")
    }

    function aiSuggestionConfidence(suggestion) {
        if (suggestion) {
            var finalConfidence = suggestion["final_confidence"]
            if (finalConfidence !== undefined && finalConfidence !== null && finalConfidence !== "") {
                var numericConfidence = Number(finalConfidence)
                if (Number.isFinite(numericConfidence)) {
                    var percent = numericConfidence >= 0 && numericConfidence <= 1
                        ? numericConfidence * 100
                        : numericConfidence
                    return Math.round(percent) + "%"
                }
            }
        }
        return root.aiSuggestionValue(suggestion, "confidence", qsTr("Medium"))
    }

    function aiSuggestionReviewState(suggestion) {
        var reviewState = root.aiSuggestionValue(suggestion, "review_state", "pending").toLowerCase()
        return reviewState === "accepted" || reviewState === "rejected" ? reviewState : "pending"
    }

    function rebuildAiPicksModel() {
        var previousEdits = []
        for (var previousIndex = 0; previousIndex < aiPicksModel.count; previousIndex += 1) {
            var previousPick = aiPicksModel.get(previousIndex)
            previousEdits.push({
                "suggestionId": previousPick.suggestionId,
                "start": previousPick.start,
                "end": previousPick.end,
                "reason": previousPick.reason,
                "reviewState": previousPick.reviewState
            })
        }
        aiPicksModel.clear()

        var suggestions = appController.aiSuggestions
        for (var index = 0; index < suggestions.length; index += 1) {
            var suggestion = suggestions[index]
            var startTime = root.aiSuggestionValue(suggestion, "start", "")
            var endTime = root.aiSuggestionValue(suggestion, "end", "")
            if (startTime.length === 0 || endTime.length === 0) continue

            var category = root.aiSuggestionValue(suggestion, "category", "uncertain")
            var reason = root.aiSuggestionValue(suggestion, "reason", "")
            var suggestionId = root.stableAiSuggestionId(
                suggestion,
                startTime,
                endTime,
                category,
                reason
            )
            var reviewState = root.aiSuggestionReviewState(suggestion)

            for (var editIndex = 0; editIndex < previousEdits.length; editIndex += 1) {
                var previousEdit = previousEdits[editIndex]
                if (previousEdit.suggestionId !== suggestionId
                        || previousEdit.reviewState !== "pending"
                        || reviewState !== "pending") continue
                startTime = previousEdit.start
                endTime = previousEdit.end
                reason = previousEdit.reason
                break
            }

            aiPicksModel.append({
                "suggestionId": suggestionId,
                "start": startTime,
                "end": endTime,
                "category": category,
                "confidence": root.aiSuggestionConfidence(suggestion),
                "reason": reason,
                "reviewState": reviewState,
                "needsReview": suggestion["needs_review"] !== false,
                "selected": false,
                "added": reviewState === "accepted"
            })
        }
    }

    function displayAiTime(value) {
        return String(value || "").split(".")[0]
    }

    function aiPicksTitle() {
        if (appController.selectedVideoPath.length === 0) return qsTr("AI Picks unavailable")
        if (appController.aiAnalysisState === "running"
                || appController.aiAnalysisState === "cancelling") return qsTr("Analyzing video...")
        if (aiPicksModel.count === 0) return qsTr("No AI picks yet")
        return qsTr("AI Picks")
    }

    function aiPicksSubtitle() {
        if (appController.selectedVideoPath.length === 0) return qsTr("Open a video first.")
        if (appController.aiAnalysisState === "running"
                || appController.aiAnalysisState === "cancelling") return qsTr("Please wait while analysis runs.")
        if (aiPicksModel.count === 0) return qsTr("Run analysis to generate suggestions.")
        return qsTr("Suggested cuts detected")
    }

    Component.onCompleted: root.rebuildAiPicksModel()

    Rectangle {
        anchors.fill: parent
        radius: 14
        color: root.lightMode ? root.panelColor : "#0A1423"
        border.color: root.lightMode ? root.strokeColor : "#233754"

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 13
            color: "transparent"
            border.color: root.lightMode ? "#FFFFFF" : "#163456"
            border.width: 1
            opacity: root.lightMode ? 0.42 : 0.42
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 1
            height: 1
            color: root.lightMode ? "#FFFFFF" : "#7DB7FF"
            opacity: root.lightMode ? 0.55 : 0.18
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 16

            RowLayout {
                Layout.preferredWidth: 174
                Layout.minimumWidth: 150
                spacing: 10

                Rectangle {
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 32
                    radius: 10
                    color: root.lightMode ? "#EFF6FF" : "#0B2548"
                    border.color: root.lightMode ? "#BFDBFE" : "#2F7BFF"

                    Rectangle {
                        anchors.centerIn: parent
                        width: 20
                        height: 20
                        radius: 8
                        color: "#2F7BFF"
                        opacity: root.lightMode ? 0.16 : 0.18
                    }

                    Image {
                        anchors.centerIn: parent
                        width: 23
                        height: 23
                        source: root.appIconSource
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "NSFW Cutter"
                    color: root.textColor
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                id: openButton
                objectName: "openMenuButton"

                text: qsTr("Open")
                font.pixelSize: 13
                font.weight: Font.DemiBold
                Layout.preferredWidth: 112
                Layout.preferredHeight: 40
                onClicked: openMenu.opened ? openMenu.closeAfterAction() : openMenu.showAt(openButton)

                background: Rectangle {
                    radius: 10
                    color: openMenu.opened
                        ? (root.lightMode ? "#DBEAFE" : "#102A43")
                        : (root.lightMode ? "#2563EB" : "#0F2F66")
                    border.color: openMenu.opened
                        ? (root.lightMode ? "#2563EB" : root.accentColor)
                        : (root.lightMode ? "#2563EB" : "#2F7BFF")
                    border.width: 1
                }

                contentItem: RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 10
                    spacing: 7

                    VectorIcon {
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                        name: "open"
                        iconColor: "#F8FAFC"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: openButton.text
                        color: "#F8FAFC"
                        font: openButton.font
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }

                    VectorIcon {
                        Layout.preferredWidth: 14
                        Layout.preferredHeight: 14
                        name: openMenu.opened ? "chevronUp" : "chevronDown"
                        iconColor: "#F8FAFC"
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 190
                spacing: 3

                Text {
                    Layout.fillWidth: true
                    text: appController.selectedVideoPath.length > 0 && appController.videoName.length > 0
                        ? appController.videoName
                        : qsTr("No video loaded")
                    color: appController.selectedVideoPath.length > 0 ? root.textColor : root.mutedTextColor
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    elide: Text.ElideMiddle
                    verticalAlignment: Text.AlignVCenter
                }

                Text {
                    Layout.fillWidth: true
                    text: root.mediaDetailLabel()
                    color: root.mutedTextColor
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    hoverEnabled: true
                    ToolTip.visible: containsMouse && appController.selectedVideoPath.length > 0
                    ToolTip.text: appController.selectedVideoPath
                }
            }

            AppButton {
                id: subtitleButton

                text: root.subtitleButtonLabel()
                iconName: "cc"
                variant: "ghost"
                size: "md"
                lightMode: root.lightMode
                enabled: root.selectableSubtitleCount() > 0
                Layout.preferredWidth: 184
                Layout.preferredHeight: 40
                onClicked: subtitleSelector.showAt(subtitleButton)
            }

            AppButton {
                id: aiPicksButton
                objectName: "aiPicksButton"

                text: qsTr("AI Picks ▼")
                iconName: "sparkle"
                variant: "ghost"
                size: "md"
                lightMode: root.lightMode
                active: hovered || aiPicksPopup.opened
                activeAccentColor: root.accentColor
                Layout.preferredWidth: 138
                Layout.preferredHeight: 40
                onClicked: aiPicksPopup.opened ? aiPicksPopup.closeAfterAction() : aiPicksPopup.showAt(aiPicksButton)
            }

            ThemeToggleButton {
                lightMode: root.lightMode
                Layout.preferredWidth: 64
                Layout.preferredHeight: 44
                onClicked: root.toggleTheme()
            }

            AppButton {
                text: ""
                accessibilityLabel: qsTr("Settings")
                iconSource: Qt.resolvedUrl("../../../../assets/icons/settings.png")
                imageIconSize: 32
                variant: "ghost"
                size: "icon"
                lightMode: root.lightMode
                Layout.preferredWidth: 44
                Layout.preferredHeight: 44
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Settings")
                onClicked: root.settingsRequested()
            }
        }
    }

    ListModel {
        id: aiPicksModel
    }

    AiPicksPopup {
        id: aiPicksPopup
        objectName: "aiPicksPopup"

        lightMode: root.lightMode
        textColor: root.textColor
        mutedTextColor: root.mutedTextColor
        accentColor: root.accentColor
        picksModel: aiPicksModel
        onAcceptRequested: function(suggestionId, startTime, endTime, confidence, reason) {
            root.aiPickAcceptRequested(suggestionId, startTime, endTime, confidence, reason)
        }
        onRejectRequested: function(suggestionId) {
            root.aiPickRejectRequested(suggestionId)
        }
    }

    Popup {
        id: openMenu
        objectName: "openMenuPopup"

        readonly property int menuWidth: 410

        function showAt(target) {
            var position = target.mapToItem(openMenu.parent, 0, 0)
            openMenu.x = position.x
            openMenu.y = position.y + target.height + 8
            openMenu.open()
            openMenu.forceActiveFocus()
        }

        function closeAfterAction() {
            openMenu.close()
        }

        modal: false
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        width: openMenu.menuWidth
        height: menuColumn.implicitHeight + 18

        onAboutToShow: appController.refreshRecentFiles()

        Keys.onEscapePressed: openMenu.closeAfterAction()

        background: Item {}

        contentItem: Item {
            implicitWidth: openMenu.width
            implicitHeight: openMenu.height

            Rectangle {
                x: 0
                y: 5
                width: parent.width
                height: parent.height
                radius: 14
                color: "#000000"
                opacity: root.lightMode ? 0.14 : 0.34
            }

            Rectangle {
                anchors.fill: parent
                radius: 14
                color: root.elevatedPanel
                border.color: root.elevatedBorder
                border.width: 1
            }

            Column {
                id: menuColumn

                x: 9
                y: 9
                width: openMenu.menuWidth - 18
                spacing: 5

                MenuAction {
                    iconName: "open"
                    label: qsTr("Select Video...")
                    shortcut: "Ctrl+O"
                    onTriggered: {
                        openMenu.closeAfterAction()
                        appController.openFile()
                    }
                }

                MenuAction {
                    iconName: "folder"
                    label: qsTr("Select Folder...")
                    shortcut: "Ctrl+Shift+O"
                    onTriggered: {
                        openMenu.closeAfterAction()
                        appController.browseFolder()
                    }
                }

                MenuSeparator {}

                SectionLabel {
                    text: qsTr("Recent Videos")
                }

                MenuAction {
                    visible: appController.recentFiles.length === 0
                    label: qsTr("No recent videos")
                    enabled: false
                }

                Repeater {
                    model: appController.recentFiles

                    delegate: MenuAction {
                        id: recentRow

                        required property var modelData

                        iconName: "history"
                        label: root.recentDisplayName(recentRow.modelData)
                        tooltip: root.recentDisplayPath(recentRow.modelData)
                        onTriggered: {
                            var recentPath = root.recentDisplayPath(recentRow.modelData)
                            if (recentPath.length === 0) return
                            openMenu.closeAfterAction()
                            appController.openRecentFile(recentPath)
                        }
                    }
                }

                MenuSeparator {}

                MenuAction {
                    iconName: "trash"
                    label: qsTr("Clear Recent List")
                    enabled: appController.recentFiles.length > 0
                    onTriggered: {
                        openMenu.closeAfterAction()
                        appController.clearRecentFiles()
                    }
                }
            }
        }

        component MenuSeparator: Rectangle {
            width: parent ? parent.width : openMenu.menuWidth - 18
            height: 1
            color: root.lightMode ? "#E5EAF2" : "#1F2F4A"
        }

        component SectionLabel: Rectangle {
            property string text: ""

            width: parent ? parent.width : openMenu.menuWidth - 18
            height: 28
            color: "transparent"

            Text {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                text: parent.text
                color: root.lightMode ? "#64748B" : root.mutedTextColor
                font.pixelSize: 11
                font.weight: Font.DemiBold
                font.letterSpacing: 0.8
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }

        component MenuAction: Rectangle {
            id: actionRoot

            property string iconText: ""
            property string iconName: ""
            property string label: ""
            property string shortcut: ""
            property string tooltip: ""

            signal triggered()

            width: parent ? parent.width : openMenu.menuWidth - 18
            height: 36
            radius: 8
            color: menuMouse.containsMouse && actionRoot.enabled
                ? (root.lightMode ? "#EFF6FF" : "#102A43")
                : "transparent"
            opacity: actionRoot.enabled ? 1.0 : 0.48

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8

                VectorIcon {
                    visible: actionRoot.iconName.length > 0
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                    name: actionRoot.iconName
                    iconColor: actionRoot.enabled
                        ? (root.lightMode ? "#1F6FEB" : "#60A5FA")
                        : (root.lightMode ? "#94A3B8" : "#64748B")
                }

                Text {
                    visible: actionRoot.iconText.length > 0 && actionRoot.iconName.length === 0
                    Layout.preferredWidth: 18
                    text: actionRoot.iconText
                    color: actionRoot.enabled
                        ? (root.lightMode ? "#1F6FEB" : "#60A5FA")
                        : (root.lightMode ? "#94A3B8" : "#64748B")
                    font.pixelSize: 14
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: actionRoot.label
                    color: actionRoot.enabled
                        ? (root.lightMode ? "#0F172A" : root.textColor)
                        : (root.lightMode ? "#94A3B8" : "#64748B")
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                Text {
                    visible: actionRoot.shortcut.length > 0
                    text: actionRoot.shortcut
                    color: root.lightMode ? "#64748B" : root.mutedTextColor
                    font.pixelSize: 11
                    verticalAlignment: Text.AlignVCenter
                }
            }

            MouseArea {
                id: menuMouse

                anchors.fill: parent
                enabled: actionRoot.enabled
                hoverEnabled: true
                cursorShape: actionRoot.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: actionRoot.triggered()
            }

            ToolTip.visible: actionRoot.tooltip.length > 0 && menuMouse.containsMouse
            ToolTip.text: actionRoot.tooltip
        }
    }

    SubtitleSelectorPopup {
        id: subtitleSelector

        lightMode: root.lightMode
        textColor: root.textColor
        mutedTextColor: root.mutedTextColor
        options: appController.analysisSubtitleOptions
        detectedCount: appController.subtitleCandidates.length
        onCandidateSelected: function(candidateId) {
            if (appController.selectAnalysisSubtitle(candidateId))
                subtitleSelector.closeAfterAction()
        }
    }

    Connections {
        target: appController

        function onSelectedVideoPathChanged() {
            subtitleSelector.closeAfterAction()
            openMenu.closeAfterAction()
            root.rebuildAiPicksModel()
            aiPicksPopup.closeAfterAction()
        }

        function onAiSuggestionsChanged() {
            root.rebuildAiPicksModel()
        }

        function onSubtitleCandidatesChanged() {
            if (root.selectableSubtitleCount() === 0)
                subtitleSelector.closeAfterAction()
        }
    }

    Shortcut {
        sequence: "Ctrl+O"
        onActivated: appController.openFile()
    }

    Shortcut {
        sequence: "Ctrl+Shift+O"
        onActivated: appController.browseFolder()
    }
}

