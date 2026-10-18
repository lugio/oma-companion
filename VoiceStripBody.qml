import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Le contenu du bandeau de la voix : le visage, ce qu'elle a compris, sa réponse, le niveau du
// micro. Séparé de la fenêtre (VoiceStrip.qml) pour qu'un banc puisse le dessiner tel quel.
BorderSurface {
    id: body
    required property var app
    signal clicked

    // Une carte qui apparaît sous une main déjà en train de cliquer ne doit rien autoriser : les
    // deux boutons restent inertes une demi-seconde. Le bandeau surgit tout seul, l'utilisateur
    // n'a pas demandé à cliquer à cet instant précis.
    readonly property int armDelay: 500
    property bool armed: false
    Connections {
        target: body.app
        function onStripCardChanged() {
            body.armed = false;
            if (body.app.stripCard)
                armTimer.restart();
            else
                armTimer.stop();
        }
    }
    Timer {
        id: armTimer
        interval: body.armDelay
        onTriggered: body.armed = true
    }

    implicitHeight: content.implicitHeight + Style.space(20)
    radius: Style.cornerRadius
    color: Util.alpha(Color.menu.background, 0.97)
    borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))

    // Le corps entier ouvre le panneau — sauf quand une carte attend : là, ce sont ses boutons
    // qui comptent, et un clic de trop ne doit rien autoriser.
    MouseArea {
        anchors.fill: parent
        enabled: !body.app.stripCard
        cursorShape: Qt.PointingHandCursor
        onClicked: body.clicked()
    }

    RowLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.space(12)
        anchors.rightMargin: Style.space(12)
        spacing: Style.space(10)

        Avatar {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: Style.space(26)
            Layout.preferredHeight: Style.space(26)
            mood: body.app.face
            activity: body.app.activity
            level: body.app.audioLevel
            // Le plugin reste chargé en permanence : on ne compte pas sur la visibilité de la
             // fenêtre, on lit l'état du bandeau (comme `enabled: root.opened` de l'OSD du shell).
            animate: body.app.stripShown && body.app.mood !== "idle"
            foreground: Color.menu.text
            background: Color.menu.background
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.space(2)

            // Une action à valider : qui demande, quoi, et les deux boutons. Le panneau reste à
            // un clic pour lire l'action en entier (« détails »).
            Text {
                Layout.fillWidth: true
                visible: body.app.stripCard
                text: body.app.permissionHost !== ""
                      ? body.app.t("card_page", body.app.speaker.toUpperCase(), body.app.permissionHost)
                      : body.app.permissionOwn
                      ? body.app.t("card_ask", body.app.speaker.toUpperCase(), body.app.permissionTool)
                      : body.app.t("card_action", body.app.speaker.toUpperCase(), body.app.permissionTool)
                color: Color.accent
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                elide: Text.ElideRight
                maximumLineCount: 1
            }
            Text {
                Layout.fillWidth: true
                visible: body.app.stripCard
                text: body.app.permissionText
                color: Color.menu.text
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.body
                wrapMode: Text.Wrap
                elide: Text.ElideRight
                maximumLineCount: 4
            }
            RowLayout {
                Layout.topMargin: Style.space(6)
                visible: body.app.stripCard
                spacing: Style.space(8)
                Button {
                    text: body.app.permissionHost !== "" ? body.app.tr.card_read
                          : body.app.permissionOwn ? body.app.tr.card_allow : body.app.tr.card_run
                    bordered: true
                    enabled: body.armed
                    opacity: enabled ? 1 : 0.45
                    foreground: Color.accent
                    fontFamily: Style.font.menuFamily
                    onClicked: body.app.decide("allow")
                }
                Button {
                    text: body.app.tr.card_refuse_short
                    bordered: true
                    enabled: body.armed
                    opacity: enabled ? 1 : 0.45
                    foreground: Color.menu.text
                    fontFamily: Style.font.menuFamily
                    onClicked: body.app.decide("deny")
                }
                Text {
                    text: body.app.tr.details
                    color: Color.menu.text
                    opacity: 0.5
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.caption
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: body.clicked()
                    }
                }
            }
            // Ce qu'elle a compris — c'est ce qui manque le plus à la voix toute seule.
            Text {
                Layout.fillWidth: true
                visible: text !== "" && !body.app.stripCard
                text: body.app.stripYou
                color: Color.menu.text
                opacity: 0.6
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
                maximumLineCount: 1
            }
            // Sa réponse, coupée à trois lignes : le fil complet reste dans le panneau.
            Text {
                Layout.fillWidth: true
                visible: text !== "" && !body.app.stripCard
                text: body.app.stripHer
                color: Color.menu.text
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.body
                wrapMode: Text.Wrap
                elide: Text.ElideRight
                maximumLineCount: 3
            }
            // Niveau du micro pendant l'écoute : la preuve qu'il est ouvert, pas une décoration.
            Row {
                Layout.topMargin: Style.space(3)
                visible: body.app.mood === "listening"
                spacing: Style.space(2)
                Repeater {
                    model: 14
                    Rectangle {
                        required property int index
                        // Les barres du milieu suivent le niveau de plus près : sinon le tracé
                        // ressemble à une jauge, pas à une voix.
                        readonly property real weight: 0.35 + 0.65 * Math.sin(Math.PI * (index + 0.5) / 14)
                        width: Style.space(2)
                        radius: width / 2
                        height: Math.max(Style.space(2),
                                         Style.space(14) * Math.min(1, body.app.audioLevel * 1.6) * weight)
                        anchors.verticalCenter: parent.verticalCenter
                        color: Color.accent
                        Behavior on height {
                            NumberAnimation {
                                duration: 90
                            }
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: body.app.stripHint !== "" && !body.app.stripCard
                text: body.app.stripHint
                color: Color.menu.text
                opacity: 0.4
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }
    }
}
