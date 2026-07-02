.pragma library
.import "time_utils.js" as TimeUtils

function numericCutSeconds(cut, secondsKey, timeKey) {
    if (!cut) return NaN

    var seconds = cut[secondsKey]
    if (seconds !== undefined && seconds !== null && seconds !== "") {
        var numeric = Number(seconds)
        if (Number.isFinite(numeric)) return numeric
    }

    var timeMs = TimeUtils.parseTimeMs(cut[timeKey])
    return timeMs >= 0 ? timeMs / 1000 : NaN
}

function cutRange(cut) {
    if (!cut) return { "valid": false, "start": 0, "end": 0 }

    var safeStart = numericCutSeconds(cut, "safeStartSeconds", "safeStart")
    var safeEnd = numericCutSeconds(cut, "safeEndSeconds", "safeEnd")
    if (Number.isFinite(safeStart) && Number.isFinite(safeEnd) && safeEnd > safeStart)
        return { "valid": true, "start": safeStart, "end": safeEnd }

    var requestedStart = numericCutSeconds(cut, "requestedStartSeconds", "start")
    var requestedEnd = numericCutSeconds(cut, "requestedEndSeconds", "end")
    if (Number.isFinite(requestedStart) && Number.isFinite(requestedEnd) && requestedEnd > requestedStart)
        return { "valid": true, "start": requestedStart, "end": requestedEnd }

    return { "valid": false, "start": 0, "end": 0 }
}

function requestedCutRange(cut) {
    if (!cut) return { "valid": false, "start": 0, "end": 0 }

    var requestedStart = numericCutSeconds(cut, "requestedStartSeconds", "start")
    var requestedEnd = numericCutSeconds(cut, "requestedEndSeconds", "end")
    if (Number.isFinite(requestedStart) && Number.isFinite(requestedEnd) && requestedEnd > requestedStart)
        return { "valid": true, "start": requestedStart, "end": requestedEnd }

    return cutRange(cut)
}

function clampedTimelineSeconds(value, durationMs) {
    if (!Number.isFinite(value) || !Number.isFinite(durationMs) || durationMs <= 0) return 0
    var durationSeconds = durationMs / 1000
    return Math.max(0, Math.min(value, durationSeconds))
}

function timelineX(seconds, trackWidth, durationMs) {
    if (!Number.isFinite(durationMs) || durationMs <= 0 || trackWidth <= 0) return 0
    return clampedTimelineSeconds(seconds, durationMs) / (durationMs / 1000) * trackWidth
}

function timelineSecondsAtX(trackX, trackWidth, durationMs) {
    if (!Number.isFinite(durationMs) || durationMs <= 0 || trackWidth <= 0) return 0
    var clampedX = Math.max(0, Math.min(trackX, trackWidth))
    return clampedX / trackWidth * (durationMs / 1000)
}

function markerSeconds(timeText, isSet) {
    if (!isSet) return NaN
    var timeMs = TimeUtils.parseTimeMs(timeText)
    return timeMs >= 0 ? timeMs / 1000 : NaN
}
