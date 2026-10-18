import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Zone de saisie : champ, Envoyer, Stop pendant la voix et micro rond, l'action principale.
// À l'écoute, le micro montre une icône d'arrêt et un anneau dont l'épaisseur suit ta voix.
Rectangle {
    id: composer
    required property var app
    readonly property bool listening: app.mood === "listening"
    function focusInput() { field.forceActiveFocus(); }
    function setText(value) { field.text = value; field.forceActiveFocus(); }
    function sendTyped() {
        if (composer.app.submit(field.text))
            field.text = "";
    }
    implicitHeight: Style.space(58)
    radius: Style.cornerRadius
    color: Style.normalFill
    border.width: Style.normalBorderWidth
    border.color: Style.normalBorderColor

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(12)
        anchors.rightMargin: Style.space(7)
        spacing: Style.spacing.md

        QQC.TextField {
            id: field
            Layout.fillWidth: true
            placeholderText: composer.listening ? (composer.app.tr.composer_listening || "") : (composer.app.tr.composer_placeholder || "")
            placeholderTextColor: Color.muted
            color: Color.menu.text
            selectionColor: Style.selectionFill
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.body
            background: Item {}
            onAccepted: composer.sendTyped()
            // Le champ avale Entrée : il passe d'abord les raccourcis du panneau (Échap, Ctrl+Entrée).
            Keys.onPressed: event => composer.app.shortcut(event)
        }
        Button {
            iconText: ""
            tooltipText: (composer.app.tr.send || "")
            focusable: true
            Accessible.name: tooltipText
            foreground: Color.menu.text
            enabled: composer.app.connected && !composer.app.busy && !composer.listening && field.text.trim() !== ""
            opacity: enabled ? 1 : 0.35
            onClicked: composer.sendTyped()
        }
        Button {
            visible: composer.app.mood === "speaking"
            iconText: ""
            tooltipText: (composer.app.tr.stop_voice || "")
            focusable: true
            Accessible.name: tooltipText
            foreground: Color.menu.text
            onClicked: composer.app.send("stop_speak")
        }
        Rectangle {
            id: mic
            Layout.preferredWidth: Style.space(44)
            Layout.preferredHeight: Style.space(44)
            radius: width / 2
            color: micMouse.containsMouse || mic.activeFocus ? Qt.lighter(Color.accent, 1.12) : Color.accent
            opacity: micMouse.enabled ? 1 : 0.45
            // Anneau : l'épaisseur suit ta voix à l'écoute ; sinon il marque le focus clavier.
            border.width: composer.listening ? Style.space(2) + Math.round(Math.min(1, composer.app.audioLevel) * Style.space(4))
                                             : (mic.activeFocus ? Math.max(1, Style.focusBorderWidth) : 0)
            border.color: Color.menu.text
            activeFocusOnTab: micMouse.enabled
            Keys.onReturnPressed: composer.app.talk()
            Keys.onEnterPressed: composer.app.talk()
            Keys.onSpacePressed: composer.app.talk()
            Text {
                anchors.centerIn: parent
                text: composer.listening ? "" : ""
                color: Color.menu.background
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.iconLarge
            }
            MouseArea {
                id: micMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                enabled: composer.app.connected && !composer.app.busy
                onClicked: composer.app.talk()
            }
            Accessible.role: Accessible.Button
            Accessible.name: composer.listening ? (composer.app.tr.stop_listening || "") : (composer.app.tr.talk || "")
        }
    }
}
