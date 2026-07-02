import QtQuick

Rectangle {
    id: root

    property string subtitleText: ""
    property bool lightMode: false

    width: Math.min((parent ? parent.width : 0) * 0.82, subtitleLabel.implicitWidth + 28)
    height: subtitleLabel.implicitHeight + 14
    radius: 10
    color: "#000000"
    opacity: root.subtitleText.length > 0 ? 0.78 : 0
    visible: opacity > 0
    z: 3

    Text {
        id: subtitleLabel

        anchors.centerIn: parent
        width: Math.min((root.parent ? root.parent.width : root.width) * 0.78, implicitWidth)
        text: root.subtitleText
        color: "#FFFFFF"
        font.pixelSize: 22
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.Wrap
        style: Text.Outline
        styleColor: "#000000"
    }
}
