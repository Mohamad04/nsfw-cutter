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

Popup {
    id: root

    property bool lightMode: false
    property bool canClearCurrentMedia: false
    property var recentFiles: []
    property color textColor: "#F8FAFC"
    property color mutedTextColor: "#94A3B8"
    property color accentColor: "#38BDF8"
    readonly property int menuWidth: 286
    readonly property int recentWidth: 300
    readonly property int panelGap: 6
    property bool recentOpen: false

    signal openFileRequested()
    signal openFilesRequested()
    signal openFolderRequested()
    signal recentFileRequested(string path)
    signal clearRecentFilesRequested()
    signal clearCurrentMediaRequested()
    signal refreshRecentFilesRequested()

    function showAt(target) {
        root.x = target.x
        root.y = target.y + target.height + 6
        root.recentOpen = false
        root.open()
        root.forceActiveFocus()
    }

    function closeAfterAction() {
        root.recentOpen = false
        root.close()
    }

    modal: false
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: root.recentOpen ? root.menuWidth + root.panelGap + root.recentWidth : root.menuWidth
    height: Math.max(menuColumn.implicitHeight + 16, root.recentOpen ? recentPanel.y + recentPanel.height : 0)

    onAboutToShow: root.refreshRecentFilesRequested()
    onClosed: root.recentOpen = false

    Keys.onEscapePressed: root.closeAfterAction()

    background: Item {}

    contentItem: Item {
        implicitWidth: root.width
        implicitHeight: root.height

        Rectangle {
            id: mainPanel

            x: 0
            y: 0
            width: root.menuWidth
            height: menuColumn.implicitHeight + 16
            radius: 10
            color: root.lightMode ? "#FFFFFF" : "#07111E"
            border.color: root.lightMode ? "#CBD5E1" : "#243244"
            border.width: 1
        }

        Column {
            id: menuColumn

            x: 8
            y: 8
            width: root.menuWidth - 16
            spacing: 4

            MenuAction {
                label: "Open File..."
                shortcut: "Ctrl+O"
                onHovered: root.recentOpen = false
                onTriggered: {
                    root.closeAfterAction()
                    root.openFileRequested()
                }
            }

            MenuAction {
                label: "Open Files..."
                onHovered: root.recentOpen = false
                onTriggered: {
                    root.closeAfterAction()
                    root.openFilesRequested()
                }
            }

            MenuAction {
                label: "Open Folder..."
                onHovered: root.recentOpen = false
                onTriggered: {
                    root.closeAfterAction()
                    root.openFolderRequested()
                }
            }

            MenuSeparator {}

            MenuAction {
                id: recentItem

                label: "Recent Files"
                accessory: ">"
                onHovered: root.recentOpen = true
                onTriggered: root.recentOpen = true
            }

            MenuSeparator {}

            MenuAction {
                label: "Clear Current Media"
                enabled: root.canClearCurrentMedia
                onHovered: root.recentOpen = false
                onTriggered: {
                    root.closeAfterAction()
                    root.clearCurrentMediaRequested()
                }
            }
        }

        Rectangle {
            id: recentPanel

            visible: root.recentOpen
            x: root.menuWidth + root.panelGap
            y: menuColumn.y + recentItem.y
            width: root.recentWidth
            height: recentColumn.implicitHeight + 16
            radius: 10
            color: root.lightMode ? "#FFFFFF" : "#07111E"
            border.color: root.lightMode ? "#CBD5E1" : "#243244"
            border.width: 1

            Column {
                id: recentColumn

                x: 8
                y: 8
                width: root.recentWidth - 16
                spacing: 4

                MenuAction {
                    visible: root.recentFiles.length === 0
                    label: "No recent files"
                    enabled: false
                }

                Repeater {
                    model: root.recentFiles

                    delegate: MenuAction {
                        required property var modelData

                        label: modelData.name
                        tooltip: modelData.path
                        onTriggered: {
                            root.closeAfterAction()
                            root.recentFileRequested(modelData.path)
                        }
                    }
                }

                MenuSeparator {}

                MenuAction {
                    label: "Clear Recent Files"
                    enabled: root.recentFiles.length > 0
                    onTriggered: {
                        root.closeAfterAction()
                        root.clearRecentFilesRequested()
                    }
                }
            }
        }
    }

    component MenuSeparator: Rectangle {
        width: parent ? parent.width : root.menuWidth - 16
        height: 1
        color: root.lightMode ? "#E5EAF2" : "#1F2F4A"
    }

    component MenuAction: Rectangle {
        id: actionRoot

        property string label: ""
        property string shortcut: ""
        property string accessory: ""
        property string tooltip: ""

        signal triggered()
        signal hovered()

        width: parent ? parent.width : root.menuWidth - 16
        height: 34
        radius: 7
        color: menuMouse.containsMouse && actionRoot.enabled
            ? (root.lightMode ? "#EFF6FF" : "#102A43")
            : "transparent"
        opacity: actionRoot.enabled ? 1.0 : 0.48

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 8

            Text {
                Layout.fillWidth: true
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

            Text {
                visible: actionRoot.accessory.length > 0
                text: actionRoot.accessory
                color: root.lightMode ? "#64748B" : root.mutedTextColor
                font.pixelSize: 13
                verticalAlignment: Text.AlignVCenter
            }
        }

        MouseArea {
            id: menuMouse

            anchors.fill: parent
            enabled: actionRoot.enabled
            hoverEnabled: true
            cursorShape: actionRoot.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onEntered: actionRoot.hovered()
            onClicked: actionRoot.triggered()
        }

        ToolTip.visible: actionRoot.tooltip.length > 0 && menuMouse.containsMouse
        ToolTip.text: actionRoot.tooltip
    }
}

