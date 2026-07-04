pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../Shared"

Button {
    id: root

    property bool lightMode: false
    property color iconColor: root.lightMode ? "#0F3B73" : "#F8FBFF"

    implicitWidth: 84
    implicitHeight: 36
    hoverEnabled: true
    padding: 0
    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: 0
    scale: root.down ? 0.975 : 1.0
    opacity: root.enabled ? 1.0 : (root.lightMode ? 0.64 : 0.56)

    Accessible.name: qsTr("Seek forward 5 seconds")

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

        property bool hoveredState: root.hovered
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

        onPaint: {
            var ctx = getContext("2d")
            var w = width
            var h = height
            if (w <= 0 || h <= 0) return

            ctx.clearRect(0, 0, w, h)

            var active = (backgroundCanvas.hoveredState || backgroundCanvas.downState) && backgroundCanvas.enabledState
            var down = backgroundCanvas.downState && backgroundCanvas.enabledState
            var light = backgroundCanvas.lightModeState
            var radius = Math.min(15, h * 0.42)
            var inset = down ? 2.0 : 1.25

            ctx.save()
            ctx.globalAlpha = backgroundCanvas.enabledState ? 1.0 : 0.72

            if (light) {
                backgroundCanvas.roundedRect(ctx, inset, inset, w - inset * 2, h - inset * 2, radius)
                ctx.shadowColor = down ? "rgba(37, 99, 235, 0.08)" : (active ? "rgba(37, 99, 235, 0.12)" : "rgba(15, 23, 42, 0.08)")
                ctx.shadowBlur = active ? 3 : 2
                ctx.shadowOffsetY = down ? 1 : 2

                var lightFill = ctx.createLinearGradient(0, inset, 0, h - inset)
                lightFill.addColorStop(0.0, backgroundCanvas.enabledState ? (down ? "#DBEAFE" : (active ? "#EAF2FF" : "#FFFFFF")) : "#F1F5F9")
                lightFill.addColorStop(1.0, backgroundCanvas.enabledState ? (down ? "#CFE3FF" : (active ? "#F5F8FF" : "#F5F8FF")) : "#E8EEF7")
                ctx.fillStyle = lightFill
                ctx.fill()

                ctx.shadowBlur = 0
                ctx.shadowOffsetY = 0
                ctx.strokeStyle = backgroundCanvas.enabledState ? (down ? "#93C5FD" : (active ? "#9FC9FF" : "#BFD7FF")) : "#CFD9E8"
                ctx.lineWidth = active ? 1.25 : 1.0
                ctx.stroke()

                backgroundCanvas.roundedRect(ctx, inset + 1.1, inset + 1.1, w - (inset + 1.1) * 2, h - (inset + 1.1) * 2, radius - 2)
                ctx.strokeStyle = down ? "rgba(37, 99, 235, 0.10)" : "rgba(255, 255, 255, 0.78)"
                ctx.lineWidth = 1
                ctx.stroke()

                ctx.strokeStyle = active ? "rgba(37, 99, 235, 0.16)" : "rgba(37, 99, 235, 0.08)"
                ctx.lineWidth = 1
                ctx.beginPath()
                ctx.moveTo(w * 0.34, h - inset - 0.65)
                ctx.lineTo(w * 0.66, h - inset - 0.65)
                ctx.stroke()

                ctx.restore()
                return
            }

            backgroundCanvas.roundedRect(ctx, 1.5, 1.5, w - 3, h - 3, radius)
            ctx.strokeStyle = active ? "rgba(98, 192, 255, 0.36)" : "rgba(64, 150, 238, 0.14)"
            ctx.lineWidth = active ? 5.0 : 2.6
            ctx.stroke()

            backgroundCanvas.roundedRect(ctx, inset, inset, w - inset * 2, h - inset * 2, radius)
            var fill = ctx.createLinearGradient(0, inset, 0, h - inset)
            fill.addColorStop(0.0, down ? "#050A14" : "#0B1D34")
            fill.addColorStop(0.48, down ? "#071426" : "#0A172A")
            fill.addColorStop(1.0, down ? "#040913" : "#06101F")
            ctx.fillStyle = fill
            ctx.fill()

            ctx.shadowColor = active ? "rgba(91, 190, 255, 0.75)" : "rgba(64, 150, 238, 0.26)"
            ctx.shadowBlur = active ? 7 : 2
            ctx.strokeStyle = active ? "rgba(99, 190, 255, 0.95)" : "rgba(85, 161, 241, 0.56)"
            ctx.lineWidth = active ? 1.35 : 1.0
            ctx.stroke()
            ctx.shadowBlur = 0

            backgroundCanvas.roundedRect(ctx, inset + 1.2, inset + 1.2, w - (inset + 1.2) * 2, h - (inset + 1.2) * 2, radius - 2)
            ctx.strokeStyle = "rgba(255, 255, 255, 0.06)"
            ctx.lineWidth = 1
            ctx.stroke()

            var topGlow = ctx.createLinearGradient(w * 0.34, 0, w * 0.66, 0)
            topGlow.addColorStop(0.0, "rgba(61, 171, 255, 0.0)")
            topGlow.addColorStop(0.5, active ? "rgba(117, 218, 255, 0.95)" : "rgba(84, 187, 255, 0.38)")
            topGlow.addColorStop(1.0, "rgba(61, 171, 255, 0.0)")
            ctx.strokeStyle = topGlow
            ctx.lineWidth = active ? 1.8 : 1.0
            ctx.beginPath()
            ctx.moveTo(w * 0.34, inset + 0.45)
            ctx.lineTo(w * 0.66, inset + 0.45)
            ctx.stroke()

            var bottomGlow = ctx.createLinearGradient(w * 0.34, 0, w * 0.66, 0)
            bottomGlow.addColorStop(0.0, "rgba(61, 171, 255, 0.0)")
            bottomGlow.addColorStop(0.5, active ? "rgba(91, 206, 255, 0.90)" : "rgba(70, 176, 255, 0.32)")
            bottomGlow.addColorStop(1.0, "rgba(61, 171, 255, 0.0)")
            ctx.strokeStyle = bottomGlow
            ctx.lineWidth = active ? 1.8 : 1.0
            ctx.beginPath()
            ctx.moveTo(w * 0.34, h - inset - 0.45)
            ctx.lineTo(w * 0.66, h - inset - 0.45)
            ctx.stroke()

            ctx.restore()
        }
    }

    contentItem: Canvas {
        id: iconCanvas

        property bool hoveredState: root.hovered
        property bool downState: root.down
        property bool enabledState: root.enabled
        property bool lightModeState: root.lightMode
        property color iconColorState: root.iconColor

        anchors.fill: parent
        antialiasing: true

        onHoveredStateChanged: requestPaint()
        onDownStateChanged: requestPaint()
        onEnabledStateChanged: requestPaint()
        onLightModeStateChanged: requestPaint()
        onIconColorStateChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()

        function mapX(value, scale, offsetX) {
            return offsetX + value * scale
        }

        function mapY(value, scale, offsetY) {
            return offsetY + value * scale
        }

        function chevron(ctx, x1, y1, x2, y2, x3, y3, scale, offsetX, offsetY) {
            ctx.beginPath()
            ctx.moveTo(iconCanvas.mapX(x1, scale, offsetX), iconCanvas.mapY(y1, scale, offsetY))
            ctx.lineTo(iconCanvas.mapX(x2, scale, offsetX), iconCanvas.mapY(y2, scale, offsetY))
            ctx.lineTo(iconCanvas.mapX(x3, scale, offsetX), iconCanvas.mapY(y3, scale, offsetY))
            ctx.stroke()
        }

        function roundedRect(ctx, x, y, w, h, r, scale, offsetX, offsetY) {
            var px = iconCanvas.mapX(x, scale, offsetX)
            var py = iconCanvas.mapY(y, scale, offsetY)
            var pw = w * scale
            var ph = h * scale
            var pr = Math.min(r * scale, pw / 2, ph / 2)
            ctx.beginPath()
            ctx.moveTo(px + pr, py)
            ctx.lineTo(px + pw - pr, py)
            ctx.quadraticCurveTo(px + pw, py, px + pw, py + pr)
            ctx.lineTo(px + pw, py + ph - pr)
            ctx.quadraticCurveTo(px + pw, py + ph, px + pw - pr, py + ph)
            ctx.lineTo(px + pr, py + ph)
            ctx.quadraticCurveTo(px, py + ph, px, py + ph - pr)
            ctx.lineTo(px, py + pr)
            ctx.quadraticCurveTo(px, py, px + pr, py)
            ctx.closePath()
        }

        onPaint: {
            var ctx = getContext("2d")
            var w = width
            var h = height
            if (w <= 0 || h <= 0) return

            ctx.clearRect(0, 0, w, h)

            var scale = Math.min(w / 84, h / 36)
            var offsetX = (w - 84 * scale) / 2
            var offsetY = (h - 36 * scale) / 2 + (iconCanvas.downState ? 0.6 : 0)
            var alpha = iconCanvas.enabledState ? 1.0 : 0.64
            var active = (iconCanvas.hoveredState || iconCanvas.downState) && iconCanvas.enabledState
            var light = iconCanvas.lightModeState

            ctx.save()
            ctx.lineCap = "round"
            ctx.lineJoin = "round"
            ctx.globalAlpha = alpha

            ctx.strokeStyle = light ? (active ? "rgba(37, 99, 235, 0.14)" : "rgba(37, 99, 235, 0.07)") : (active ? "rgba(88, 192, 255, 0.34)" : "rgba(88, 192, 255, 0.12)")
            ctx.lineWidth = (light ? 7.4 : 8.6) * scale
            iconCanvas.chevron(ctx, 23.2, 10.4, 34.0, 18, 23.2, 25.6, scale, offsetX, offsetY)
            iconCanvas.chevron(ctx, 36.2, 10.4, 47.0, 18, 36.2, 25.6, scale, offsetX, offsetY)

            ctx.strokeStyle = iconCanvas.iconColorState
            ctx.lineWidth = 5.0 * scale
            iconCanvas.chevron(ctx, 23.2, 10.4, 34.0, 18, 23.2, 25.6, scale, offsetX, offsetY)
            iconCanvas.chevron(ctx, 36.2, 10.4, 47.0, 18, 36.2, 25.6, scale, offsetX, offsetY)

            iconCanvas.roundedRect(ctx, 52.8, 12.2, 20.4, 12.6, 4.3, scale, offsetX, offsetY)
            ctx.strokeStyle = light ? (active ? "rgba(37, 99, 235, 0.16)" : "rgba(37, 99, 235, 0.08)") : (active ? "rgba(94, 197, 255, 0.30)" : "rgba(94, 197, 255, 0.12)")
            ctx.lineWidth = (light ? 4.2 : 5.0) * scale
            ctx.stroke()

            iconCanvas.roundedRect(ctx, 52.8, 12.2, 20.4, 12.6, 4.3, scale, offsetX, offsetY)
            ctx.strokeStyle = iconCanvas.iconColorState
            ctx.lineWidth = 2.25 * scale
            ctx.stroke()

            var streak = ctx.createLinearGradient(iconCanvas.mapX(50.2, scale, offsetX), 0,
                                                  iconCanvas.mapX(55.4, scale, offsetX), 0)
            streak.addColorStop(0.0, light ? "rgba(37, 99, 235, 0.0)" : "rgba(91, 190, 255, 0.0)")
            streak.addColorStop(0.55, light ? (active ? "rgba(37, 99, 235, 0.20)" : "rgba(37, 99, 235, 0.10)") : (active ? "rgba(115, 218, 255, 0.78)" : "rgba(88, 190, 255, 0.32)"))
            streak.addColorStop(1.0, light ? "rgba(37, 99, 235, 0.22)" : "rgba(255, 255, 255, 0.82)")
            ctx.strokeStyle = streak
            ctx.lineWidth = 1.4 * scale
            ctx.beginPath()
            ctx.moveTo(iconCanvas.mapX(50.2, scale, offsetX), iconCanvas.mapY(12.2, scale, offsetY))
            ctx.lineTo(iconCanvas.mapX(55.4, scale, offsetX), iconCanvas.mapY(12.2, scale, offsetY))
            ctx.stroke()

            ctx.fillStyle = iconCanvas.iconColorState
            ctx.font = "800 " + Math.round(13.4 * scale) + "px sans-serif"
            ctx.textAlign = "center"
            ctx.textBaseline = "middle"
            ctx.fillText("5", iconCanvas.mapX(63.0, scale, offsetX), iconCanvas.mapY(18.9, scale, offsetY))

            ctx.restore()
        }
    }
}

