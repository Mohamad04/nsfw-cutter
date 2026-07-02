pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../Shared"

Button {
    id: root

    property bool lightMode: false
    property bool forceHovered: false
    property url moonIconSource: Qt.resolvedUrl("../../../../assets/icons/theme-toggle-moon-icon-app.png")
    readonly property int moonIconWidth: Math.max(44, Math.min(52, Math.round(root.width - 12)))
    readonly property int moonIconHeight: Math.max(34, Math.min(40, Math.round(root.height - 6)))
    readonly property string actionLabel: root.lightMode ? "Switch to Dark Mode" : "Switch to Light Mode"

    implicitWidth: 64
    implicitHeight: 44
    hoverEnabled: true
    padding: 0
    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: 0
    scale: root.down ? 0.975 : 1.0
    opacity: root.enabled ? 1.0 : (root.lightMode ? 0.66 : 0.54)

    Accessible.name: root.actionLabel
    ToolTip.visible: root.hovered && !root.forceHovered
    ToolTip.text: root.actionLabel

    Behavior on scale {
        NumberAnimation {
            duration: 80
            easing.type: Easing.OutQuad
        }
    }

    Behavior on opacity {
        NumberAnimation {
            duration: 120
            easing.type: Easing.OutQuad
        }
    }

    background: Canvas {
        id: backgroundCanvas

        property bool hoveredState: root.hovered || root.forceHovered
        property bool downState: root.down
        property bool enabledState: root.enabled
        property bool lightModeState: root.lightMode

        anchors.fill: parent
        antialiasing: true

        onHoveredStateChanged: requestPaint()
        onDownStateChanged: requestPaint()
        onEnabledStateChanged: requestPaint()
        onLightModeStateChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()

        function roundedRect(ctx, x, y, w, h, r) {
            var radius = Math.min(r, w / 2, h / 2)
            ctx.beginPath()
            ctx.moveTo(x + radius, y)
            ctx.lineTo(x + w - radius, y)
            ctx.quadraticCurveTo(x + w, y, x + w, y + radius)
            ctx.lineTo(x + w, y + h - radius)
            ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h)
            ctx.lineTo(x + radius, y + h)
            ctx.quadraticCurveTo(x, y + h, x, y + h - radius)
            ctx.lineTo(x, y + radius)
            ctx.quadraticCurveTo(x, y, x + radius, y)
            ctx.closePath()
        }

        function capsulePath(ctx, x, y, w, h) {
            roundedRect(ctx, x, y, w, h, h / 2)
        }

        function rimGradient(ctx, light, active, down, x, y, w, h) {
            var rim = ctx.createLinearGradient(x, y, x + w, y + h)
            if (light) {
                rim.addColorStop(0.0, down ? "#93C5FD" : (active ? "#7DB7FF" : "#BFD7FF"))
                rim.addColorStop(0.38, down ? "#DBEAFE" : "#FFFFFF")
                rim.addColorStop(0.66, down ? "#93C5FD" : (active ? "#93C5FD" : "#D7E7FF"))
                rim.addColorStop(1.0, down ? "#7DB7FF" : "#BFD7FF")
            } else {
                rim.addColorStop(0.0, down ? "#1F5FBF" : "#2E74E6")
                rim.addColorStop(0.32, active ? "#80D9FF" : "#54A8FF")
                rim.addColorStop(0.50, active ? "#C9F4FF" : "#83CCFF")
                rim.addColorStop(0.72, active ? "#4CBFFF" : "#2F7BFF")
                rim.addColorStop(1.0, down ? "#163E7A" : "#235AAB")
            }
            return rim
        }

        function drawLinearFlare(ctx, y, alphaScale, light) {
            var w = backgroundCanvas.width
            var flare = ctx.createLinearGradient(w * 0.20, 0, w * 0.80, 0)

            if (light) {
                flare.addColorStop(0.0, "rgba(37, 99, 235, 0.0)")
                flare.addColorStop(0.44, "rgba(37, 99, 235, " + (0.14 * alphaScale) + ")")
                flare.addColorStop(0.50, "rgba(255, 255, 255, " + (0.76 * alphaScale) + ")")
                flare.addColorStop(0.56, "rgba(37, 99, 235, " + (0.14 * alphaScale) + ")")
                flare.addColorStop(1.0, "rgba(37, 99, 235, 0.0)")
            } else {
                flare.addColorStop(0.0, "rgba(28, 134, 255, 0.0)")
                flare.addColorStop(0.42, "rgba(40, 176, 255, " + (0.56 * alphaScale) + ")")
                flare.addColorStop(0.50, "rgba(207, 249, 255, " + (0.95 * alphaScale) + ")")
                flare.addColorStop(0.58, "rgba(40, 176, 255, " + (0.56 * alphaScale) + ")")
                flare.addColorStop(1.0, "rgba(28, 134, 255, 0.0)")
            }

            ctx.strokeStyle = flare
            ctx.lineWidth = light ? 1.0 : 1.35
            ctx.beginPath()
            ctx.moveTo(w * 0.20, y)
            ctx.lineTo(w * 0.80, y)
            ctx.stroke()
        }

        function drawSideGleams(ctx, light, alphaScale) {
            var w = backgroundCanvas.width
            var h = backgroundCanvas.height
            var color = light ? "rgba(37, 99, 235, " : "rgba(94, 197, 255, "

            ctx.strokeStyle = color + (0.15 * alphaScale) + ")"
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(7.5, h * 0.34)
            ctx.lineTo(7.5, h * 0.66)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(w - 7.5, h * 0.34)
            ctx.lineTo(w - 7.5, h * 0.66)
            ctx.stroke()
        }

        onPaint: {
            var ctx = getContext("2d")
            var w = width
            var h = height
            if (w <= 0 || h <= 0) return

            ctx.clearRect(0, 0, w, h)

            var active = (backgroundCanvas.hoveredState || backgroundCanvas.downState) && backgroundCanvas.enabledState
            var down = backgroundCanvas.downState && backgroundCanvas.enabledState
            var light = backgroundCanvas.lightModeState
            var disabled = !backgroundCanvas.enabledState
            var inset = down ? 2.25 : 1.45
            var bodyX = inset
            var bodyY = inset
            var bodyW = w - inset * 2
            var bodyH = h - inset * 2
            var innerInset = down ? 3.8 : 2.9

            ctx.save()
            ctx.globalAlpha = disabled ? 0.72 : 1.0

            backgroundCanvas.capsulePath(ctx, 1.2, 1.2, w - 2.4, h - 2.4)
            ctx.shadowColor = light
                ? (active ? "rgba(37, 99, 235, 0.18)" : "rgba(15, 23, 42, 0.10)")
                : (active ? "rgba(77, 195, 255, 0.62)" : "rgba(52, 148, 255, 0.28)")
            ctx.shadowBlur = disabled ? 0 : (down ? 2 : (active ? (light ? 7 : 11) : (light ? 5 : 5)))
            ctx.shadowOffsetY = light ? (down ? 1 : 3) : 0
            ctx.strokeStyle = light ? "rgba(191, 215, 255, 0.42)" : "rgba(54, 168, 255, 0.20)"
            ctx.lineWidth = light ? 1.2 : 2.6
            ctx.stroke()

            backgroundCanvas.capsulePath(ctx, bodyX, bodyY, bodyW, bodyH)
            var fill = ctx.createLinearGradient(0, bodyY, 0, bodyY + bodyH)
            if (light) {
                fill.addColorStop(0.0, disabled ? "#F1F5F9" : (down ? "#DBEAFE" : (active ? "#EAF2FF" : "#FFFFFF")))
                fill.addColorStop(0.45, disabled ? "#EDF2F8" : (down ? "#D8E8FF" : (active ? "#F7FAFF" : "#FBFDFF")))
                fill.addColorStop(1.0, disabled ? "#E5ECF5" : (down ? "#CFE3FF" : "#F5F8FF"))
            } else {
                fill.addColorStop(0.0, disabled ? "#0A1220" : (down ? "#050A14" : (active ? "#122A47" : "#0D2038")))
                fill.addColorStop(0.44, disabled ? "#07101D" : (down ? "#071322" : (active ? "#0A1E35" : "#09182B")))
                fill.addColorStop(1.0, disabled ? "#050B14" : (down ? "#040814" : (active ? "#061326" : "#050F1D")))
            }
            ctx.fillStyle = fill
            ctx.fill()

            ctx.shadowBlur = 0
            ctx.shadowOffsetY = 0
            ctx.strokeStyle = backgroundCanvas.rimGradient(ctx, light, active, down, bodyX, bodyY, bodyW, bodyH)
            ctx.lineWidth = active ? 1.45 : 1.05
            ctx.stroke()

            backgroundCanvas.capsulePath(ctx, bodyX + innerInset, bodyY + innerInset, bodyW - innerInset * 2, bodyH - innerInset * 2)
            var glass = ctx.createLinearGradient(0, bodyY + innerInset, 0, bodyY + bodyH - innerInset)
            if (light) {
                glass.addColorStop(0.0, down ? "rgba(37, 99, 235, 0.08)" : "rgba(255, 255, 255, 0.74)")
                glass.addColorStop(1.0, down ? "rgba(37, 99, 235, 0.10)" : "rgba(37, 99, 235, 0.045)")
            } else {
                glass.addColorStop(0.0, down ? "rgba(0, 0, 0, 0.16)" : "rgba(119, 190, 255, 0.060)")
                glass.addColorStop(1.0, down ? "rgba(0, 0, 0, 0.28)" : "rgba(0, 0, 0, 0.075)")
            }
            ctx.fillStyle = glass
            ctx.fill()
            ctx.strokeStyle = light
                ? (down ? "rgba(37, 99, 235, 0.11)" : "rgba(255, 255, 255, 0.72)")
                : (down ? "rgba(0, 0, 0, 0.38)" : "rgba(255, 255, 255, 0.055)")
            ctx.lineWidth = 1
            ctx.stroke()

            backgroundCanvas.drawLinearFlare(ctx, bodyY + 0.72, down ? 0.32 : (active ? 1.0 : 0.58), light)
            backgroundCanvas.drawLinearFlare(ctx, bodyY + bodyH - 0.72, down ? 0.28 : (active ? 0.74 : 0.40), light)
            backgroundCanvas.drawSideGleams(ctx, light, active ? 1.0 : 0.58)

            ctx.restore()
        }
    }

    contentItem: Item {
        id: iconLayer

        anchors.fill: parent

        Image {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: root.down ? 0.65 : 0
            width: root.moonIconWidth
            height: root.moonIconHeight
            visible: !root.lightMode
            source: root.moonIconSource
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            cache: true
            opacity: root.enabled ? 1.0 : 0.56
            sourceSize.width: 393
            sourceSize.height: 320
        }

        Canvas {
            id: sunCanvas

            property bool hoveredState: root.hovered || root.forceHovered
            property bool downState: root.down
            property bool enabledState: root.enabled

            anchors.fill: parent
            visible: root.lightMode
            antialiasing: true

            onHoveredStateChanged: requestPaint()
            onDownStateChanged: requestPaint()
            onEnabledStateChanged: requestPaint()
            onVisibleChanged: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()

            function drawSun(ctx, cx, cy, s) {
                var r = s * 0.19
                var rayInner = s * 0.33
                var rayOuter = s * 0.44

                ctx.beginPath()
                ctx.arc(cx, cy, r, 0, Math.PI * 2)
                ctx.stroke()

                for (var i = 0; i < 10; i += 1) {
                    var angle = Math.PI * 2 * i / 10
                    ctx.beginPath()
                    ctx.moveTo(cx + Math.cos(angle) * rayInner, cy + Math.sin(angle) * rayInner)
                    ctx.lineTo(cx + Math.cos(angle) * rayOuter, cy + Math.sin(angle) * rayOuter)
                    ctx.stroke()
                }

                ctx.save()
                ctx.globalAlpha *= 0.18
                ctx.beginPath()
                ctx.arc(cx, cy, s * 0.32, 0, Math.PI * 2)
                ctx.fill()
                ctx.restore()
            }

            onPaint: {
                var ctx = getContext("2d")
                var w = width
                var h = height
                if (w <= 0 || h <= 0) return

                ctx.clearRect(0, 0, w, h)

                var active = (sunCanvas.hoveredState || sunCanvas.downState) && sunCanvas.enabledState
                var down = sunCanvas.downState && sunCanvas.enabledState
                var s = Math.min(w, h) * 0.72
                var cx = w / 2
                var cy = h / 2 + (down ? 0.65 : 0)
                var iconColor = sunCanvas.enabledState ? "#2563EB" : "#7D8AA0"

                ctx.save()
                ctx.fillStyle = iconColor
                ctx.strokeStyle = iconColor
                ctx.lineWidth = Math.max(2.15, s * 0.092)
                ctx.lineCap = "round"
                ctx.lineJoin = "round"
                ctx.globalAlpha = sunCanvas.enabledState ? 1.0 : 0.62
                ctx.shadowColor = "rgba(37, 99, 235, 0.16)"
                ctx.shadowBlur = active ? 2 : 1

                sunCanvas.drawSun(ctx, cx, cy, s)
                ctx.restore()
            }
        }
    }
}

