import QtQuick
import QtQuick.Controls

Button {
    id: root

    property string variant: "secondary"
    // primary, secondary, success, danger, control, ghost

    property string size: "md"
    // sm, md, lg, icon

    property int radiusValue: size === "icon" ? 14 : 12

    implicitHeight: {
        if (size === "sm") return 36
        if (size === "lg") return 48
        if (size === "icon") return 56
        return 42
    }

    implicitWidth: {
        if (size === "sm") return 112
        if (size === "lg") return 180
        if (size === "icon") return 82
        return 140
    }

    font.pixelSize: size === "sm" ? 13 : 14
    font.weight: Font.Medium

    scale: down ? 0.985 : 1.0

    Behavior on scale {
        NumberAnimation {
            duration: 80
            easing.type: Easing.OutQuad
        }
    }

    function baseColor() {
        if (variant === "primary") return "#2563EB"
        if (variant === "success") return "#15803D"
        if (variant === "danger") return "#991B1B"
        if (variant === "control") return "#1E293B"
        if (variant === "ghost") return "#101826"
        return "#243244"
    }

    function hoverColor() {
        if (variant === "primary") return "#2A6CF0"
        if (variant === "success") return "#169247"
        if (variant === "danger") return "#AB2020"
        if (variant === "control") return "#243244"
        if (variant === "ghost") return "#121C2C"
        return "#2A3A4E"
    }

    function pressedColor() {
        if (variant === "primary") return "#1E40AF"
        if (variant === "success") return "#14532D"
        if (variant === "danger") return "#651313"
        if (variant === "control") return "#0F172A"
        if (variant === "ghost") return "#0B1324"
        return "#172033"
    }

    function borderColor() {
        if (variant === "primary") return "#3B82F6"
        if (variant === "success") return "#22C55E"
        if (variant === "danger") return "#EF4444"
        if (variant === "control") return "#334155"
        if (variant === "ghost") return "#334155"
        return "#334155"
    }

    function hoverOverlayOpacity() {
        if (!root.hovered || root.down || !root.enabled) return 0.0
        if (variant === "ghost") return 0.0
        if (variant === "primary") return 0.02
        if (variant === "success") return 0.018
        if (variant === "danger") return 0.018
        return 0.015
    }

    function hoverOverlayColor() {
        if (variant === "primary") return "#1E3A8A"
        if (variant === "success") return "#14532D"
        if (variant === "danger") return "#7F1D1D"
        if (variant === "ghost") return "#1E293B"
        return "#334155"
    }

    background: Rectangle {
        radius: root.radiusValue
        color: !root.enabled ? root.baseColor() : (root.down ? root.pressedColor() : (root.hovered ? root.hoverColor() : root.baseColor()))
        border.color: root.borderColor()
        border.width: 1
        opacity: root.enabled ? 1.0 : 0.45

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
        color: root.enabled ? "#F8FAFC" : "#64748B"
        font: root.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
