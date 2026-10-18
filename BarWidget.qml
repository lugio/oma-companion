import QtQuick
import qs.Commons
import qs.Ui
import "I18n.js" as I18n

// Alison dans la barre, sur le modèle des widgets d'Omarchy (BarWidget + WidgetButton) : la barre
// injecte `bar`, `moduleName` (l'identifiant du plugin) et `settings` (l'entrée de shell.json).
// Clic : ouvre ou ferme le panneau.
//
// Le widget montre le MÊME visage que le panneau : le service du plugin (le seul objet partagé
// entre les deux) porte `face` et `activity`, que le panneau y publie. Il ne s'anime que quand elle
// fait quelque chose — au repos, le dessin est fixe, pas de Canvas redessiné sur batterie.
BarWidget {
    id: root

    readonly property var shellApi: bar ? bar.shell : null
    readonly property var wake: shellApi && moduleName ? shellApi.serviceFor(moduleName) : null
    readonly property bool listening: wake !== null && wake.listening === true
    readonly property string name: setting("name", "Alison")
    LangLoader { id: langFile; lang: root.setting("language", "fr") }
    readonly property var tr: langFile.table
    readonly property string face: wake !== null && wake.face ? wake.face : (listening ? "idle" : "muted")
    readonly property string activity: wake !== null && wake.activity ? wake.activity : ""
    // Au repos, rien ne bouge : l'animation ne tourne que pendant un vrai travail.
    readonly property bool busy: face !== "idle" && face !== "muted" && face !== "ignored"
    readonly property int avatarSize: Math.max(14, Math.round((bar ? bar.barSize : 26) * 0.74))

    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        labelVisible: false
        hasVisualContent: true
        fixedWidth: root.avatarSize + Style.spaceReal(12)
        tooltipText: I18n.format(root.listening ? root.tr.widget_listening : root.tr.widget_open, root.name)
        onPressed: function (mouseButton) {
            if (root.shellApi && root.moduleName)
                root.shellApi.toggle(root.moduleName, "{}");
        }
        Avatar {
            anchors.centerIn: parent
            width: root.avatarSize
            height: root.avatarSize
            mood: root.face
            activity: root.activity
            foreground: root.bar ? root.bar.barForeground : Color.bar.text
            background: root.bar ? root.bar.background : Color.bar.background
            animate: root.busy || root.activity === "dream"
        }
    }
    Accessible.role: Accessible.Button
    Accessible.name: I18n.format(root.tr.widget_open, root.name)
}
