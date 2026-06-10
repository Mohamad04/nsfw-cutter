import QtQuick

Canvas {
    id: root

    property string name: ""
    property color iconColor: "#F8FAFC"
    property real strokeWidth: Math.max(1.4, Math.min(width, height) * 0.08)

    implicitWidth: 18
    implicitHeight: 18
    antialiasing: true

    onNameChanged: requestPaint()
    onIconColorChanged: requestPaint()
    onStrokeWidthChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)

        var w = width
        var h = height
        var s = Math.min(w, h)
        var ox = (w - s) / 2
        var oy = (h - s) / 2

        ctx.strokeStyle = root.iconColor
        ctx.fillStyle = root.iconColor
        ctx.lineWidth = root.strokeWidth
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.font = Math.round(s * 0.32) + "px sans-serif"
        ctx.textAlign = "center"
        ctx.textBaseline = "middle"

        function x(v) { return ox + v * s }
        function y(v) { return oy + v * s }
        function line(x1, y1, x2, y2) {
            ctx.beginPath()
            ctx.moveTo(x(x1), y(y1))
            ctx.lineTo(x(x2), y(y2))
            ctx.stroke()
        }
        function poly(points, fill) {
            ctx.beginPath()
            ctx.moveTo(x(points[0][0]), y(points[0][1]))
            for (var i = 1; i < points.length; i += 1)
                ctx.lineTo(x(points[i][0]), y(points[i][1]))
            ctx.closePath()
            if (fill) ctx.fill()
            else ctx.stroke()
        }
        function rect(rx, ry, rw, rh, fill) {
            ctx.beginPath()
            ctx.rect(x(rx), y(ry), rw * s, rh * s)
            if (fill) ctx.fill()
            else ctx.stroke()
        }
        function circle(cx, cy, radius, fill) {
            ctx.beginPath()
            ctx.arc(x(cx), y(cy), radius * s, 0, Math.PI * 2)
            if (fill) ctx.fill()
            else ctx.stroke()
        }
        function roundRect(rx, ry, rw, rh, rr, fill) {
            var px = x(rx)
            var py = y(ry)
            var pw = rw * s
            var ph = rh * s
            var pr = Math.min(rr * s, pw / 2, ph / 2)
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
            if (fill) ctx.fill()
            else ctx.stroke()
        }

        switch (root.name) {
        case "play":
            poly([[0.34, 0.24], [0.34, 0.76], [0.76, 0.50]], true)
            break
        case "pause":
            rect(0.30, 0.24, 0.14, 0.52, true)
            rect(0.56, 0.24, 0.14, 0.52, true)
            break
        case "rewind5":
            ctx.lineWidth = Math.max(root.strokeWidth, s * 0.075)
            line(0.52, 0.25, 0.30, 0.50)
            line(0.30, 0.50, 0.52, 0.75)
            line(0.73, 0.25, 0.51, 0.50)
            line(0.51, 0.50, 0.73, 0.75)
            ctx.globalAlpha = 0.12
            roundRect(0.58, 0.52, 0.30, 0.30, 0.045, true)
            ctx.globalAlpha = 1.0
            ctx.lineWidth = Math.max(1, s * 0.045)
            roundRect(0.58, 0.52, 0.30, 0.30, 0.045, false)
            ctx.font = "800 " + Math.round(s * 0.24) + "px sans-serif"
            ctx.fillText("5", x(0.73), y(0.675))
            break
        case "forward5":
            ctx.lineWidth = Math.max(root.strokeWidth, s * 0.075)
            line(0.25, 0.25, 0.47, 0.50)
            line(0.47, 0.50, 0.25, 0.75)
            line(0.46, 0.25, 0.68, 0.50)
            line(0.68, 0.50, 0.46, 0.75)
            ctx.globalAlpha = 0.12
            roundRect(0.58, 0.52, 0.30, 0.30, 0.045, true)
            ctx.globalAlpha = 1.0
            ctx.lineWidth = Math.max(1, s * 0.045)
            roundRect(0.58, 0.52, 0.30, 0.30, 0.045, false)
            ctx.font = "800 " + Math.round(s * 0.24) + "px sans-serif"
            ctx.fillText("5", x(0.73), y(0.675))
            break
        case "volume":
            poly([[0.15, 0.42], [0.32, 0.42], [0.52, 0.25], [0.52, 0.75], [0.32, 0.58], [0.15, 0.58]], false)
            ctx.beginPath()
            ctx.arc(x(0.54), y(0.50), s * 0.17, -0.65, 0.65)
            ctx.stroke()
            ctx.beginPath()
            ctx.arc(x(0.54), y(0.50), s * 0.29, -0.65, 0.65)
            ctx.stroke()
            break
        case "mute":
            poly([[0.15, 0.42], [0.32, 0.42], [0.52, 0.25], [0.52, 0.75], [0.32, 0.58], [0.15, 0.58]], false)
            line(0.66, 0.36, 0.86, 0.64)
            line(0.86, 0.36, 0.66, 0.64)
            break
        case "fullscreen":
            line(0.20, 0.40, 0.20, 0.20)
            line(0.20, 0.20, 0.40, 0.20)
            line(0.60, 0.20, 0.80, 0.20)
            line(0.80, 0.20, 0.80, 0.40)
            line(0.80, 0.60, 0.80, 0.80)
            line(0.80, 0.80, 0.60, 0.80)
            line(0.40, 0.80, 0.20, 0.80)
            line(0.20, 0.80, 0.20, 0.60)
            break
        case "folder":
        case "open":
            ctx.beginPath()
            ctx.moveTo(x(0.12), y(0.34))
            ctx.lineTo(x(0.38), y(0.34))
            ctx.lineTo(x(0.46), y(0.42))
            ctx.lineTo(x(0.88), y(0.42))
            ctx.lineTo(x(0.82), y(0.78))
            ctx.lineTo(x(0.12), y(0.78))
            ctx.closePath()
            ctx.stroke()
            line(0.12, 0.34, 0.12, 0.72)
            break
        case "chevronDown":
            line(0.28, 0.40, 0.50, 0.62)
            line(0.50, 0.62, 0.72, 0.40)
            break
        case "chevronUp":
            line(0.28, 0.60, 0.50, 0.38)
            line(0.50, 0.38, 0.72, 0.60)
            break
        case "sparkle":
            ctx.lineWidth = Math.max(root.strokeWidth, s * 0.06)
            poly([[0.50, 0.12], [0.58, 0.38], [0.84, 0.50], [0.58, 0.62], [0.50, 0.88], [0.42, 0.62], [0.16, 0.50], [0.42, 0.38]], false)
            line(0.76, 0.15, 0.76, 0.28)
            line(0.70, 0.215, 0.83, 0.215)
            line(0.24, 0.72, 0.24, 0.84)
            line(0.18, 0.78, 0.30, 0.78)
            break
        case "cc":
            rect(0.13, 0.24, 0.74, 0.52, false)
            ctx.font = Math.round(s * 0.27) + "px sans-serif"
            ctx.fillText("CC", x(0.50), y(0.51))
            break
        case "sun":
            circle(0.50, 0.50, 0.16, false)
            for (var ray = 0; ray < 8; ray += 1) {
                var angle = Math.PI * 2 * ray / 8
                var sx = 0.50 + Math.cos(angle) * 0.28
                var sy = 0.50 + Math.sin(angle) * 0.28
                var ex = 0.50 + Math.cos(angle) * 0.39
                var ey = 0.50 + Math.sin(angle) * 0.39
                line(sx, sy, ex, ey)
            }
            break
        case "moon":
            ctx.beginPath()
            ctx.arc(x(0.56), y(0.48), s * 0.28, 0.65 * Math.PI, 1.8 * Math.PI)
            ctx.arc(x(0.68), y(0.40), s * 0.25, 1.7 * Math.PI, 0.55 * Math.PI, true)
            ctx.closePath()
            ctx.fill()
            break
        case "settings":
            circle(0.50, 0.50, 0.13, false)
            for (var tooth = 0; tooth < 8; tooth += 1) {
                var a = Math.PI * 2 * tooth / 8
                line(0.50 + Math.cos(a) * 0.25, 0.50 + Math.sin(a) * 0.25,
                     0.50 + Math.cos(a) * 0.36, 0.50 + Math.sin(a) * 0.36)
            }
            break
        case "scissors":
            circle(0.30, 0.70, 0.12, false)
            circle(0.50, 0.72, 0.10, false)
            line(0.40, 0.62, 0.78, 0.24)
            line(0.42, 0.62, 0.82, 0.74)
            line(0.38, 0.62, 0.22, 0.34)
            break
        case "eye":
            ctx.beginPath()
            ctx.moveTo(x(0.10), y(0.50))
            ctx.bezierCurveTo(x(0.25), y(0.26), x(0.75), y(0.26), x(0.90), y(0.50))
            ctx.bezierCurveTo(x(0.75), y(0.74), x(0.25), y(0.74), x(0.10), y(0.50))
            ctx.closePath()
            ctx.stroke()
            circle(0.50, 0.50, 0.11, true)
            break
        case "shield":
            poly([[0.50, 0.12], [0.82, 0.24], [0.76, 0.62], [0.50, 0.86], [0.24, 0.62], [0.18, 0.24]], false)
            line(0.35, 0.51, 0.46, 0.62)
            line(0.46, 0.62, 0.66, 0.40)
            break
        case "warning":
            poly([[0.50, 0.14], [0.88, 0.82], [0.12, 0.82]], false)
            line(0.50, 0.38, 0.50, 0.58)
            circle(0.50, 0.70, 0.025, true)
            break
        case "trash":
            line(0.28, 0.30, 0.72, 0.30)
            line(0.38, 0.22, 0.62, 0.22)
            rect(0.32, 0.34, 0.36, 0.48, false)
            line(0.43, 0.44, 0.43, 0.72)
            line(0.57, 0.44, 0.57, 0.72)
            break
        case "export":
            line(0.50, 0.18, 0.50, 0.60)
            line(0.34, 0.34, 0.50, 0.18)
            line(0.66, 0.34, 0.50, 0.18)
            rect(0.22, 0.58, 0.56, 0.24, false)
            break
        case "markerStart":
            line(0.28, 0.18, 0.28, 0.82)
            poly([[0.36, 0.32], [0.72, 0.50], [0.36, 0.68]], true)
            break
        case "markerEnd":
            line(0.72, 0.18, 0.72, 0.82)
            poly([[0.64, 0.32], [0.28, 0.50], [0.64, 0.68]], true)
            break
        case "list":
            circle(0.20, 0.30, 0.035, true)
            circle(0.20, 0.50, 0.035, true)
            circle(0.20, 0.70, 0.035, true)
            line(0.32, 0.30, 0.80, 0.30)
            line(0.32, 0.50, 0.80, 0.50)
            line(0.32, 0.70, 0.80, 0.70)
            break
        case "history":
            ctx.beginPath()
            ctx.arc(x(0.52), y(0.52), s * 0.30, 0.15 * Math.PI, 1.75 * Math.PI)
            ctx.stroke()
            poly([[0.26, 0.25], [0.24, 0.48], [0.42, 0.36]], true)
            line(0.52, 0.34, 0.52, 0.54)
            line(0.52, 0.54, 0.66, 0.62)
            break
        default:
            circle(0.50, 0.50, 0.32, false)
            break
        }
    }
}
