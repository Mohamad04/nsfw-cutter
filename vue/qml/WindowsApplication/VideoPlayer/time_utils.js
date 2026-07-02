.pragma library

function pad(value) {
    return value < 10 ? "0" + value : "" + value
}

function padMillis(value) {
    if (value < 10) return "00" + value
    if (value < 100) return "0" + value
    return "" + value
}

function formatTime(ms, includeMilliseconds) {
    if (!Number.isFinite(ms) || ms <= 0) return "00:00:00"
    var totalMilliseconds = Math.max(0, Math.round(ms))
    var totalSeconds = Math.floor(totalMilliseconds / 1000)
    var milliseconds = totalMilliseconds % 1000
    var hours = Math.floor(totalSeconds / 3600)
    var minutes = Math.floor((totalSeconds % 3600) / 60)
    var seconds = totalSeconds % 60
    var text = pad(hours) + ":" + pad(minutes) + ":" + pad(seconds)
    if (includeMilliseconds === true && milliseconds > 0) text += "." + padMillis(milliseconds)
    return text
}

function formatSeconds(seconds) {
    if (seconds === null || seconds === undefined || seconds === "") return ""
    var value = Number(seconds)
    if (!Number.isFinite(value)) return ""
    value = Math.max(0, value)
    var totalMilliseconds = Math.round(value * 1000)
    var totalSeconds = Math.floor(totalMilliseconds / 1000)
    var milliseconds = totalMilliseconds % 1000
    var hours = Math.floor(totalSeconds / 3600)
    var minutes = Math.floor((totalSeconds % 3600) / 60)
    var wholeSeconds = totalSeconds % 60
    var text = pad(hours) + ":" + pad(minutes) + ":" + pad(wholeSeconds)
    if (milliseconds > 0) text += "." + padMillis(milliseconds)
    return text
}

function parseTimeMs(timeText) {
    var parts = String(timeText).trim().split(":")
    if (parts.length !== 3) return -1
    var hours = Number(parts[0])
    var minutes = Number(parts[1])
    var seconds = Number(parts[2])
    if (!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(seconds)) return -1
    if (hours < 0 || minutes < 0 || minutes > 59 || seconds < 0 || seconds >= 60) return -1
    return ((hours * 3600) + (minutes * 60) + seconds) * 1000
}

function formatSignedDelta(seconds) {
    if (!Number.isFinite(seconds)) return "--"

    var roundedSeconds = Math.round(seconds)
    var sign = roundedSeconds >= 0 ? "+" : "-"
    var absoluteSeconds = Math.abs(roundedSeconds)
    var hours = Math.floor(absoluteSeconds / 3600)
    var minutes = Math.floor((absoluteSeconds % 3600) / 60)
    var wholeSeconds = absoluteSeconds % 60
    if (hours > 0)
        return sign + pad(hours) + ":" + pad(minutes) + ":" + pad(wholeSeconds)
    return sign + pad(minutes) + ":" + pad(wholeSeconds)
}
