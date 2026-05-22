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
    property bool darkMode: settingsController.theme !== "light"

    visible: true
    visibility: Window.Maximized
    width: Math.min(1360, root.availableScreenWidth)
    height: Math.min(820, root.availableScreenHeight)
    minimumWidth: Math.min(960, root.availableScreenWidth)
    minimumHeight: Math.min(620, root.availableScreenHeight)
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
