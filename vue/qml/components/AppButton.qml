import QtQuick
import QtQuick.Controls

Button {
    id: root

    property string variant: "secondary"
    // primary, secondary, success, danger, control, ghost

    property string size: "md"
    // sm, md, lg, icon

    property bool lightMode: false
    property int radiusValue: size === "icon" ? 14 : 10

    implicitHeight: {
        if (size === "sm") return 36
        if (size === "lg") return 42
        if (size === "icon") return 52
        return 42
    }

    implicitWidth: {
        if (size === "sm") return 92
        if (size === "lg") return 160
        if (size === "icon") return 52
        return 124
    }

    font.pixelSize: size === "sm" ? 12 : 13
    font.weight: Font.Medium

    scale: down ? 0.985 : 1.0

    Behavior on scale {
        NumberAnimation {
            duration: 80
            easing.type: Easing.OutQuad
        }
    }

    function baseColor() {
        if (root.lightMode) {
            if (!root.enabled) {
                if (variant === "danger") return "#FEE2E2"
                if (variant === "ghost") return "#F8FAFC"
                return "#E2E8F0"
            }
            if (variant === "primary") return "#2563EB"
            if (variant === "success") return "#16A34A"
            if (variant === "danger") return "#DC2626"
            if (variant === "control") return "#FFFFFF"
            if (variant === "ghost") return "#FFFFFF"
            return "#FFFFFF"
        }
        if (variant === "primary") return "#2563EB"
        if (variant === "success") return "#15803D"
        if (variant === "danger") return "#991B1B"
        if (variant === "control") return "#1E293B"
        if (variant === "ghost") return "#101826"
        return "#0371ff"
    }

    function hoverColor() {
        if (root.lightMode) {
            if (variant === "primary") return "#1D4ED8"
            if (variant === "success") return "#15803D"
            if (variant === "danger") return root.enabled ? "#B91C1C" : "#FEE2E2"
            if (variant === "control") return "#EFF6FF"
            return "#EFF6FF"
        }
        if (variant === "primary") return "#2A6CF0"
        if (variant === "success") return "#169247"
        if (variant === "danger") return "#AB2020"
        if (variant === "control") return "#243244"
        if (variant === "ghost") return "#121C2C"
        return "#2A3A4E"
    }

    function pressedColor() {
        if (root.lightMode) {
            if (variant === "primary") return "#1E40AF"
            if (variant === "success") return "#166534"
            if (variant === "danger") return root.enabled ? "#991B1B" : "#FEE2E2"
            if (variant === "control") return "#DBEAFE"
            return "#DBEAFE"
        }
        if (variant === "primary") return "#1E40AF"
        if (variant === "success") return "#14532D"
        if (variant === "danger") return "#651313"
        if (variant === "control") return "#0F172A"
        if (variant === "ghost") return "#0B1324"
        return "#172033"
    }

    function borderColor() {
        if (root.lightMode) {
            if (!root.enabled && variant === "danger") return "#FCA5A5"
            if (!root.enabled) return "#CBD5E1"
            if (variant === "primary") return "#2563EB"
            if (variant === "success") return "#16A34A"
            if (variant === "danger") return "#DC2626"
            if (variant === "control") return root.hovered && root.enabled ? "#93C5FD" : "#CBD5E1"
            return root.hovered && root.enabled ? "#93C5FD" : "#CBD5E1"
        }
        if (variant === "primary") return "#3B82F6"
        if (variant === "success") return "#22C55E"
        if (variant === "danger") return "#EF4444"
        if (variant === "control") return "#334155"
        if (variant === "ghost") return "#334155"
        return "#334155"
    }

    function hoverOverlayOpacity() {
        if (root.lightMode) return 0.0
        if (!root.hovered || root.down || !root.enabled) return 0.0
        if (variant === "ghost") return 0.0
        if (variant === "primary") return 0.02
        if (variant === "success") return 0.018
        if (variant === "danger") return 0.018
        return 0.015
    }

    function hoverOverlayColor() {
        if (root.lightMode) return "#EFF6FF"
        if (variant === "primary") return "#1E3A8A"
        if (variant === "success") return "#14532D"
        if (variant === "danger") return "#7F1D1D"
        if (variant === "ghost") return "#1E293B"
        return "#334155"
    }

    function textColor() {
        if (!root.enabled) {
            if (root.lightMode && root.variant === "danger") return "#991B1B"
            return root.lightMode ? "#94A3B8" : "#64748B"
        }
        if (root.lightMode && root.variant === "control") return "#334155"
        if (root.variant === "primary" || root.variant === "success" || root.variant === "danger" || root.variant === "control") return "#F8FAFC"
        return root.lightMode ? "#334155" : "#F8FAFC"
    }

    background: Rectangle {
        radius: root.radiusValue
        color: !root.enabled ? root.baseColor() : (root.down ? root.pressedColor() : (root.hovered ? root.hoverColor() : root.baseColor()))
        border.color: root.borderColor()
        border.width: 1
        opacity: root.lightMode || root.enabled ? 1.0 : 0.45

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: root.hoverOverlayColor()
            opacity: root.hoverOverlayOpacity()

            Behavior on opacity {
                NumberAnimation {
                    duration: root.down ? 80 : 120
                    easing.type: Easing.OutQuad
                }
            }
        }

        Behavior on color {
            ColorAnimation {
                duration: root.down ? 80 : 120
                easing.type: Easing.OutQuad
            }
        }

    }

    contentItem: Text {
        text: root.text
        color: root.textColor()
        font: root.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
