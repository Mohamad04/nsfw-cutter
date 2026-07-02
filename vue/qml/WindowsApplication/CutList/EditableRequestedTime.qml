import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../Shared"

FocusScope {
    id: root

    required property string fieldName
    required property string displayText
    property string editTextOnStart: displayText
    property bool canEdit: false
    property bool editing: false
    property bool invalid: false
    property bool lightMode: false
    property color textColor: "#F3F6FB"
    property color requestedColor: "#F59E3D"
    property color accentColor: "#2F7BFF"
    property var canApplyEdit: null

    signal requestedTimeEdited(string fieldName, real seconds)

    Layout.fillWidth: true
    implicitHeight: 20

    function parseEditableTimeSeconds(value) {
        var match = /^(\d+):([0-5]\d):([0-5]\d)(?:\.(\d{1,3}))?$/.exec(String(value || "").trim())
        if (match === null) return NaN

        var hours = Number(match[1])
        var minutes = Number(match[2])
        var seconds = Number(match[3])
        var milliseconds = 0
        if (match[4] !== undefined) {
            var millisText = (match[4] + "000").slice(0, 3)
            milliseconds = Number(millisText)
        }

        if (!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(seconds) || !Number.isFinite(milliseconds))
            return NaN
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    }

    function beginEdit() {
        if (!root.canEdit) return
        editInput.text = root.editTextOnStart.length > 0 ? root.editTextOnStart : root.displayText
        root.invalid = false
        root.editing = true
        editInput.forceActiveFocus()
        editInput.selectAll()
    }

    function commitEdit() {
        if (!root.editing) return

        var seconds = root.parseEditableTimeSeconds(editInput.text)
        var canApply = root.canApplyEdit !== null && root.canApplyEdit(root.fieldName, seconds)
        if (!canApply) {
            root.invalid = true
            editInput.forceActiveFocus()
            editInput.selectAll()
            return
        }

        root.invalid = false
        root.editing = false
        root.requestedTimeEdited(root.fieldName, seconds)
    }

    Text {
        anchors.fill: parent
        visible: !root.editing
        text: root.displayText
        color: root.requestedColor
        font.pixelSize: 11
        font.weight: Font.DemiBold
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }

    MouseArea {
        anchors.fill: parent
        enabled: !root.editing && root.canEdit
        hoverEnabled: true
        cursorShape: Qt.IBeamCursor
        onClicked: root.beginEdit()
        ToolTip.visible: containsMouse
        ToolTip.text: "Edit time"
    }

    Rectangle {
        anchors.fill: parent
        visible: root.editing
        radius: 4
        color: root.lightMode ? "#FFFFFF" : "#0F172A"
        border.color: root.invalid ? (root.lightMode ? "#DC2626" : "#F87171") : root.accentColor

        TextInput {
            id: editInput

            anchors.fill: parent
            anchors.leftMargin: 4
            anchors.rightMargin: 4
            text: root.editTextOnStart
            color: root.textColor
            selectionColor: root.lightMode ? "#BFDBFE" : "#2563EB"
            selectedTextColor: root.lightMode ? "#0F172A" : "#FFFFFF"
            font.pixelSize: 11
            font.weight: Font.DemiBold
            verticalAlignment: TextInput.AlignVCenter
            selectByMouse: true
            clip: true
            validator: RegularExpressionValidator {
                regularExpression: /^\d+:[0-5]\d:[0-5]\d(?:\.\d{0,3})?$/
            }
            onAccepted: root.commitEdit()
            onActiveFocusChanged: {
                if (!activeFocus && root.editing)
                    root.commitEdit()
            }
            Keys.onEscapePressed: function(event) {
                root.invalid = false
                root.editing = false
                event.accepted = true
            }
        }
    }
}

