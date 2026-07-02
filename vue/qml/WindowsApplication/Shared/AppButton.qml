import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Button {
    id: root

    property string variant: "secondary"
    // primary, secondary, success, danger, control, ghost

    property string size: "md"
    // sm, md, lg, icon

    property bool lightMode: false
    property string iconName: ""
    property url iconSource: ""
    property int iconSize: size === "sm" ? 16 : 18
    property int imageIconSize: iconSize
    property int imageIconWidth: imageIconSize
    property int imageIconHeight: imageIconSize
    property int imageSourceSize: 512
    property int imageSourceWidth: imageSourceSize
    property int imageSourceHeight: imageSourceSize
    property int radiusValue: size === "icon" ? 14 : 10
    property string accessibilityLabel: ""
    property bool active: false
    property color activeAccentColor: root.lightMode ? "#22C55E" : "#6EE7B7"
    readonly property bool hasImageIcon: String(root.iconSource).length > 0
    readonly property bool hasVectorIcon: root.iconName.length > 0 && !root.hasImageIcon
    readonly property bool hasIcon: root.hasImageIcon || root.hasVectorIcon

    Accessible.name: root.accessibilityLabel.length > 0 ? root.accessibilityLabel : root.text

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
        if (!root.enabled) return "#0B1423"
        if (variant === "primary") return "#0C3B88"
        if (variant === "success") return "#12613A"
        if (variant === "danger") return "#3A1620"
        if (variant === "control") return "#0D1B2E"
        if (variant === "ghost") return "#0A1423"
        return "#0D1B2E"
    }

    function hoverColor() {
        if (root.lightMode) {
            if (variant === "primary") return "#1D4ED8"
            if (variant === "success") return "#15803D"
            if (variant === "danger") return root.enabled ? "#B91C1C" : "#FEE2E2"
            if (variant === "control") return "#EFF6FF"
            return "#EFF6FF"
        }
        if (variant === "primary") return "#1558C8"
        if (variant === "success") return "#18864E"
        if (variant === "danger") return "#4F1F2B"
        if (variant === "control") return "#162944"
        if (variant === "ghost") return "#101D31"
        return "#162944"
    }

    function pressedColor() {
        if (root.lightMode) {
            if (variant === "primary") return "#1E40AF"
            if (variant === "success") return "#166534"
            if (variant === "danger") return root.enabled ? "#991B1B" : "#FEE2E2"
            if (variant === "control") return "#DBEAFE"
            return "#DBEAFE"
        }
        if (variant === "primary") return "#0A2E6C"
        if (variant === "success") return "#0F4D2F"
        if (variant === "danger") return "#30111A"
        if (variant === "control") return "#091220"
        if (variant === "ghost") return "#081120"
        return "#091220"
    }

    function borderColor() {
        if (root.active && root.enabled) return root.activeAccentColor
        if (root.lightMode) {
            if (!root.enabled && variant === "danger") return "#FCA5A5"
            if (!root.enabled) return "#CBD5E1"
            if (variant === "primary") return "#2563EB"
            if (variant === "success") return "#16A34A"
            if (variant === "danger") return "#DC2626"
            if (variant === "control") return root.hovered && root.enabled ? "#93C5FD" : "#CBD5E1"
            return root.hovered && root.enabled ? "#93C5FD" : "#CBD5E1"
        }
        if (!root.enabled) return "#223049"
        if (variant === "primary") return "#5AA4FF"
        if (variant === "success") return "#31D67C"
        if (variant === "danger") return "#7A3144"
        if (variant === "control") return "#28405F"
        if (variant === "ghost") return "#28405F"
        return "#28405F"
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
            return root.lightMode ? "#94A3B8" : "#8494AA"
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
        opacity: root.lightMode || root.enabled ? 1.0 : 0.72

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 1
            anchors.rightMargin: 1
            anchors.topMargin: 1
            height: 1
            radius: parent.radius
            color: "#FFFFFF"
            opacity: root.lightMode ? 0.28 : (root.enabled ? 0.08 : 0.03)
        }

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

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: root.activeAccentColor
            opacity: root.active && root.enabled ? (root.hovered ? 0.08 : 0.045) : 0.0

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

    contentItem: Item {
        RowLayout {
            visible: root.text.length > 0
            anchors.fill: parent
            anchors.leftMargin: root.hasIcon ? 10 : 12
            anchors.rightMargin: 12
            spacing: root.hasIcon && root.text.length > 0 ? 7 : 0

            Image {
                visible: root.hasImageIcon
                Layout.preferredWidth: root.imageIconWidth
                Layout.preferredHeight: root.imageIconHeight
                source: root.iconSource
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                cache: true
                opacity: root.enabled ? 1.0 : 0.45
                scale: root.down && root.enabled ? 0.96 : 1.0
                sourceSize.width: root.imageSourceWidth
                sourceSize.height: root.imageSourceHeight

                Behavior on scale {
                    NumberAnimation {
                        duration: 80
                        easing.type: Easing.OutQuad
                    }
                }
            }

            VectorIcon {
                visible: root.hasVectorIcon
                Layout.preferredWidth: root.iconSize
                Layout.preferredHeight: root.iconSize
                iconColor: root.textColor()
                name: root.iconName
                opacity: root.enabled ? 1.0 : 0.72
            }

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.text
                color: root.textColor()
                font: root.font
                horizontalAlignment: root.hasIcon ? Text.AlignLeft : Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }

        Image {
            visible: root.text.length === 0 && root.hasImageIcon
            anchors.centerIn: parent
            width: root.imageIconWidth
            height: root.imageIconHeight
            source: root.iconSource
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            cache: true
            opacity: root.enabled ? 1.0 : 0.45
            scale: root.down && root.enabled ? 0.96 : 1.0
            sourceSize.width: root.imageSourceWidth
            sourceSize.height: root.imageSourceHeight

            Behavior on scale {
                NumberAnimation {
                    duration: 80
                    easing.type: Easing.OutQuad
                }
            }
        }

        VectorIcon {
            visible: root.text.length === 0 && root.hasVectorIcon
            anchors.centerIn: parent
            width: root.iconSize
            height: root.iconSize
            iconColor: root.textColor()
            name: root.iconName
            opacity: root.enabled ? 1.0 : 0.72
        }
    }
}

