import QtQuick
import Quickshell
import Quickshell.Io

// Les textes du panneau pour une langue : `lang/<code>.json` du plugin, puis le fichier de
// l'utilisateur (~/.config/omarchy-companion/lang/<code>.json) par-dessus ; l'anglais bouche les
// trous clé par clé. Un fichier modifié est relu à chaud : un traducteur voit son travail sans
// redémarrer. Le moteur lit les mêmes fichiers (texts.py) et publie la liste des langues.
Item {
    id: loader
    property string lang: "fr"
    property var table: ({})
    property string wake: ""
    readonly property string pluginDir: Qt.resolvedUrl("lang/").toString().replace("file://", "")
    readonly property string userDir: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")) + "/omarchy-companion/lang/"

    function parse(view) {
        try {
            var text = view.text();
            return text ? JSON.parse(text) : ({});
        } catch (e) {
            return ({});
        }
    }
    function rebuild() {
        var en = parse(enFile), base = parse(baseFile), user = parse(userFile);
        table = Object.assign({}, en.panel || {}, base.panel || {}, user.panel || {});
        wake = user.wake || base.wake || en.wake || "";
    }
    FileView {
        id: enFile
        path: loader.pluginDir + "en.json"
        blockLoading: true
        printErrors: false
        onLoaded: loader.rebuild()
        onLoadFailed: loader.rebuild()
    }
    FileView {
        id: baseFile
        path: loader.pluginDir + loader.lang + ".json"
        blockLoading: true
        watchChanges: true
        printErrors: false
        onLoaded: loader.rebuild()
        onLoadFailed: loader.rebuild()
        onFileChanged: loader.rebuild()
    }
    FileView {
        id: userFile
        path: loader.userDir + loader.lang + ".json"
        blockLoading: true
        watchChanges: true
        printErrors: false
        onLoaded: loader.rebuild()
        onLoadFailed: loader.rebuild()
        onFileChanged: loader.rebuild()
    }
    Component.onCompleted: rebuild()
}
