import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Carte de validation, juste au-dessus de la saisie : l'agent propose, rien ne s'exécute
// avant « Exécuter ». Sert aussi aux propositions d'action des moteurs hors agent Omarchy.
// Bordure fine d'accent tout autour, jamais de bordure latérale seule.
Rectangle {
    id: card
    required property var app
    readonly property bool permission: app.permissionText !== ""
    // Page web (WebFetch) : on lit plutôt qu'on exécute, et le site peut devenir de confiance.
    readonly property bool page: permission && app.permissionHost !== ""
    visible: permission || app.actionText !== ""
    implicitHeight: column.implicitHeight + Style.space(24)
    radius: Style.cornerRadius
    color: Style.normalFill
    // Le cadre d'accent porte un sens (une validation attend) : jamais 0, même sur un thème sans bordures.
    border.width: Math.max(1, Style.normalBorderWidth)
    border.color: Color.accent

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Style.space(12)
        spacing: Style.spacing.lg

        Text {
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: card.page
                  ? card.app.t("card_page", card.app.speaker.toUpperCase(), card.app.permissionHost)
                  : card.app.permissionOwn
                  ? card.app.t("card_ask", card.app.speaker.toUpperCase(), card.app.permissionTool)
                  : card.permission
                  ? card.app.t("card_action", card.app.speaker.toUpperCase(), card.app.permissionTool)
                  : (card.app.tr.card_proposed || "")
            color: Color.accent
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: detail.implicitHeight + Style.space(14)
            radius: Style.cornerRadius
            color: Color.menu.background
            TextEdit {
                id: detail
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Style.space(8)
                text: card.permission ? card.app.permissionText : card.app.actionText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                color: Color.menu.text
                selectionColor: Style.selectionFill
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.body
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Style.spacing.lg
            PrimaryButton {
                // Elle ne « propose » pas une action quand c'est elle qui demande : elle demande
                // la permission de faire quelque chose. « Autoriser », pas « Exécuter ».
                label: card.page ? (card.app.tr.card_read || "")
                       : card.app.permissionOwn ? (card.app.tr.card_allow || "") : (card.app.tr.card_run || "")
                hint: card.permission ? (card.app.tr.card_run_hint || "") : ""
                enabled: card.permission || !card.app.busy
                onClicked: {
                    if (card.permission) {
                        card.app.decide("allow");
                    } else {
                        card.app.send("execute");
                        card.app.actionText = "";
                    }
                }
            }
            Button {
                visible: card.page
                text: card.app.t("card_always", card.app.permissionHost)
                focusable: true
                bordered: true
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                tooltipText: card.app.t("card_always_tip", card.app.permissionHost)
                onClicked: card.app.decide("allow_site")
            }
            // « Toujours ici » : la même famille d'action ne redemandera plus de cette conversation.
            Button {
                visible: card.permission && !card.page && card.app.permissionAction !== ""
                text: card.app.t("card_always_here", card.app.permissionAction)
                focusable: true
                bordered: true
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                tooltipText: card.app.t("card_always_here_tip", card.app.permissionAction)
                onClicked: card.app.decide("allow_always")
            }
            Button {
                text: card.permission ? (card.app.tr.card_refuse || "") : (card.app.tr.card_ignore || "")
                focusable: true
                bordered: true
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                onClicked: {
                    if (card.permission)
                        card.app.decide("deny");
                    else
                        card.app.actionText = "";
                }
            }
            Item { Layout.fillWidth: true }
        }
        // Sous les boutons, sur sa propre ligne : à côté de trois boutons, il s'écrasait en colonne.
        Text {
            Layout.fillWidth: true
            visible: card.permission
            text: (card.app.tr.card_timeout || "")
            color: Color.menu.text
            opacity: 0.55
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
        }
    }
}
