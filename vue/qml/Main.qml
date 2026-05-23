pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

import "components"
import "pages"

ApplicationWindow {
    id: root

    readonly property int availableScreenWidth: Screen.desktopAvailableWidth > 0 ? Screen.desktopAvailableWidth : Screen.width
    readonly property int availableScreenHeight: Screen.desktopAvailableHeight > 0 ? Screen.desktopAvailableHeight : Screen.height
    readonly property int restoreWidth: root.availableScreenWidth >= 1280 ? Math.min(1920, root.availableScreenWidth - 40) : root.availableScreenWidth
    readonly property int restoreHeight: root.availableScreenHeight >= 720 ? Math.min(1080, root.availableScreenHeight - 40) : root.availableScreenHeight
    property bool darkMode: settingsController.theme !== "light"

    visible: true
    visibility: Window.Maximized
    width: root.restoreWidth
    height: root.restoreHeight
    minimumWidth: Math.min(1280, root.availableScreenWidth)
    minimumHeight: Math.min(720, root.availableScreenHeight)
    title: "NSFW Cutter"
    color: root.darkMode ? "#0F172A" : "#F6F7FB"

    SettingsDialog {
        id: settingsDialog
    }

    HomePage {
        anchors.fill: parent
        onSettingsRequested: settingsDialog.openWithCurrentSettings()
    }
}
