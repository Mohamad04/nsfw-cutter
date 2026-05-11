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
        if (variant === "ghost") return "transparent"
        return "#243244"
    }

    function borderColor() {
        if (variant === "primary") return "#3B82F6"
        if (variant === "success") return "#22C55E"
        if (variant === "danger") return "#EF4444"
        if (variant === "control") return "#334155"
        if (variant === "ghost") return "#334155"
        return "#334155"
    }

    background: Rectangle {
        radius: root.radiusValue
        color: root.baseColor()
        border.color: root.borderColor()
        border.width: 1
        opacity: root.enabled ? 1.0 : 0.45

        // Subtle hover layer
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: "#FFFFFF"
            opacity: root.hovered ? 0.07 : 0.0

            Behavior on opacity {
                NumberAnimation {
                    duration: 120
                    easing.type: Easing.OutQuad
                }
            }
        }

        // Press layer
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: "#000000"
            opacity: root.down ? 0.14 : 0.0

            Behavior on opacity {
                NumberAnimation {
                    duration: 80
                    easing.type: Easing.OutQuad
                }
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