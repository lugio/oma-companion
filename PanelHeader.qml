import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// En-tête : avatar et état d'Alison, puis trois icônes. Journal et Réglages remplacent la
// conversation par leur vue ; un second clic sur la même icône ramène à la conversation.
// L'état dit la vérité sur le micro : « J'écoute » (avec le niveau de ta voix) seulement quand
// il est ouvert, « Micro coupé » sinon, avec la façon de le rouvrir.
RowLayout {
    id: header
    required property var app
    readonly property bool alert: app.face === "error"
    readonly property bool active: app.face !== "idle" && app.face !== "muted" && !alert
    spacing: Style.spacing.lg

    Avatar {
        mood: header.app.face
        activity: header.app.activity
        level: header.app.audioLevel
        // Un Item reste « visible » dans une fenêtre masquée : sans ça, l'avatar respirait et
        // redessinait son Canvas en continu, panneau fermé.
        animate: header.app.opened
        Layout.preferredWidth: Style.space(76)
        Layout.preferredHeight: Style.space(76)
    }
    ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.xxs
        // QUI répond : le rôle s'il y en a un, elle sinon. Le mot d'éveil, lui, ne change jamais —
        // d'où la ligne discrète en dessous, qui rappelle que c'est toujours elle.
        Text {
            text: header.app.speaker
            color: Color.menu.text
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.title
            font.bold: true
        }
        // Sous le nom du rôle, un rappel que c'est toujours elle : le mot d'éveil ne change pas.
        Text {
            visible: header.app.role !== "" && header.app.roleLabel !== ""
            text: header.app.t("under_role", header.app.companionName, header.app.roleLabel)
            color: Color.menu.text
            opacity: 0.55
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
        }
        // Sélecteur de rôle : il appartient à l'IDENTITÉ, pas à la rangée du mode. C'est le SEUL
        // endroit où l'on choisit un rôle (Réglages › Rôles n'a que les fiches). Absent tant
        // qu'aucun rôle n'est installé : qui n'en veut pas ne voit jamais la notion.
        Loader {
            active: header.app.rolesAvailable.length > 0 && header.app.provider === "omarchy"
            visible: active
            sourceComponent: Dropdown {
                showLabel: false
                implicitWidth: Style.space(150)
                value: header.app.role
                options: [{ value: "", label: header.app.t("role_self_named", header.app.companionName) }].concat(
                    header.app.rolesAvailable.map(function (r) { return { value: r.name, label: r.label }; }))
                fontFamily: Style.font.menuFamily
                onChanged: function (picked) { header.app.setSetting("role", picked); }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(8)
            // Niveau de ta voix, visible seulement micro ouvert.
            Row {
                visible: header.app.mood === "listening"
                Layout.alignment: Qt.AlignVCenter
                spacing: Style.space(2)
                Layout.preferredHeight: Style.space(12)
                Repeater {
                    model: [0.55, 1, 0.75, 0.4]
                    Rectangle {
                        required property real modelData
                        anchors.bottom: parent.bottom
                        width: Style.space(3)
                        height: Math.max(Style.space(3), Style.space(12) * Math.min(1, header.app.audioLevel * 2.2) * modelData)
                        radius: Style.space(1)
                        color: Color.accent
                        Behavior on height { NumberAnimation { duration: 80 } }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: header.app.connected ? header.app.statusText : header.app.tr.status_connecting
                color: header.alert ? Color.urgent : (header.active ? Color.accent : Color.menu.text)
                opacity: header.alert || header.active ? 1 : 0.65
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.body
            }
        }
    }
    // Nouvelle conversation et Supprimer (18/10) : sur le fil, pas cachés dans les Réglages. Supprimer
    // demande un second clic (4 s) : il retire aussi les lignes de la conversation des notes du jour.
    property bool confirmDelete: false
    readonly property bool canReset: app.view === "chat" && app.messageCount > 0 && !app.busy
    Timer {
        interval: 4000
        running: header.confirmDelete
        onTriggered: header.confirmDelete = false
    }
    Button {
        visible: header.app.view === "chat" && header.app.messageCount > 0
        enabled: header.canReset
        opacity: enabled ? 1 : 0.45
        iconText: "\uf067"
        tooltipText: header.app.tr.new_conversation
        focusable: true
        Accessible.name: tooltipText
        foreground: Color.menu.text
        onClicked: {
            header.confirmDelete = false;
            header.app.send("clear");
            header.app.actionText = "";
        }
    }
    Button {
        visible: header.app.view === "chat" && header.app.messageCount > 0
        enabled: header.canReset
        opacity: enabled ? 1 : 0.45
        iconText: "\uf1f8"
        tooltipText: header.confirmDelete ? header.app.tr.header_delete_confirm : header.app.tr.header_delete
        focusable: true
        Accessible.name: tooltipText
        selected: header.confirmDelete
        foreground: header.confirmDelete ? Color.urgent : Color.menu.text
        onClicked: {
            if (!header.confirmDelete) {
                header.confirmDelete = true;
                return;
            }
            header.confirmDelete = false;
            header.app.send("delete_conversation");
            header.app.actionText = "";
        }
    }
    Button {
        iconText: ""
        tooltipText: header.app.view === "journal" ? header.app.tr.header_back : header.app.tr.header_journal
        focusable: true
        Accessible.name: tooltipText
        selected: header.app.view === "journal"
        foreground: Color.menu.text
        onClicked: header.app.showView("journal")
    }
    Button {
        iconText: ""
        tooltipText: header.app.view === "settings" ? header.app.tr.header_back : header.app.tr.header_settings
        focusable: true
        Accessible.name: tooltipText
        selected: header.app.view === "settings"
        foreground: Color.menu.text
        onClicked: header.app.showView("settings")
    }
    Button {
        iconText: ""
        tooltipText: header.app.tr.header_close
        focusable: true
        Accessible.name: tooltipText
        foreground: Color.menu.text
        onClicked: header.app.dismiss()
    }
}
