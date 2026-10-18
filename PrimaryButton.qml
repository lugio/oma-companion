import QtQuick
import qs.Commons

// Bouton d'action principale, fond d'accent plein. Composant maison : le `Button` d'Omarchy
// repeint son fond au survol avec une teinte du texte, ce qui rendrait le libellé illisible
// sur un fond d'accent.
Rectangle {
    id: button
    property string label: ""
    property string hint: ""
    signal clicked
    implicitWidth: row.implicitWidth + Style.spacing.controlPaddingX * 2
    implicitHeight: Style.spacing.controlHeight + Style.space(4)
    radius: Style.cornerRadius
    color: mouse.pressed ? Qt.darker(Color.accent, 1.2) : (mouse.containsMouse || button.activeFocus ? Qt.lighter(Color.accent, 1.12) : Color.accent)
    opacity: enabled ? 1 : 0.45
    // Atteignable au clavier (Tab), avec un anneau de focus aux jetons du thème.
    activeFocusOnTab: enabled
    border.width: button.activeFocus ? Math.max(1, Style.focusBorderWidth) : 0
    border.color: Color.menu.text
    Keys.onReturnPressed: if (button.enabled) button.clicked()
    Keys.onEnterPressed: if (button.enabled) button.clicked()
    Keys.onSpacePressed: if (button.enabled) button.clicked()

    Row {
        id: row
        anchors.centerIn: parent
        spacing: Style.spacing.md
        Text {
            text: button.label
            color: Color.menu.background
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.body
            font.bold: true
        }
        Text {
            visible: button.hint !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: button.hint
            color: Color.menu.background
            opacity: 0.7
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        enabled: button.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: button.clicked()
    }
    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.onPressAction: clicked()
}
