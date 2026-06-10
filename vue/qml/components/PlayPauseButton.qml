pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Button {
    id: root

    property bool lightMode: false
    property bool playing: false
    property color iconColor: root.lightMode ? "#2563EB" : "#FFFFFF"

    implicitWidth: 96
    implicitHeight: 40
    hoverEnabled: true
    padding: 0
    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: 0
    scale: root.down ? 0.975 : 1.0
    opacity: root.enabled ? 1.0 : (root.lightMode ? 0.62 : 0.48)

    Accessible.name: root.playing ? "Pause playback" : "Play playback"

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

        function drawCenterFlare(ctx, y, alphaScale) {
            var w = backgroundCanvas.width
            var light = backgroundCanvas.lightModeState
            var flare = ctx.createLinearGradient(w * 0.34, 0, w * 0.66, 0)

            if (light) {
                flare.addColorStop(0.0, "rgba(37, 99, 235, 0.0)")
                flare.addColorStop(0.5, "rgba(37, 99, 235, " + (0.11 * alphaScale) + ")")
                flare.addColorStop(1.0, "rgba(37, 99, 235, 0.0)")
            } else {
                flare.addColorStop(0.0, "rgba(74, 179, 255, 0.0)")
                flare.addColorStop(0.48, "rgba(104, 203, 255, " + (0.95 * alphaScale) + ")")
                flare.addColorStop(0.52, "rgba(184, 238, 255, " + (0.95 * alphaScale) + ")")
                flare.addColorStop(1.0, "rgba(74, 179, 255, 0.0)")
            }

            ctx.strokeStyle = flare
            ctx.lineWidth = light ? 1.0 : 1.6
            ctx.beginPath()
            ctx.moveTo(w * 0.34, y)
            ctx.lineTo(w * 0.66, y)
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
            var radius = Math.min(18, h * 0.44)
            var inset = down ? 2.15 : 1.45

            ctx.save()
            ctx.globalAlpha = backgroundCanvas.enabledState ? 1.0 : 0.72

            if (light) {
                backgroundCanvas.roundedRect(ctx, inset, inset, w - inset * 2, h - inset * 2, radius)
                ctx.shadowColor = down ? "rgba(37, 99, 235, 0.08)" : (active ? "rgba(37, 99, 235, 0.14)" : "rgba(15, 23, 42, 0.09)")
                ctx.shadowBlur = active ? 5 : 4
                ctx.shadowOffsetY = down ? 1 : 3

                var lightFill = ctx.createLinearGradient(0, inset, 0, h - inset)
                lightFill.addColorStop(0.0, backgroundCanvas.enabledState ? (down ? "#DBEAFE" : (active ? "#EAF2FF" : "#FFFFFF")) : "#F1F5F9")
                lightFill.addColorStop(0.55, backgroundCanvas.enabledState ? (down ? "#D6E8FF" : (active ? "#F4F8FF" : "#F8FBFF")) : "#EDF2F8")
                lightFill.addColorStop(1.0, backgroundCanvas.enabledState ? (down ? "#CFE3FF" : (active ? "#F5F8FF" : "#F5F8FF")) : "#E8EEF7")
                ctx.fillStyle = lightFill
                ctx.fill()

                ctx.shadowBlur = 0
                ctx.shadowOffsetY = 0
                ctx.strokeStyle = backgroundCanvas.enabledState ? (down ? "#93C5FD" : (active ? "#93C5FD" : "#BFD7FF")) : "#CFD9E8"
                ctx.lineWidth = active ? 1.35 : 1.0
                ctx.stroke()

                backgroundCanvas.roundedRect(ctx, inset + 1.2, inset + 1.2, w - (inset + 1.2) * 2, h - (inset + 1.2) * 2, radius - 2)
                ctx.strokeStyle = down ? "rgba(37, 99, 235, 0.10)" : "rgba(255, 255, 255, 0.82)"
                ctx.lineWidth = 1
                ctx.stroke()

                backgroundCanvas.drawCenterFlare(ctx, inset + 0.6, active ? 1.0 : 0.62)
                backgroundCanvas.drawCenterFlare(ctx, h - inset - 0.6, active ? 0.88 : 0.50)

                ctx.restore()
                return
            }

            backgroundCanvas.roundedRect(ctx, 1.6, 1.6, w - 3.2, h - 3.2, radius)
            ctx.strokeStyle = active ? "rgba(70, 178, 255, 0.34)" : "rgba(77, 163, 244, 0.16)"
            ctx.lineWidth = active ? 5.2 : 3.0
            ctx.stroke()

            backgroundCanvas.roundedRect(ctx, inset, inset, w - inset * 2, h - inset * 2, radius)
            var fill = ctx.createLinearGradient(0, inset, 0, h - inset)
            fill.addColorStop(0.0, down ? "#050A14" : (active ? "#102744" : "#0C1D33"))
            fill.addColorStop(0.48, down ? "#071324" : (active ? "#0A1E36" : "#09172A"))
            fill.addColorStop(1.0, down ? "#040914" : (active ? "#061225" : "#06101F"))
            ctx.fillStyle = fill
            ctx.fill()

            ctx.shadowColor = active ? "rgba(76, 187, 255, 0.78)" : "rgba(64, 150, 238, 0.34)"
            ctx.shadowBlur = down ? 2 : (active ? 10 : 4)
            ctx.strokeStyle = backgroundCanvas.enabledState
                ? (down ? "rgba(80, 158, 238, 0.58)" : (active ? "rgba(88, 190, 255, 0.98)" : "rgba(93, 171, 252, 0.72)"))
                : "rgba(69, 101, 143, 0.44)"
            ctx.lineWidth = active ? 1.45 : 1.05
            ctx.stroke()
            ctx.shadowBlur = 0

            backgroundCanvas.roundedRect(ctx, inset + 1.35, inset + 1.35, w - (inset + 1.35) * 2, h - (inset + 1.35) * 2, radius - 2)
            ctx.strokeStyle = down ? "rgba(0, 0, 0, 0.24)" : "rgba(255, 255, 255, 0.055)"
            ctx.lineWidth = 1
            ctx.stroke()

            backgroundCanvas.drawCenterFlare(ctx, inset + 0.55, down ? 0.36 : (active ? 1.0 : 0.54))
            backgroundCanvas.drawCenterFlare(ctx, h - inset - 0.55, down ? 0.32 : (active ? 0.92 : 0.48))

            ctx.restore()
        }
    }

    contentItem: Canvas {
        id: iconCanvas

        property bool hoveredState: root.hovered
        property bool downState: root.down
        property bool enabledState: root.enabled
        property bool lightModeState: root.lightMode
        property bool playingState: root.playing
        property color iconColorState: root.iconColor

        anchors.fill: parent
        antialiasing: true

        onHoveredStateChanged: requestPaint()
        onDownStateChanged: requestPaint()
        onEnabledStateChanged: requestPaint()
        onLightModeStateChanged: requestPaint()
        onPlayingStateChanged: requestPaint()
        onIconColorStateChanged: requestPaint()
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

        function playIcon(ctx, cx, cy, size) {
            var left = cx - size * 0.34
            var top = cy - size * 0.40
            var right = cx + size * 0.42
            var bottom = cy + size * 0.40
            var mid = cy
            var r = size * 0.10

            ctx.beginPath()
            ctx.moveTo(left + r, top + r * 0.20)
            ctx.quadraticCurveTo(left, top, left, top + r)
            ctx.lineTo(left, bottom - r)
            ctx.quadraticCurveTo(left, bottom, left + r, bottom - r * 0.20)
            ctx.lineTo(right - r, mid + r * 0.45)
            ctx.quadraticCurveTo(right, mid, right - r, mid - r * 0.45)
            ctx.closePath()
            ctx.fill()
        }

        onPaint: {
            var ctx = getContext("2d")
            var w = width
            var h = height
            if (w <= 0 || h <= 0) return

            ctx.clearRect(0, 0, w, h)

            var light = iconCanvas.lightModeState
            var active = (iconCanvas.hoveredState || iconCanvas.downState) && iconCanvas.enabledState
            var down = iconCanvas.downState && iconCanvas.enabledState
            var scale = Math.min(w / 96, h / 40)
            var cx = w / 2 + (iconCanvas.playingState ? 0 : 1.2 * scale)
            var cy = h / 2 + (down ? 0.7 * scale : 0)
            var iconSize = 28 * scale

            ctx.save()
            ctx.fillStyle = iconCanvas.iconColorState
            ctx.globalAlpha = iconCanvas.enabledState ? 1.0 : 0.58
            ctx.shadowColor = light ? "rgba(37, 99, 235, 0.10)" : "rgba(149, 221, 255, 0.38)"
            ctx.shadowBlur = light ? 1 : (down ? 2 : (active ? 5 : 3))

            if (iconCanvas.playingState) {
                var barW = 5.2 * scale
                var barH = 21.0 * scale
                var gap = 5.2 * scale
                var y = cy - barH / 2

                iconCanvas.roundedRect(ctx, cx - gap / 2 - barW, y, barW, barH, 1.8 * scale)
                ctx.fill()
                iconCanvas.roundedRect(ctx, cx + gap / 2, y, barW, barH, 1.8 * scale)
                ctx.fill()
            } else {
                iconCanvas.playIcon(ctx, cx, cy, iconSize)
            }

            ctx.restore()
        }
    }
}
