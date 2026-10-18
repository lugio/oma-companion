import QtQuick
import Quickshell
import Quickshell.Io

// Service du mot d'éveil (wakeword.py dans l'environnement de voix). S'il s'arrête (micro perdu,
// mise en veille), il repart seul, trois fois au plus : au-delà, ou si la voix n'est pas installée,
// il attend l'installation depuis les Réglages, qui le relance (`restart`).
Item {
  id: root
  property var shell: null
  property var manifest: null
  property bool listening: false
  // État de l'avatar, publié par le panneau : le widget de barre n'a pas d'autre chemin vers lui
  // (la barre n'injecte que `bar`, `moduleName` et `settings`). Voir Companion.qml.
  property string face: "idle"
  property string activity: ""
  // Le panneau (seul à lire les réglages) dit si la voix répond dans le bandeau discret. Dans ce
  // cas le mot d'éveil n'ouvre plus rien : il rend la main au panneau, qui écoute en place.
  property bool stripMode: false
  signal woke
  // Parole coupée : « stop » entendu pendant qu'elle parlait (même micro, autre grammaire).
  signal barged(string word, string file)
  // Décision d'une carte à la voix : "allow" ou "deny", quand une action attend.
  signal decided(string kind, string word, int card)
  property string errorText: ""
  // Langue des messages du service (posée par le panneau ; le moteur du mot d'éveil lit la sienne
  // dans shell.json).
  property string lang: "fr"
  LangLoader { id: langFile; lang: root.lang }
  property int attempts: 0
  readonly property int maxAttempts: 3
  // Relance après l'installation de la voix depuis les Réglages.
  function restart() {
    errorText = ""
    attempts = 0
    retry.stop()
    stable.stop()
    listener.running = false
    listener.running = true
  }
  Process {
    id: listener
    running: true
    environment: ({PYTHONDONTWRITEBYTECODE: "1"})
    // Sans environnement de voix (« Installer la voix » pas encore cliqué), il n'y a rien à lancer :
    // on sort proprement (code 0) au lieu de trois « failed to start » au journal du shell sur une
    // installation neuve (audit de conformité du 21/09).
    command: ["sh", "-c", "[ -x \"$1\" ] || exit 0; exec \"$1\" \"$2\"", "alison-voix",
              (Quickshell.env("COMPANION_DATA_HOME") || Quickshell.env("HOME") + "/.local/share/omarchy-companion") + "/.venv/bin/python",
              Qt.resolvedUrl("wakeword.py").toString().replace("file://", "")]
    stdout: SplitParser {
      onRead: data => {
        try {
          var event = JSON.parse(data)
          if (event.event === "listening") {
            root.listening = event.value
            if (event.value) {
              root.errorText = ""   // il écoute : l'erreur d'avant ne vaut plus
              // Le compteur de relances ne repart à zéro qu'après une minute d'écoute stable :
              // un micro qui démarre puis plante aussitôt ne doit pas relancer sans fin (audit du 18/10).
              stable.restart()
            }
          }
          if (event.event === "error") root.errorText = event.text
          if (event.event === "barge") root.barged(String(event.word || ""), String(event.file || ""))
          if (event.event === "decide") root.decided(String(event.value || ""), String(event.word || ""), Number(event.card || 0))
          if (event.event === "wake") {
            if (root.stripMode) root.woke()
            else if (root.shell && root.manifest) root.shell.summon(root.manifest.id, '{"listen":true}')
          }
        } catch (e) { root.errorText = langFile.table.wake_service_error || "voice service error" }
      }
    }
    stderr: SplitParser { onRead: data => console.warn("Compagnon voix: " + data) }
    onExited: (exitCode, exitStatus) => {
      root.listening = false
      stable.stop()
      if (exitCode === 0 && exitStatus === 0)
        return          // sorti de lui-même sans erreur : pas de voix installée, rien à relancer
      if (root.attempts < root.maxAttempts) {
        root.attempts += 1
        retry.interval = 3000 * root.attempts
        retry.restart()
      } else if (root.errorText === "")
        root.errorText = langFile.table.wake_service_died || "voice service stopped"
    }
  }
  Timer {
    id: retry
    onTriggered: listener.running = true
  }
  Timer {
    id: stable
    interval: 60000
    onTriggered: root.attempts = 0
  }
}
