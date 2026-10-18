import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Bandeau de la voix : ce qu'on voit quand Alison écoute et répond SANS ouvrir le grand panneau.
//
// Pourquoi : « Salut Alison » posait un voile sur tout le bureau et prenait le clavier, pour une
// phrase de trois mots (remarque du 19/09). Ici : pas de voile, pas de clavier pris — on
// continue à taper pendant qu'elle répond. Un clic ouvre le grand panneau.
//
// Ce bandeau est aussi la PREUVE VISIBLE que le micro est ouvert : la règle « le micro ne s'ouvre
// jamais sans qu'on le voie » ne change pas, c'est sa forme qui maigrit. Tant qu'il est là, le
// moteur s'autorise à écouter ; dès qu'il part, il coupe.
//
// Une fenêtre PAR ÉCRAN, comme les notifications du shell : cette preuve ne doit pas se poser sur
// l'écran que tu ne regardes pas (dock + 49 pouces).
Variants {
    id: screens
    required property var app
    model: Quickshell.screens

    PanelWindow {
        id: strip
        required property var modelData
        readonly property var app: screens.app

        // Placement au choix (réglage `voiceStrip`) : sous la barre à droite, ou en bas au centre.
        readonly property bool atBottom: app.voiceStrip === "bas"
        // Le shell donne aux plugins qui posent leurs propres fenêtres une vue de la barre ACTIVE
        // (`shell.bar`, services/PluginBarStateApi.qml) ; `barConfig` n'est que la configuration.
        readonly property string barPosition: app.shell && app.shell.bar && app.shell.bar.position
            ? String(app.shell.bar.position)
            : (app.shell && app.shell.barConfig ? String(app.shell.barConfig.position || "top") : "top")
        readonly property bool barVertical: barPosition === "left" || barPosition === "right"
        // Dégagement de la barre, comme les notifications : sa taille réelle quand elle est là, sa
        // taille par défaut sinon — le bandeau ne se pose jamais dessus.
        readonly property int liveBarSize: app.shell && app.shell.bar && !app.shell.bar.barHidden
            ? Math.max(0, app.shell.bar.barSize)
            : (barVertical ? Style.bar.sizeVertical : Style.bar.sizeHorizontal)
        readonly property int clearance: liveBarSize + Style.gapsOut

        screen: modelData
        visible: app.stripShown
        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }
        color: "transparent"
        WlrLayershell.namespace: "omarchy-companion-voix"
        WlrLayershell.layer: WlrLayer.Overlay
        // Jamais le clavier : tu continues à écrire dans ton éditeur pendant qu'elle parle.
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        // Seul le bandeau reçoit les clics ; ailleurs, la surface laisse tout passer vers le bureau.
        mask: Region {
            item: body
        }

        VoiceStripBody {
            id: body
            app: strip.app
            width: Math.min(Style.space(430), strip.width - Style.gapsOut * 2)
            anchors.right: strip.atBottom ? undefined : parent.right
            anchors.horizontalCenter: strip.atBottom ? parent.horizontalCenter : undefined
            anchors.top: strip.atBottom ? undefined : parent.top
            anchors.bottom: strip.atBottom ? parent.bottom : undefined
            anchors.topMargin: strip.barPosition === "top" ? strip.clearance : Style.gapsOut
            anchors.rightMargin: strip.barPosition === "right" ? strip.clearance : Style.gapsOut
            // En bas : au-dessus de la bande des OSD d'Omarchy (volume, luminosité), qui occupent
            // jusqu'à ~125 px du bas — et au-dessus d'une barre basse, s'il y en a une.
            anchors.bottomMargin: (strip.barPosition === "bottom" ? strip.clearance : Style.gapsOut)
                                  + Style.space(145)
            onClicked: strip.app.openFromStrip()
        }
    }
}
