pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

Popup {
    id: root

    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color mutedTextColor: "#92A2B8"
    property color accentColor: "#2F7BFF"
    property var picksModel: null
    property var anchorTarget: null

    readonly property int menuWidth: 560
    readonly property bool hasSelectedVideo: String(appController.selectedVideoPath || "").length > 0
    readonly property string analysisState: String(appController.aiAnalysisState || "idle")
    readonly property bool analysisRunning: root.analysisState === "running"
        || root.analysisState === "cancelling"
    readonly property int analysisProgress: Math.max(0, Math.min(100, Number(appController.aiAnalysisProgress || 0)))
    readonly property string analysisStatus: String(appController.aiAnalysisStatus || "")
    readonly property string analysisError: String(appController.aiAnalysisError || "")
    readonly property var analysisDetails: appController.aiAnalysisDetails || ({})
    readonly property bool analysisDiagnosticIsError: root.analysisState === "error"
    readonly property int suggestionCount: root.picksModel ? root.picksModel.count : 0

    signal acceptRequested(string suggestionId, string startTime, string endTime, string confidence, string reason)
    signal rejectRequested(string suggestionId)

    function formatEta(value) {
        var seconds = Number(value)
        if (!isFinite(seconds) || seconds < 0) return qsTr("calculating")
        if (seconds < 60) return Math.ceil(seconds) + "s"
        var minutes = Math.floor(seconds / 60)
        var remainder = Math.ceil(seconds % 60)
        return minutes + "m " + remainder + "s"
    }

    function progressDetailsText() {
        var details = root.analysisDetails
        var parts = []
        if (details.device) parts.push(String(details.device))
        if (Number(details.candidate_count || 0) > 0)
            parts.push(qsTr("Candidates") + ": " + Number(details.candidate_count))
        if (Number(details.total_units || 0) > 0)
            parts.push(Number(details.completed_units || 0) + "/" + Number(details.total_units) + " " + qsTr("batches"))
        if (Number(details.resumed_units || 0) > 0)
            parts.push(qsTr("Resumed") + ": " + Number(details.resumed_units))
        if (Number(details.repaired_units || 0) > 0)
            parts.push(qsTr("Repaired") + ": " + Number(details.repaired_units))
        if (Number(details.failed_units || 0) > 0)
            parts.push(qsTr("Failed") + ": " + Number(details.failed_units))
        if (details.eta_seconds !== undefined && details.eta_seconds !== null)
            parts.push(qsTr("ETA") + ": " + root.formatEta(details.eta_seconds))
        return parts.join("  •  ")
    }

    AppTheme { id: theme }

    function maximumAvailableHeight() {
        var hostWindow = root.anchorTarget ? root.anchorTarget.Window.window : null
        return hostWindow ? Math.max(280, hostWindow.height - 32) : 680
    }

    function reposition() {
        if (!root.anchorTarget || !root.parent) return

        var position = root.anchorTarget.mapToItem(root.parent, 0, 0)
        var windowMargin = 16
        var parentScenePosition = root.parent.mapToItem(null, 0, 0)
        var hostWindow = root.anchorTarget.Window.window
        var maximumX = Math.max(windowMargin, root.parent.width - root.width - windowMargin)
        var preferredY = position.y + root.anchorTarget.height + 8
        var minimumY = hostWindow ? windowMargin - parentScenePosition.y : 0
        var maximumY = hostWindow
            ? hostWindow.height - parentScenePosition.y - root.height - windowMargin
            : preferredY

        root.x = Math.max(windowMargin, Math.min(position.x, maximumX))
        root.y = Math.max(minimumY, Math.min(preferredY, maximumY))
    }

    function showAt(target) {
        root.anchorTarget = target
        root.reposition()
        root.open()
        root.forceActiveFocus()
    }

    function closeAfterAction() {
        root.close()
    }

    function categoryLabel(category) {
        var words = String(category || "uncertain").replace(/_/g, " ")
        return words.charAt(0).toUpperCase() + words.slice(1)
    }

    function reviewLabel(reviewState, added) {
        if (reviewState === "accepted" || added) return qsTr("Accepted")
        if (reviewState === "rejected") return qsTr("Rejected")
        return qsTr("Needs review")
    }

    function reviewColor(reviewState, added) {
        if (reviewState === "accepted" || added)
            return root.lightMode ? "#15803D" : "#86EFAC"
        if (reviewState === "rejected") return root.lightMode ? "#B91C1C" : "#FCA5A5"
        return root.accentColor
    }

    function saveEdits(index, startTime, endTime, reason) {
        if (!root.picksModel || index < 0 || index >= root.picksModel.count) return
        root.picksModel.setProperty(index, "start", String(startTime || "").trim())
        root.picksModel.setProperty(index, "end", String(endTime || "").trim())
        root.picksModel.setProperty(index, "reason", String(reason || "").trim())
    }

    modal: false
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: Math.min(root.menuWidth, root.parent ? Math.max(320, root.parent.width - 32) : root.menuWidth)
    height: Math.min(root.maximumAvailableHeight(), popupColumn.implicitHeight + 28)

    onHeightChanged: {
        if (root.opened) root.reposition()
    }
    onSuggestionCountChanged: {
        if (root.opened) Qt.callLater(root.reposition)
    }
    onOpened: root.reposition()

    background: Item {}

    Connections {
        target: root.anchorTarget
        enabled: root.opened
        ignoreUnknownSignals: true

        function onXChanged() { root.reposition() }
        function onYChanged() { root.reposition() }
        function onWidthChanged() { root.reposition() }
        function onHeightChanged() { root.reposition() }
    }

    Connections {
        target: root.anchorTarget ? root.anchorTarget.Window.window : null
        enabled: root.opened
        ignoreUnknownSignals: true

        function onWidthChanged() { Qt.callLater(root.reposition) }
        function onHeightChanged() { Qt.callLater(root.reposition) }
    }

    contentItem: Item {
        implicitWidth: root.width
        implicitHeight: root.height

        Rectangle {
            x: 0
            y: 5
            width: parent.width
            height: parent.height - 5
            radius: theme.panelRadius
            color: "#000000"
            opacity: 0.34
        }

        Rectangle {
            anchors.fill: parent
            radius: theme.panelRadius
            color: root.lightMode ? theme.lightSurface : theme.darkAppBg
            border.color: root.lightMode ? theme.lightBorder : theme.darkBorder
            border.width: 1
        }

        Column {
            id: popupColumn

            x: 14
            y: 14
            width: root.width - 28
            spacing: theme.sectionGap

            Row {
                width: parent.width
                height: 22
                spacing: 8

                VectorIcon {
                    width: 18
                    height: 18
                    anchors.verticalCenter: parent.verticalCenter
                    name: "sparkle"
                    iconColor: root.accentColor
                }

                Text {
                    width: parent.width - 26
                    height: parent.height
                    text: qsTr("AI Picks")
                    color: root.textColor
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }

            }

            Text {
                width: parent.width
                text: qsTr("Local analysis creates review-only suggestions. Nothing is cut until you explicitly accept a suggestion.")
                color: root.mutedTextColor
                font.pixelSize: 12
                lineHeight: 1.25
                wrapMode: Text.WordWrap
            }

            Rectangle {
                width: parent.width
                height: noVideoText.implicitHeight + 20
                radius: theme.innerRadius
                visible: !root.hasSelectedVideo
                color: root.lightMode ? "#FFF7ED" : "#2B1B0B"
                border.color: root.lightMode ? "#FDBA74" : "#9A5B16"

                Text {
                    id: noVideoText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: qsTr("Select a video before starting analysis.")
                    color: root.lightMode ? "#9A3412" : "#FDBA74"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Column {
                width: parent.width
                spacing: 7
                visible: root.hasSelectedVideo && (root.analysisRunning
                    || root.analysisState !== "idle"
                    || root.analysisStatus.length > 0)

                Text {
                    width: parent.width
                    text: root.analysisRunning ? qsTr("Analysis in progress") : qsTr("Analysis status")
                    color: root.textColor
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    text: root.analysisStatus
                    color: root.mutedTextColor
                    font.pixelSize: 12
                    lineHeight: 1.2
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    visible: root.analysisRunning
                    text: qsTr("Analyzing...") + " " + root.analysisProgress + "%"
                    color: root.accentColor
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    visible: root.analysisRunning && root.progressDetailsText().length > 0
                    text: root.progressDetailsText()
                    color: root.mutedTextColor
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }

                ProgressBar {
                    id: analysisProgressBar
                    objectName: "aiPicksProgressBar"

                    width: parent.width
                    height: 8
                    visible: root.analysisRunning
                    padding: 0
                    from: 0
                    to: 100
                    value: root.analysisProgress

                    background: Rectangle {
                        implicitWidth: analysisProgressBar.width
                        implicitHeight: 8
                        radius: 4
                        color: root.lightMode ? theme.lightBorderSoft : theme.darkBorderSoft
                    }

                    contentItem: Item {
                        implicitWidth: analysisProgressBar.width
                        implicitHeight: 8

                        Rectangle {
                            width: analysisProgressBar.visualPosition * parent.width
                            height: parent.height
                            radius: 4
                            color: root.accentColor
                        }
                    }
                }
            }

            Rectangle {
                width: parent.width
                height: analysisErrorText.implicitHeight + 20
                radius: theme.innerRadius
                visible: root.analysisError.length > 0
                color: root.analysisDiagnosticIsError
                    ? (root.lightMode ? "#FEF2F2" : "#2C1117")
                    : (root.lightMode ? "#FFF7ED" : "#2B1B0B")
                border.color: root.analysisDiagnosticIsError
                    ? (root.lightMode ? "#FCA5A5" : "#7A3144")
                    : (root.lightMode ? "#FDBA74" : "#9A5B16")

                Text {
                    id: analysisErrorText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: root.analysisError
                    color: root.analysisDiagnosticIsError
                        ? (root.lightMode ? "#B91C1C" : "#FCA5A5")
                        : (root.lightMode ? "#9A3412" : "#FDBA74")
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
            }

            AppButton {
                objectName: "aiPicksActionButton"
                width: parent.width
                height: 40
                text: root.analysisState === "cancelling"
                    ? qsTr("Cancelling...")
                    : (root.analysisRunning ? qsTr("Cancel analysis") : qsTr("Analyze video"))
                variant: root.analysisRunning ? "danger" : "primary"
                size: "md"
                lightMode: root.lightMode
                enabled: root.analysisState === "running"
                    || (!root.analysisRunning && root.hasSelectedVideo)
                onClicked: {
                    if (root.analysisState === "running")
                        appController.cancelVideoAnalysis()
                    else if (!root.analysisRunning && root.hasSelectedVideo)
                        appController.analyzeVideo()
                }
            }

            Rectangle {
                width: parent.width
                height: 1
                color: root.lightMode ? theme.lightDivider : theme.darkDivider
            }

            RowLayout {
                width: parent.width

                Text {
                    Layout.fillWidth: true
                    text: qsTr("Suggestions")
                    color: root.textColor
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }

                Text {
                    text: String(root.suggestionCount)
                    color: root.accentColor
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }

            Text {
                width: parent.width
                visible: root.suggestionCount === 0
                text: root.analysisRunning
                    ? qsTr("Suggestions will appear here when analysis completes.")
                    : qsTr("No suggestions are ready for review.")
                color: root.mutedTextColor
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }

            ListView {
                id: suggestionList

                width: parent.width
                height: root.suggestionCount > 0 ? Math.min(contentHeight, 360) : 0
                visible: root.suggestionCount > 0
                model: root.picksModel
                spacing: 10
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                ScrollBar.vertical: AppScrollBar { lightMode: root.lightMode }

                delegate: Rectangle {
                    id: suggestionCard

                    required property int index
                    required property string suggestionId
                    required property string category
                    required property string confidence
                    required property string start
                    required property string end
                    required property string reason
                    required property string reviewState
                    required property bool added

                    readonly property bool pendingReview: suggestionCard.reviewState === "pending"
                        && !suggestionCard.added

                    width: suggestionList.width
                    height: 246
                    radius: theme.innerRadius
                    color: root.lightMode ? theme.lightSurfaceAlt : theme.darkSurfaceAlt
                    border.color: root.reviewColor(
                        suggestionCard.reviewState,
                        suggestionCard.added
                    )
                    border.width: suggestionCard.pendingReview ? 1 : 2

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 7

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Text {
                                Layout.fillWidth: true
                                text: root.categoryLabel(suggestionCard.category)
                                color: root.textColor
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }

                            Text {
                                text: suggestionCard.confidence
                                color: root.accentColor
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }

                            Text {
                                text: root.reviewLabel(
                                    suggestionCard.reviewState,
                                    suggestionCard.added
                                )
                                color: root.reviewColor(
                                    suggestionCard.reviewState,
                                    suggestionCard.added
                                )
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: qsTr("ID: %1").arg(suggestionCard.suggestionId)
                            color: root.mutedTextColor
                            font.pixelSize: 10
                            elide: Text.ElideMiddle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3

                                Text {
                                    text: qsTr("Start")
                                    color: root.mutedTextColor
                                    font.pixelSize: 11
                                }

                                AppTextField {
                                    id: startInput
                                    objectName: "aiSuggestionStartField"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 36
                                    lightMode: root.lightMode
                                    text: suggestionCard.start
                                    readOnly: !suggestionCard.pendingReview
                                    placeholderText: "00:00:00.000"
                                    onEditingFinished: root.saveEdits(
                                        suggestionCard.index,
                                        startInput.text,
                                        endInput.text,
                                        reasonInput.text
                                    )
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3

                                Text {
                                    text: qsTr("End")
                                    color: root.mutedTextColor
                                    font.pixelSize: 11
                                }

                                AppTextField {
                                    id: endInput
                                    objectName: "aiSuggestionEndField"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 36
                                    lightMode: root.lightMode
                                    text: suggestionCard.end
                                    readOnly: !suggestionCard.pendingReview
                                    placeholderText: "00:00:00.000"
                                    onEditingFinished: root.saveEdits(
                                        suggestionCard.index,
                                        startInput.text,
                                        endInput.text,
                                        reasonInput.text
                                    )
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3

                            Text {
                                text: qsTr("Reason")
                                color: root.mutedTextColor
                                font.pixelSize: 11
                            }

                            AppTextField {
                                id: reasonInput
                                objectName: "aiSuggestionReasonField"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 36
                                lightMode: root.lightMode
                                text: suggestionCard.reason
                                readOnly: !suggestionCard.pendingReview
                                placeholderText: qsTr("Short evidence explanation")
                                onEditingFinished: root.saveEdits(
                                    suggestionCard.index,
                                    startInput.text,
                                    endInput.text,
                                    reasonInput.text
                                )
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Item { Layout.fillWidth: true }

                            AppButton {
                                objectName: "aiSuggestionRejectButton"
                                text: qsTr("Reject")
                                variant: "danger"
                                size: "sm"
                                lightMode: root.lightMode
                                enabled: suggestionCard.pendingReview
                                Layout.preferredWidth: 96
                                onClicked: root.rejectRequested(suggestionCard.suggestionId)
                            }

                            AppButton {
                                objectName: "aiSuggestionAcceptButton"
                                text: qsTr("Accept")
                                variant: "success"
                                size: "sm"
                                lightMode: root.lightMode
                                enabled: suggestionCard.pendingReview
                                Layout.preferredWidth: 96
                                onClicked: {
                                    root.saveEdits(
                                        suggestionCard.index,
                                        startInput.text,
                                        endInput.text,
                                        reasonInput.text
                                    )
                                    root.acceptRequested(
                                        suggestionCard.suggestionId,
                                        startInput.text.trim(),
                                        endInput.text.trim(),
                                        suggestionCard.confidence,
                                        reasonInput.text.trim()
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
