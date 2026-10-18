import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "I18n.js" as I18n

// Panneau d'Alison : état, pont JSON-lines vers backend.py, fenêtre et assemblage.
// L'affichage vit dans les composants frères (PanelHeader, StatusChips, ChatView,
// ApprovalCard, Composer, HarnessLine, SettingsView, JournalView), qui lisent `app.*`
// et n'écrivent au moteur qu'à travers les fonctions ci-dessous.
Item {
    id: root
    property var shell: null
    property var manifest: null
    property var service: null
    // Identifiant lu dans le manifest injecté par le shell : jamais recopié en dur.
    readonly property string pluginId: manifest && manifest.id ? manifest.id : ""
    property string omarchyPath: Quickshell.env("OMARCHY_PATH")
    // Langue du panneau (réglage `language`) : tous les textes sont lus dans `tr`, jamais en dur.
    property string lang: "fr"
    // Les textes : un fichier par langue, relu à chaud (LangLoader). Liste des langues : du moteur.
    LangLoader { id: langFile; lang: root.lang }
    readonly property var tr: langFile.table
    property var languages: []
    function wakeOf(code) {
        for (var i = 0; i < languages.length; i++)
            if (languages[i].code === code)
                return languages[i].wake || "";
        return "";
    }
    function t(key, a, b, c) {
        return I18n.format(tr[key], a, b, c);
    }
    property bool opened: false
    property bool connected: false
    // Vue centrale : "chat" (conversation), "settings" (réglages) ou "journal".
    property string view: "chat"
    // Ouverture sur une vue explicite (captures, tests) : le micro ne s'ouvre jamais seul, même
    // quand l'état du moteur arrive après l'ouverture (moteur tout juste redémarré).
    property bool quietOpen: false
    property string mood: "idle"
    property real audioLevel: 0
    property string companionName: "Alison"
    property string provider: "omarchy"
    property string agentName: ""
    property string agentProblem: ""
    // Harnais réellement appliqué (agent + mode). Affiché tel quel : ne jamais le deviner ici.
    property string harness: ""
    // Lecture non filtrable (Codex) : dit par le moteur, jamais deviné dans le texte du harnais.
    property bool harnessUnsafe: false
    property bool streaming: false
    property string journalText: ""
    property string modelName: ""
    property string endpoint: "http://localhost:11434"
    property string wakePhrase: ""
    property bool voice: false
    property bool wakeEnabled: false
    property string mode: "chat"
    // Rôle actif ("" = elle-même) et rôles trouvés sur le disque, publiés par le moteur :
    // [{ name, label, description }]. Liste vide = aucun rôle installé, la notion ne s'affiche pas.
    property string role: ""
    property var rolesAvailable: []
    // Alison générique (18/10) : sa personnalité choisie, le savoir Omarchy, les rôles d'exemple,
    // le niveau du cerveau et l'assistant de première installation.
    property string personaText: ""
    property bool personaCustom: false
    property bool omarchyKnowledge: true
    property bool omarchySkill: false
    property var roleExamples: []
    property string brainLevel: ""
    property bool firstRun: false
    property bool setupDone: false
    property bool welcomeShown: false
    // Sauvegarde / restauration (Réglages › Sauvegarde).
    property var backupItems: []
    property var backupPreview: null
    property string backupPath: ""
    property string backupError: ""
    property string backupStatus: ""
    property string backupFolder: ""
    property string backupToken: ""
    // Résultat du dernier enregistrement de rôle depuis les Réglages : "" = réussi.
    property string roleSaveError: ""
    // Les rôles peuvent se poser des questions entre eux (lecture seule, un aller-retour).
    property bool delegation: true
    property int roleSaveCount: 0
    // Étiquette du rôle actif et modes qu'il laisse ouverts. Tout vient du moteur : le panneau ne
    // recalcule aucune restriction, sinon il afficherait une limite que le moteur n'applique pas
    // (les crans de mode étaient cliquables alors que le rôle les fermait — audit du 20/09).
    property string roleLabel: ""
    property var roleModes: []
    // Les trois accès (maison, courrier, comptabilité), tels que le MOTEUR les applique :
    // [{ key, configured, on, blocked, by }]. Le panneau n'en recalcule aucun — il afficherait
    // sinon une limite que le moteur n'applique pas.
    property var access: []
    // Où se déposent les rôles (dit par le moteur : lui seul connaît le chemin standard).
    property string rolesFolder: ""
    // QUI répond : le rôle s'il y en a un, elle sinon. Le mot d'éveil et la voix ne changent pas —
    // on l'appelle toujours par son nom.
    readonly property string speaker: role && roleLabel ? roleLabel : companionName
    function modeClosed(value) {
        return roleModes.length > 0 && roleModes.indexOf(value) < 0;
    }
    // Où chercher des rôles en plus de ~/.config/omarchy-companion/roles.
    property var rolePaths: []
    property bool conversation: false
    // Interrupteur de l'accès Maison (réglage `home`, ancien nom `ha` encore lu à l'arrivée).
    property bool home: false
    property string haUrl: ""
    property bool haHasToken: false
    property bool haKeyring: false
    // Trousseau du système (18/10) : disponible ? et, par accès, un secret y est-il rangé (oui / non) ?
    property var secrets: ({ available: false, mail: false, erp: false, ha: false })
    property string mailEmail: ""
    property string mailHost: ""
    property int mailPort: 993
    property string erpUrl: ""
    property string mailStore: ""
    property string erpStore: ""
    property string haMessage: ""
    property string actionText: ""
    property string problem: ""
    property int permissionId: 0
    property string permissionTool: ""
    property string permissionText: ""
    // Hôte de la page web que l'agent veut lire (carte WebFetch) : bouton « Toujours pour ce site ».
    property string permissionHost: ""
    // Famille de l'action proposée (« firefox », « git push », « ~/Work/jeu ») : ce que le bouton
    // « Toujours ici » autorisera pour le reste de la conversation.
    property string permissionAction: ""
    // Vrai quand c'est Alison elle-même qui demande (photo de l'écran), pas l'agent qui propose une
    // action : la carte ne dit pas la même chose, et n'offre jamais de « toujours ».
    property bool permissionOwn: false
    // Familles déjà autorisées pour cette conversation (Réglages › Sécurité).
    property var sessionAllows: []
    property var trustedSites: []
    // Emplacements privés (coffre de secrets…) fermés à l'agent en mode Assistant : un réglage,
    // jamais un chemin dans le code.
    property var privatePaths: []
    // Carnet d'Alison (Réglages › Mémoire) : liste { text, at, source, topic }, tenue par le moteur.
    property var memory: []
    readonly property int memoryMax: 200
    // Notes du jour (mémoire à court terme) : nombre de journées écrites sur le disque.
    property int notesDays: 0
    // Relecture des conversations passées avant de répondre (Réglages › Mémoire).
    property bool recall: true
    // Le rêve : tri de la mémoire, une fois par jour. Dernier rapport et tri en cours.
    property bool dreams: true
    property var dreamReport: ({})
    property bool dreaming: false
    // Comptabilité : où prendre l'adresse et la clé d'un Dolibarr (jamais la clé elle-même).
    // Interrupteurs des accès courrier et comptabilité (la maison a `home`).
    property bool mailOn: true
    property bool erpOn: true
    property string erpVault: ""
    property string erpAccount: ""
    property int erpFiscalMonth: 1
    property string erpStatus: ""
    property bool erpOk: false
    // Portail (extension privée) : son adresse et où prendre les identifiants Authelia (jamais eux-mêmes).
    property bool portailOn: true
    property string portailUrl: ""
    property string portailVault: ""
    property string portailAccount: ""
    property string portailStatus: ""
    property bool portailOk: false
    // Robot (Reachy Mini, son corps) : l'adresse du service du robot, ici ou sur une autre machine.
    property bool robotOn: true
    property string robotUrl: ""
    property string robotStatus: ""
    property bool robotOk: false
    // Micro et sortie du robot quand il est branché sur CETTE machine (vides sinon) : le moteur
    // les trouve, le panneau ne fait que les proposer.
    property string robotSink: ""
    property string robotSource: ""
    // Coffre Obsidian où écrire « note dans Obsidian : … » ("" = pas de notes).
    property string obsidianVault: ""
    // Où elle répond à la voix : "barre", "bas" (le bandeau discret) ou "panneau" (comme avant).
    property string voiceStrip: "barre"
    property string sttEngine: "parakeet"   // moteur de transcription : parakeet | whisper
    // Micro utilisé ("" = celui du système). Un micro sans écho permet de la couper en parlant.
    property string micro: ""
    property string sortie: ""          // sortie de sa voix, "" = celle du système
    // « Stop » pendant qu'elle parle l'arrête net (même micro que le mot d'éveil).
    property bool barge: true
    // Décider une carte à la voix quand une action attend.
    property bool voiceDecide: false
    // Bandeau de la voix : demandé, et réellement à l'écran (jamais en même temps que le panneau).
    property bool stripOpen: false
    readonly property bool stripShown: stripOpen && !opened && voiceStrip !== "panneau"
    // Une carte attend dans le bandeau : deux boutons, le texte de l'action, et « détails ».
    readonly property bool stripCard: stripShown && permissionText !== ""
    property string stripYou: ""
    property string stripHer: ""
    property string stripHint: ""
    // Courrier (lecture seule) : où prendre les identifiants, et le résultat du dernier test.
    property string mailVault: ""
    property string mailAccount: ""
    property string mailStatus: ""
    property bool mailOk: false
    // Fenêtre d'aperçu ouverte (hôte), "" quand il n'y en a pas.
    property string previewHost: ""
    // Thèmes du carnet, dans l'ordre d'affichage ; « other » recueille ce qui n'est rangé nulle part.
    readonly property var memoryTopics: ["me", "home", "work", "prefs", "other"]

    // Souvenirs d'un thème. Un souvenir écrit par une ancienne version peut ne pas en avoir.
    function memoryIn(topic) {
        return memory.filter(function (item) { return (item.topic || "other") === topic; });
    }
    // Voix locale installée (environnement + modèles) ; installation guidée depuis Réglages › Voix.
    property bool voiceReady: true
    property bool voiceComplete: true   // faux : un complément manque (Parakeet) → « Compléter la voix »
    property bool voiceSetupRunning: false
    property string voiceSetupText: ""
    // Images du web demandées au clic : adresse -> { loading } | { path } | { error }.
    property var images: ({})
    property alias messageModel: messages
    // Modèles proposés (pastille et Réglages) : une seule liste, l'entrée « par défaut » est ajoutée
    // par chaque vue avec son libellé.
    // Les quatre modes, du plus fermé au plus ouvert. L'ORDRE vient du moteur (`agents.MODES`,
    // envoyé dans `ready`) : il n'existe qu'une seule échelle. Ce qui est écrit ici n'est que la
    // valeur de départ avant la première réponse du moteur, et un test la compare à `agents.MODES`.
    property var modeOrder: ["chat", "read", "assistant", "code", "auto"]
    readonly property var modeLabels: ({ "chat": tr.chip_chat, "read": tr.chip_read,
                                         "assistant": tr.chip_assistant, "code": tr.chip_code,
                                         "auto": tr.chip_auto })
    readonly property var modes: modeOrder.map(function (value) {
        return { value: value, label: modeLabels[value] || value, closed: modeClosed(value) };
    })
    readonly property var models: [
        { value: "fable", label: "Fable" },
        { value: "opus", label: "Opus" },
        { value: "sonnet", label: "Sonnet" },
        { value: "haiku", label: "Haiku" }
    ]
    // La voix ne bloque pas : on peut lire, écrire et envoyer pendant qu'elle parle.
    readonly property bool busy: mood !== "idle" && mood !== "listening" && mood !== "speaking"
    readonly property int messageCount: messages.count   // l'en-tête n'offre Nouvelle / Supprimer que sur un fil non vide
    // Bref « non de la tête » quand une phrase de la pièce est écartée.
    property bool ignoredFlash: false
    // Ce qu'elle fait, lu dans les outils que l'agent lance : l'avatar prend la posture qui va avec.
    // Tenue au moins ACTIVITY_HOLD : sans ça elle clignote d'une activité à l'autre, et ça devient
    // du bruit au lieu d'une information.
    property string activity: ""
    readonly property int activityHold: 800
    function activityOf(text) {
        var line = String(text || "");
        var name = line.split(":")[0].trim();
        if (name === "WebSearch")
            return "search";
        if (name === "WebFetch" || name === "Read" || name === "Grep" || name === "Glob")
            return "read";
        if (name === "Write" || name === "Edit" || name === "MultiEdit" || name === "NotebookEdit")
            return /\.(py|qml|js|ts|lua|sh|c|h|cpp|rs|go|json|toml|ya?ml|css|html)\b/i.test(line) ? "code" : "write";
        if (name === "Bash")
            return /mail\.py/.test(line) ? "mail" : (/apercu\.py/.test(line) ? "read" : "run");
        return "";
    }
    function showActivity(text) {
        var found = activityOf(text);
        if (found === "")
            return;
        activity = found;
        activityTimer.restart();
    }
    Timer {
        id: activityTimer
        interval: root.activityHold
        onTriggered: if (root.mood !== "thinking" && root.mood !== "acting") root.activity = "";
    }

    // Le widget de barre affiche le même visage : il lit ces deux valeurs sur le service partagé.
    Binding { target: root.service; property: "face"; value: root.face; when: root.service !== null }
    Binding { target: root.service; property: "activity"; value: root.activity; when: root.service !== null }
    // Le mot d'éveil n'ouvre plus le grand panneau quand le bandeau est choisi : c'est le panneau
    // (seul à lire les réglages) qui le dit au service, et le service lui rend la main.
    Binding {
        target: root.service
        property: "stripMode"
        value: root.voiceStrip !== "panneau"
        when: root.service !== null
    }
    Connections {
        target: root.service
        enabled: root.service !== null
        function onWoke() {
            root.wake();
        }
        function onBarged(word, file) {
            root.cutSpeech(word, file);
        }
        function onDecided(kind, word, card) {
            root.decideAloud(kind, word, card);
        }
    }

    // « Salut Alison » avec le bandeau : rien ne s'ouvre, elle écoute, et ce qu'elle entend part
    // tout seul — il n'y a pas de champ de saisie où relire avant d'envoyer.
    function wake(how) {
        if (opened) {
            write(how === "greet" ? { command: "greet" } : { command: "record", auto: root.conversation });
            return;
        }
        stripYou = "";
        stripHer = "";
        stripHint = "";
        stripOpen = true;
        write(how === "greet" ? { command: "greet" } : { command: "record", auto: true });
    }
    // Ce qu'elle dit, tel qu'il tient dans le bandeau. Une réponse avec du code ou une image ne
    // se lit pas ici : on le signale, on n'ouvre pas le bureau de force.
    function stripSay(text) {
        var body = String(text || "");
        var rich = body.indexOf("```") >= 0 || /!\[[^\]]*\]\(/.test(body);
        stripHer = rich ? body.split("```")[0].trim() : body;
        stripHint = rich ? tr.strip_more : tr.strip_open;
        stripTimer.restart();
    }
    // « Stop » pendant qu'elle parle : elle se tait tout de suite. Le moteur enchaîne sur
    // l'écoute si la conversation est en cours.
    function cutSpeech(word, file) {
        if (!connected)
            return;
        // `file` : ce que le service a entendu avant de la couper — le début de sa phrase à lui.
        write({ command: "barge", text: word, file: file || "" });
        if (stripOpen) {
            stripHer = "";
            stripHint = "";
            stripTimer.restart();
        }
    }
    // Carte décidée à la voix. Volontairement asymétrique : autoriser demande un mot délibéré
    // (« valide », « j'autorise », « d'accord »), refuser en accepte beaucoup — se tromper de refus
    // ne coûte qu'un « recommence », se tromper d'autorisation exécute quelque chose.
    function decideAloud(kind, word, card) {
        if (permissionId <= 0 || permissionText === "")
            return;      // plus rien n'attend : le mot arrive trop tard, il ne décide de rien
        // Le mot a été entendu pendant une autre carte (ou sans numéro) : il ne vaut pas pour
        // celle-ci. Se tromper de refus coûte peu, mais une autorisation ne glisse jamais.
        if (kind === "allow" && card !== permissionId)
            return;
        decide(kind === "allow" ? "allow" : "deny");
    }
    // Clic sur le bandeau : on passe au grand panneau, la conversation continue au même endroit.
    function openFromStrip() {
        stripOpen = false;
        if (shell && pluginId)
            shell.summon(pluginId, '{"view":"chat"}');
    }
    // Le moteur n'écoute tout seul que si une surface est à l'écran : il faut donc lui dire quand
    // le bandeau apparaît et quand il part.
    onStripShownChanged: {
        if (connected)
            write({ command: "strip", value: stripShown });
        if (stripShown)
            stripTimer.restart();
        else
            stripTimer.stop();
    }
    Timer {
        id: stripTimer
        interval: 6000
        // Répétée : si un état se perdait en route, le bandeau resterait sinon à l'écran pour
        // toujours — et il vaut « micro autorisé » côté moteur.
        repeat: true
        // Le bandeau reste tant qu'elle FAIT quelque chose — elle écoute, réfléchit, parle, ou une
        // carte attend. C'est vrai en conversation mains libres, où le micro se rouvre seul entre
        // deux phrases (l'état ne repasse jamais au repos), et ça s'arrête tout seul quand la
        // boucle s'éteint faute de parole. Lier ça au réglage `conversation` le laissait à l'écran
        // pour toujours (trouvé à l'audit du 19/09 : c'est justement une configuration réelle).
        onTriggered: if (root.mood === "idle" && !root.busy && root.permissionText === "")
                        root.stripOpen = false;
    }

    // Expression de l'avatar : l'état du moteur, précisé par ce que le panneau sait en plus
    // (micro coupé en conversation, erreur affichée, phrase écartée).
    readonly property string face: {
        if (mood === "idle" && ignoredFlash) return "ignored";
        if (mood === "idle" && problem !== "") return "error";
        if (mood === "idle") return root.conversation ? "muted" : "idle";
        return mood;
    }
    readonly property string wakeLabel: (wakePhrase || wakeOf(lang)).replace(/(^|\s)(\S)/g, function (all, space, letter) { return space + letter.toUpperCase(); })
    // L'état dit la vérité sur le micro : jamais « à ton écoute » quand il est fermé.
    readonly property string statusText: ({
            listening: tr.status_listening,
            transcribing: tr.status_transcribing,
            thinking: tr.status_thinking,
            waiting: tr.status_waiting,
            acting: tr.status_acting,
            speaking: tr.status_speaking
        })[mood] || (root.conversation
            ? (wakeEnabled ? t("status_muted_wake", wakeLabel) : tr.status_muted_touch)
            : tr.status_ready)

    function write(message) {
        bridge.write(JSON.stringify(message) + "\n");
    }
    // Rayon d'un coin arrondi : suit le thème (un thème à coins carrés reste carré). Les points
    // et le micro rond restent des cercles : leur forme porte un sens, pas un style.
    function rounded(px) {
        return Style.cornerRadius > 0 ? Style.space(px) : 0;
    }
    function open(payload) {
        var p = {};
        try {
            p = JSON.parse(payload || "{}");
        } catch (e) {}
        quietOpen = !!p.view && !p.listen;
        // Le panneau prend la suite : le bandeau ne doit pas réapparaître quand on le referme.
        stripOpen = false;
        opened = true;
        write({ command: "resume" });
        Qt.callLater(function () {
            if (root.view === "welcome")
                welcomeView.focusNext();       // le champ de saisie est caché pendant l'assistant
            else
                composer.focusInput();
            try {
                if (p.prefs)
                    root.setView("settings");
                else if (p.view === "chat" || p.view === "settings" || p.view === "journal" || p.view === "welcome")
                    root.setView(p.view);
                if (p.section)
                    settingsView.section = p.section;
                // Crochet de test : affiche les images du fil sans clic (les clics simulés
                // n'atteignent pas la couche du panneau).
                if (p.showImages)
                    chat.showAllImages();
                // Conversation mains libres : le panneau qui s'ouvre écoute tout de suite.
                // Une ouverture qui désigne une vue (captures, tests) n'ouvre jamais le micro
                // d'elle-même : seul `listen` le fait.
                if (p.listen || (root.conversation && !p.prefs && !p.view))
                    write({ command: "record", auto: root.conversation });
            } catch (e) {}
        });
    }
    function close() {
        // `hidden` part une seule fois, depuis onVisibleChanged de la fenêtre (quel que soit le chemin
        // qui la masque) ; l'envoyer aussi ici le doublait.
        opened = false;
        quietOpen = false;
    }
    function dismiss() {
        close();
        if (shell && pluginId)
            shell.hide(pluginId);
    }
    function send(command, text) {
        if (connected)
            write({ command: command, text: text || "" });
    }
    // « Ouvrir » sous un bloc de code : le moteur l'écrit dans un fichier privé et lance l'éditeur
    // d'Omarchy. Rien n'est jamais écrit dans les fichiers de l'utilisateur.
    function openCode(lang, body) {
        if (connected)
            write({ command: "open_code", text: body, lang: lang });
    }
    // Correction d'un souvenir (Réglages › Mémoire) : l'ancien texte le désigne, `new` et `topic`
    // disent ce qui change. Le moteur garde sa date et son origine.
    function editMemory(previous, text, topic) {
        if (connected)
            write({ command: "edit_memory", text: previous, new: text, topic: topic });
    }
    // Décision sur la carte affichée : le numéro part avec, le moteur ignore toute décision qui ne
    // vise pas la carte en attente (double-clic, clic arrivé après le délai).
    function decide(command) {
        if (connected && permissionId > 0)
            write({ command: command, text: "", id: permissionId });
    }
    function setView(name) {
        view = name;
        if (name === "journal")
            send("journal");
    }
    // Icône de l'en-tête : ouvre la vue, ou ramène à la conversation si elle est déjà ouverte.
    function showView(name) {
        setView(view === name ? "chat" : name);
    }
    function openUrl(url) {
        // Le navigateur s'ouvre derrière le panneau : on le referme pour voir la page.
        send("open_url", url);
        dismiss();
    }
    function showImage(url) {
        var next = Object.assign({}, images);
        next[url] = { loading: true };
        images = next;
        send("fetch_image", url);
    }
    function showSettings(section) {
        setView("settings");
        settingsView.section = section;
    }
    function restartWelcome() {
        welcomeView.step = 0;
        setView("welcome");
        welcomeView.focusNext();
    }
    function copyText(text) {
        clipboard.text = text;
        clipboard.selectAll();
        clipboard.copy();
        clipboard.text = "";
    }
    // Toutes les lignes du fil portent les mêmes rôles (un ListModel les fige au premier ajout).
    //   role : user | assistant | tools | ignored | memory (texte préfixé + retenu / - retiré) ; at : heure (secondes, 0 = inconnue) ;
    //   text : message, ou commandes des outils une par ligne ; count : nombre d'outils ; open : déplié.
    function line(role, text, at) {
        return { role: role, text: text, at: at || 0, count: 0, open: false };
    }
    function addTool(text) {
        // Outil lancé par l'agent. Pendant une réponse en flux, il se range AVANT la bulle en cours
        // pour que le flux continue de compléter la dernière ligne. Outils successifs = un seul groupe.
        var at = streaming && messages.count > 0 ? messages.count - 1 : messages.count;
        if (at > 0 && messages.get(at - 1).role === "tools") {
            var group = messages.get(at - 1);
            messages.setProperty(at - 1, "text", group.text + "\n" + text);
            messages.setProperty(at - 1, "count", group.count + 1);
        } else {
            var fresh = line("tools", text, Date.now() / 1000);
            fresh.count = 1;
            messages.insert(at, fresh);
        }
    }
    function clearCard() {
        permissionId = 0;
        permissionTool = "";
        permissionText = "";
        permissionHost = "";
        permissionAction = "";
        permissionOwn = false;
    }
    // Échap ferme, revient à la conversation ou refuse la carte ; Ctrl+Entrée exécute la carte.
    // Une seule règle, appelée d'où que vienne le clavier.
    function shortcut(event) {
        if (event.key === Qt.Key_Escape) {
            if (!(view === "journal" && journalView.consumeEscape())
                    && !(view === "settings" && settingsView.consumeEscape()))
                handleEscape();
            event.accepted = true;
        } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                   && (event.modifiers & Qt.ControlModifier) && permissionText !== "") {
            decide("allow");
            event.accepted = true;
        }
    }
    function handleEscape() {
        if (permissionText !== "") {
            // Refus envoyé, carte retirée tout de suite : une carte que le moteur ne reconnaît plus
            // (délai passé, moteur relancé) restait affichée et bloquait Échap pour de bon.
            decide("deny");
            clearCard();
        } else if (view !== "chat")
            setView("chat");
        else
            dismiss();
    }
    function submit(text) {
        if (!text.trim() || busy || !connected)
            return false;
        if (mood === "listening")
            send("cancel_record");  // une question tapée prime sur l'écoute en cours
        problem = "";
        actionText = "";
        mood = "thinking";
        setView("chat");
        send("ask", text);
        return true;
    }
    function talk() {
        if (mood === "listening")
            send("stop_record");
        else
            write({ command: "record", auto: root.conversation });
    }
    // Réglages du panneau, tels qu'enregistrés dans l'entrée du plugin de shell.json.
    // Réglage → propriété du panneau. UNE SEULE table : `currentSettings()` l'écrit sur le disque
    // et `setSetting()` la relit. Un réglage oublié ici ne s'enregistre pas du tout — six l'étaient
    // (voiceStrip, obsidianVault, mailVault, mailAccount, recall, dreams), trouvés à l'audit du
    // 19/09 : le shell REconstruit l'entrée à partir des clés reçues, il ne complète pas. Le test
    // `test_every_setting_of_the_panel_is_saved` relit cette table contre les appels des Réglages.
    readonly property var settingProperties: ({
        "name": "companionName",
        "provider": "provider",
        "model": "modelName",
        "endpoint": "endpoint",
        "voice": "voice",
        "wakeword": "wakeEnabled",
        "wakePhrase": "wakePhrase",
        "mode": "mode",
        "role": "role",
        "rolePaths": "rolePaths",
        "conversation": "conversation",
        "home": "home",
        "trustedSites": "trustedSites",
        "privatePaths": "privatePaths",
        "language": "lang",
        "recall": "recall",
        "dreams": "dreams",
        "voiceStrip": "voiceStrip",
        "sttEngine": "sttEngine",
        "barge": "barge",
        "micro": "micro",
        "sortie": "sortie",
        "voiceDecide": "voiceDecide",
        "omarchyKnowledge": "omarchyKnowledge",
        "setupDone": "setupDone",
        "obsidianVault": "obsidianVault",
        "mail": "mailOn",
        "erp": "erpOn",
        "mailVault": "mailVault",
        "mailAccount": "mailAccount",
        "erpVault": "erpVault",
        "erpAccount": "erpAccount",
        "erpFiscalMonth": "erpFiscalMonth",
        "mailEmail": "mailEmail",
        "mailHost": "mailHost",
        "mailPort": "mailPort",
        "erpUrl": "erpUrl",
        "mailStore": "mailStore",
        "erpStore": "erpStore",
        "portail": "portailOn",
        "delegation": "delegation",
        "portailUrl": "portailUrl",
        "portailVault": "portailVault",
        "portailAccount": "portailAccount",
        "robot": "robotOn",
        "robotUrl": "robotUrl"
    })

    function currentSettings() {
        var out = {};
        for (var key in settingProperties)
            out[key] = root[settingProperties[key]];
        return out;
    }
    // Entrée actuelle du plugin dans la barre (clés inconnues d'Alison comprises), pour ne rien perdre :
    // updateEntryInline REMPLACE l'entrée entière.
    function currentEntry() {
        var layout = shell && shell.barConfig && shell.barConfig.layout ? shell.barConfig.layout : {};
        for (var section in layout) {
            var items = layout[section] || [];
            for (var i = 0; i < items.length; i++)
                if (items[i] && items[i].id === pluginId)
                    return items[i];
        }
        for (var j = 0; j < savedPluginEntries.length; j++)
            if (savedPluginEntries[j] && savedPluginEntries[j].id === pluginId)
                return savedPluginEntries[j];
        return {};
    }
    // Le shell expose la barre, mais pas plugins[] : relire les entrées hors barre.
    property var savedPluginEntries: []
    FileView {
        id: savedShellConfig
        path: Quickshell.env("COMPANION_SHELL_JSON") ||
              (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/omarchy/shell.json"
        blockLoading: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                var config = JSON.parse(text());
                root.savedPluginEntries = config.plugins || [];
                root.applyConfig(root.currentEntry());
            } catch (e) { root.savedPluginEntries = []; }
        }
    }
    // Applique les réglages reçus (du moteur à l'arrivée, ou de shell.json quand le shell le
    // réécrit — `omarchy bar set` compris) ; une clé absente laisse la valeur en place.
    function applyConfig(config) {
        var c = Object.assign({}, config || {});
        var now = Date.now();
        for (var key in recentWrites) {
            var mark = recentWrites[key];
            if (now - mark.at > recentWriteMs)
                continue;
            if (key in c && JSON.stringify(c[key]) !== mark.value)
                delete c[key];      // copie périmée : notre écriture récente prime
        }
        function list(value) { return Array.isArray(value) ? value : (typeof value === "string" && value ? [value] : []); }
        if ("name" in c) companionName = c.name;
        if ("provider" in c) provider = c.provider;
        if ("model" in c) modelName = c.model;
        if ("endpoint" in c) endpoint = c.endpoint;
        if ("voice" in c) voice = c.voice;
        if ("wakeword" in c) wakeEnabled = c.wakeword;
        if ("wakePhrase" in c) wakePhrase = c.wakePhrase;
        if ("language" in c) {
            lang = c.language || "fr";
            if (service)
                service.lang = lang;
        }
        if ("mode" in c) mode = c.mode || "assistant";
        if ("role" in c) role = c.role || "";
        if ("rolePaths" in c) rolePaths = list(c.rolePaths);
        if ("conversation" in c) root.conversation = c.conversation || false;
        if ("home" in c) home = c.home || false;
        else if ("ha" in c) home = c.ha || false;   // ancien nom du réglage
        if ("recall" in c) recall = c.recall !== false;
        if ("obsidianVault" in c) obsidianVault = c.obsidianVault || "";
        if ("voiceStrip" in c) voiceStrip = c.voiceStrip || "barre";
        if ("sttEngine" in c) sttEngine = c.sttEngine || "parakeet";
        if ("barge" in c) barge = c.barge !== false;
        if ("micro" in c) micro = c.micro || "";
        if ("sortie" in c) sortie = c.sortie || "";
        if ("voiceDecide" in c) voiceDecide = c.voiceDecide !== false;
        if ("omarchyKnowledge" in c) omarchyKnowledge = c.omarchyKnowledge !== false;
        if ("setupDone" in c) setupDone = !!c.setupDone;
        if ("mailVault" in c) mailVault = c.mailVault || "";
        if ("mailAccount" in c) mailAccount = c.mailAccount || "";
        if ("mail" in c) mailOn = c.mail !== false;
        if ("erp" in c) erpOn = c.erp !== false;
        if ("erpVault" in c) erpVault = c.erpVault || "";
        if ("erpAccount" in c) erpAccount = c.erpAccount || "";
        if ("erpFiscalMonth" in c) erpFiscalMonth = c.erpFiscalMonth || 1;
        if ("mailEmail" in c) mailEmail = c.mailEmail || "";
        if ("mailHost" in c) mailHost = c.mailHost || "";
        if ("mailPort" in c) mailPort = c.mailPort || 993;
        if ("erpUrl" in c) erpUrl = c.erpUrl || "";
        if ("mailStore" in c) mailStore = c.mailStore || "";
        if ("erpStore" in c) erpStore = c.erpStore || "";
        if ("portail" in c) portailOn = c.portail !== false;
        if ("delegation" in c) delegation = c.delegation !== false;
        if ("portailUrl" in c) portailUrl = c.portailUrl || "";
        if ("portailVault" in c) portailVault = c.portailVault || "";
        if ("portailAccount" in c) portailAccount = c.portailAccount || "";
        if ("robot" in c) robotOn = c.robot !== false;
        if ("robotUrl" in c) robotUrl = c.robotUrl || "";
        if ("dreams" in c) dreams = c.dreams !== false;
        if ("trustedSites" in c) trustedSites = list(c.trustedSites);
        if ("privatePaths" in c) privatePaths = list(c.privatePaths);
    }
    Connections {
        target: root.shell
        function onBarConfigChanged() { root.applyConfig(root.currentEntry()); }
    }
    // Réglages restaurés d'une sauvegarde : déjà filtrés par le moteur (jamais le mode, les accès, les
    // sites de confiance ni la validation vocale). Appliqués d'un bloc puis écrits UNE fois par le shell.
    function applyImported(settings) {
        var marks = recentWrites;
        for (var key in settings) {
            if (settingProperties[key] !== undefined && key !== "language") {
                root[settingProperties[key]] = settings[key];
                marks[key] = { value: JSON.stringify(settings[key]), at: Date.now() };
            }
        }
        recentWrites = marks;
        if (settings.language !== undefined && settings.language !== root.lang)
            setSetting("language", settings.language);
        else
            saveSettings();
    }
    function saveSettings() {
        // Le shell est seul à écrire shell.json : il garde la configuration en mémoire et réécrit
        // tout le fichier, un second écrivain perdrait des changements. Le moteur reçoit les mêmes
        // réglages pour les appliquer tout de suite.
        var settings = currentSettings();
        var entry = Object.assign({}, currentEntry(), settings);
        delete entry.id;
        delete entry.ha;    // ancien nom de `home`, relu à l'arrivée mais jamais réécrit
        if (shell && pluginId)
            shell.updateEntryInline(pluginId, entry);
        if (connected)
            write({ command: "save", settings: settings });
    }
    // État du rôle publié par le moteur : { name, label, modes, folder }.
    function applyRole(state) {
        var r = state || ({});
        role = r.name || "";
        roleLabel = r.label || "";
        roleModes = r.modes || [];
        if (r.folder)
            rolesFolder = r.folder;
    }
    // Ce que le panneau vient d'écrire lui-même : clé → { value, at }. Le shell renvoie, juste après
    // une écriture, une RAFALE de configurations (25 en 70 ms le 21/09) dont les premières portent
    // encore l'ancienne valeur ; le panneau s'y rabattait, et selon l'ordre d'arrivée restait sur
    // la valeur périmée (rangée MODE sur « Discussion » alors que le disque disait « Lecture »,
    // vu à la recette). Une valeur périmée ne peut plus écraser une écriture récente.
    property var recentWrites: ({})
    readonly property int recentWriteMs: 4000
    function setSetting(key, value) {
        if (key !== "language") {
            var marks = recentWrites;
            marks[key] = { value: JSON.stringify(value), at: Date.now() };
            recentWrites = marks;
        }
        if (key !== "language" && settingProperties[key] !== undefined)
            root[settingProperties[key]] = value;
        if (key === "language") {
            // La phrase d'éveil suit la langue tant qu'elle est celle par défaut ; une phrase
            // choisie à la main reste. Le service du mot d'éveil recharge son modèle.
            if (wakePhrase === "" || wakePhrase === wakeOf(root.lang))
                wakePhrase = wakeOf(value) || wakePhrase;
            root.lang = value;
            if (service) {
                service.lang = value;
                if (typeof service.restart === "function")
                    service.restart();
            }
        }
        saveSettings();
    }
    // Une pastille d'accès : réglée on l'allume ou on l'éteint, pas réglée on ouvre ses réglages.
    // Fermée par le mode ou le rôle, elle n'est pas cliquable (la pastille s'en charge).
    function toggleAccess(item) {
        if (!item)
            return;
        if (!item.configured) {
            showSettings("access");
            return;
        }
        setSetting(item.key, !item.on);
    }
    function toggleConversation() {
        root.conversation = !root.conversation;
        if (root.conversation)
            root.voice = true;
        saveSettings();
        if (root.conversation) {
            // On écoute immédiatement : pas besoin de cliquer sur le micro.
            setView("chat");
            write({ command: "record", auto: true });
        } else
            send("cancel_record");
    }
    function event(data) {
        if (data.event === "ready") {
            if (!connected)
                problem = "";   // « Le service s'est arrêté » ne vaut plus : il répond
            connected = true;
            applyConfig(data.config);
            memory = data.memory || [];
            notesDays = data.notes || 0;
            dreamReport = data.dream || ({});
            sessionAllows = data.sessionAllows || [];
            // Rôles trouvés sur le disque. Le réglage `role` vient de shell.json (applyConfig) ;
            // celui-ci dit ce que le moteur a VRAIMENT chargé — un dossier effacé remet "".
            rolesAvailable = data.roles || [];
            languages = data.languages || [];
            access = data.access || [];
            applyRole(data.role);
            // Les modes viennent du moteur (agents.MODES) : une seule échelle, pas deux listes.
            if (data.modes && data.modes.length)
                modeOrder = data.modes;
            if (data.voiceSetup) {
                voiceReady = data.voiceSetup.ready;
                voiceComplete = data.voiceSetup.complete !== false;
                voiceSetupRunning = data.voiceSetup.running;
            }
            if (data.haStatus) {
                haUrl = data.haStatus.url || "";
                haHasToken = data.haStatus.hasToken || false;
            }
            // Panneau déjà ouvert en conversation quand l'état arrive : on écoute sans clic.
            if (opened) {
                write({ command: "resume" });
                if (root.conversation && mood === "idle" && root.view !== "settings" && root.view !== "welcome" && !root.quietOpen)
                    write({ command: "record", auto: true });
            }
            agentName = data.agentName || "";
            agentProblem = data.agentProblem || "";
            harness = data.harness || "";
            harnessUnsafe = !!data.harnessUnsafe;
            brainLevel = data.brainLevel || "";
            if (data.secrets)
                secrets = data.secrets;
            personaText = (data.persona && data.persona.text) || "";
            personaCustom = !!(data.persona && data.persona.custom);
            omarchySkill = !!data.omarchySkill;
            roleExamples = data.examples || [];
            // Au PREMIER état reçu seulement : un état suivant (sync) ne ramène jamais l'assistant au
            // milieu d'une conversation après un Échap.
            if (!welcomeShown && data.firstRun)
                view = "welcome";
            welcomeShown = true;
            firstRun = !!data.firstRun;
            if (provider === "omarchy" && agentProblem)
                problem = agentProblem;
        } else if (data.event === "agent") {
            // Rafraîchissement de l'agent et du harnais seuls : ne touche jamais à l'écoute.
            agentName = data.agentName || "";
            agentProblem = data.agentProblem || "";
            harness = data.harness || "";
            harnessUnsafe = !!data.harnessUnsafe;
        } else if (data.event === "history") {
            messages.clear();
            streaming = false;
            images = ({});   // les vignettes de l'ancienne conversation ne servent plus
            for (var m of data.messages)
                messages.append(line(m.role, m.content, m.at));
        } else if (data.event === "tool") {
            showActivity(data.text);
            addTool(data.text);
            chat.scrollToEnd();
        } else if (data.event === "mail_status") {
            mailStatus = data.text || "";
            mailOk = !!data.ok;
        } else if (data.event === "erp_status") {
            erpStatus = data.text || "";
            erpOk = !!data.ok;
        } else if (data.event === "portail_status") {
            portailStatus = data.text || "";
            portailOk = !!data.ok;
        } else if (data.event === "robot_touch") {
            // Une antenne touchée = « salut Alison », par le même chemin (bandeau puis micro),
            // et seulement si le réveil à la voix est activé. Elle commence par un mot qui
            // dépend du toucher (« Oui ? » ou « Oh ! Doucement ! »), puis elle écoute.
            if (wakeEnabled)
                wake("greet");
        } else if (data.event === "robot_audio") {
            robotSink = data.sink || "";
            robotSource = data.source || "";
        } else if (data.event === "robot_status") {
            robotStatus = data.text || "";
            robotOk = !!data.ok;
        } else if (data.event === "session_allows") {
            sessionAllows = data.items || [];
        } else if (data.event === "preview") {
            previewHost = data.host || "";
            if (previewHost !== "") {
                messages.append(line("preview", previewHost, Date.now() / 1000));
                chat.scrollToEnd();
            }
        } else if (data.event === "dream") {
            dreamReport = data.report || ({});
            memory = data.memory || memory;
        } else if (data.event === "dream_running") {
            dreaming = !!data.value;
            // Elle range sa mémoire : l'avatar dort, même si rien d'autre ne se passe.
            if (dreaming) {
                activity = "dream";
                activityTimer.stop();
            } else if (activity === "dream") {
                activity = "";
            }
        } else if (data.event === "recall") {
            // Ligne discrète avant la réponse : d'où elle tire ce qu'elle va dire.
            if ((data.days || []).length > 0) {
                messages.append(line("recall", data.days.join(", "), Date.now() / 1000));
                chat.scrollToEnd();
            }
        } else if (data.event === "notes") {
            notesDays = data.days || 0;
        } else if (data.event === "memory") {
            memory = data.items || [];
            // Ligne discrète dans le fil : « Retenu : … » (avec annuler) ou « Retiré : … ».
            if (data.op === "kept" || data.op === "removed") {
                messages.append(line("memory", (data.op === "kept" ? "+" : "-") + data.text, Date.now() / 1000));
                chat.scrollToEnd();
            }
        } else if (data.event === "ignored") {
            // Phrase de la pièce qu'Alison a jugée non adressée : la bulle devient une ligne
            // discrète, pour que tu voies ce qui a été entendu sans que ça encombre le fil.
            for (var i = messages.count - 1; i >= 0; i--) {
                if (messages.get(i).role === "user" && messages.get(i).text === data.text) {
                    messages.remove(i);
                    break;
                }
            }
            streaming = false;
            messages.append(line("ignored", data.text, Date.now() / 1000));
            ignoredFlash = true;
            // Phrase de la pièce : sans ça, le bandeau affichait la nouvelle question au-dessus de
            // l'ANCIENNE réponse, comme si elle venait d'y répondre.
            if (stripOpen) {
                stripYou = t("strip_you", data.text);
                stripHer = "";
                stripHint = "";
                stripTimer.restart();
            }
            ignoredTimer.restart();
            chat.scrollToEnd();
        } else if (data.event === "partial") {
            // Réponse au fil de l'eau : on complète le dernier message de l'agent.
            if (!streaming) {
                messages.append(line("assistant", "", Date.now() / 1000));
                streaming = true;
            }
            var last = messages.count - 1;
            messages.setProperty(last, "text", messages.get(last).text + data.text);
            if (stripOpen)
                stripSay(messages.get(last).text);
            chat.scrollToEnd();
        } else if (data.event === "message") {
            if (streaming && data.role === "assistant") {
                messages.setProperty(messages.count - 1, "text", data.text);
                if (data.at)
                    messages.setProperty(messages.count - 1, "at", data.at);
                streaming = false;
            } else
                messages.append(line(data.role, data.text, data.at));
            if (stripOpen) {
                if (data.role === "assistant")
                    stripSay(data.text);
                else
                    stripYou = t("strip_you", data.text);
            }
        } else if (data.event === "voice_setup") {
            voiceSetupRunning = data.running;
            voiceReady = data.ready;
            voiceComplete = data.complete !== false;
            voiceSetupText = data.text || "";
            // Voix tout juste installée : le service du mot d'éveil repart avec le nouvel environnement.
            if (!data.running && data.ready && service && typeof service.restart === "function")
                service.restart();
        } else if (data.event === "ha_status") {
            haUrl = data.url || "";
            haHasToken = data.hasToken || false;
            haKeyring = !!data.keyring;
            haMessage = data.message || "";
        } else if (data.event === "setting") {
            // Réglage changé par le moteur (voix, site de confiance) : on l'affiche et on l'enregistre.
            if (data.key === "mode") mode = data.value;
            else if (data.key === "conversation") root.conversation = data.value;
            else if (data.key === "home") home = data.value;
            else if (data.key === "voice") voice = data.value;
            else if (data.key === "model") modelName = data.value;
            else if (data.key === "trustedSites") trustedSites = data.value || [];
            else if (data.key === "role") role = data.value || "";
            else if (data.key === "language") { setSetting("language", data.value); return; }
            saveSettings();
        } else if (data.event === "access") {
            access = data.items || [];
        } else if (data.event === "secrets") {
            secrets = data;
        } else if (data.event === "backup") {
            backupError = data.error || "";
            if (data.items)
                backupItems = data.items;
            if (data.folder)
                backupFolder = data.folder;
            if (data.done === "export" && !data.error)
                backupStatus = t("backup_exported", data.path || "");
            if (data.done === "preview") {
                backupPreview = data.preview || null;
                backupPath = data.preview ? (data.path || "") : "";
                backupToken = data.preview ? (data.token || "") : "";
            }
            if (data.done === "apply" && !data.error) {
                applyImported(data.settings || {});
                backupPreview = null;
                backupStatus = t("backup_restored", (data.errors || []).length);
            }
        } else if (data.event === "persona") {
            personaText = data.text || "";
            personaCustom = !!data.custom;
        } else if (data.event === "roles") {
            rolesAvailable = data.items || [];
        } else if (data.event === "role_saved") {
            roleSaveError = data.ok ? "" : (data.error || "?");
            roleSaveCount += 1;
        } else if (data.event === "role") {
            // Rôle pris ou quitté : qui répond, quels modes restent ouverts, ce qu'il retire.
            applyRole(data);
        } else if (data.event === "permission") {
            permissionId = data.id || 0;
            permissionTool = data.tool || "";
            permissionText = data.text || "";
            permissionHost = data.host || "";
            permissionAction = data.action || "";
            permissionOwn = data.own === true;
            // Rien à l'écran (panneau fermé, bandeau déjà effacé) : la carte attendrait 120 s sans
            // que personne la voie. Là, et seulement là, on ouvre le panneau.
            if (permissionText !== "" && !opened && !stripOpen)
                openFromStrip();
            // Le bandeau porte lui-même les deux boutons (choix du 19/09) : la voix ne doit
            // pas rallumer tout le bureau pour un oui ou un non. « Détails » ouvre le panneau pour
            // qui veut lire l'action en entier.
            // La carte réduit la hauteur du fil : on le ramène en bas pour garder ta demande visible.
            chat.scrollToEnd();
        } else if (data.event === "image") {
            var shown = Object.assign({}, images);
            shown[data.url] = data.path ? { path: data.path } : { error: data.error || "image indisponible" };
            images = shown;
        } else if (data.event === "journal") {
            journalText = data.text || "\n";
        } else if (data.event === "level")
            audioLevel = data.value;
        else if (data.event === "state") {
            mood = data.value;
            if (stripOpen)
                stripTimer.restart();
            // Elle parle ou attend : l'outil est fini, la posture de travail n'a plus de sens.
            if (mood !== "thinking" && mood !== "acting" && !activityTimer.running)
                activity = "";
        }
        else if (data.event === "error") {
            problem = data.text;
            // Panneau fermé, l'erreur n'irait nulle part : le bandeau la dit à sa place.
            if (stripOpen) {
                stripHer = data.text;
                stripHint = "";
                stripTimer.restart();
            }
        }
        else if (data.event === "action")
            actionText = data.text;
        else if (data.event === "transcript") {
            // En conversation (auto), la phrase part toute seule : elle apparaît dans le fil, pas dans
            // la saisie, où elle restait affichée même après envoi ou quand Alison l'ignorait.
            if (!data.auto)
                composer.setText(data.text);
            if (stripOpen)
                stripYou = t("strip_you", data.text);
        }
    }

    ListModel {
        id: messages
    }
    Timer {
        id: ignoredTimer
        interval: 1600
        onTriggered: root.ignoredFlash = false
    }
    // Presse-papiers : un champ invisible qui copie son texte (copier une réponse, le journal).
    TextEdit {
        id: clipboard
        visible: false
    }
    // Si la ligne d'état initial se perd au démarrage (course de lecture Quickshell),
    // on redemande l'état jusqu'à l'avoir reçu.
    Timer {
        id: syncTimer
        interval: 400
        repeat: true
        running: bridge.running && !root.connected
        property int tries: 0
        onRunningChanged: if (running) tries = 0   // chaque (re)connexion repart de zéro
        onTriggered: {
            if (root.connected || tries > 8) {
                stop();
                return;
            }
            tries += 1;
            root.write({ command: "sync" });
        }
    }
    Timer {
        id: focusPrimeTimer
        property bool primed: false
        interval: 75
        onTriggered: primed = root.opened
    }
    onOpenedChanged: {
        focusPrimeTimer.primed = false;
        if (opened)
            focusPrimeTimer.restart();
        else
            focusPrimeTimer.stop();
    }
    Process {
        id: bridge
        command: ["python3", Qt.resolvedUrl("backend.py").toString().replace("file://", "")]
        environment: ({ PYTHONDONTWRITEBYTECODE: "1" })
        stdinEnabled: true
        running: true
        stdout: SplitParser {
            onRead: data => {
                if (!data || !data.trim())
                    return;
                var parsed = null;
                try {
                    parsed = JSON.parse(data);
                } catch (e) {
                    console.warn("Compagnon: ligne non JSON (" + data.length + " car.): " + data.substring(0, 60));
                    return;
                }
                try {
                    root.event(parsed);
                } catch (e) {
                    // Une erreur dans le traitement d'un événement ne doit ni bloquer ni s'afficher.
                    console.warn("Compagnon: erreur sur l'événement " + parsed.event + " : " + e + (e.stack ? "\n" + e.stack : ""));
                }
            }
        }
        stderr: SplitParser {
            onRead: data => console.warn("Compagnon: " + data)
        }
        onExited: {
            root.connected = false;
            root.mood = "idle";
            root.streaming = false;
            root.actionText = "";
            root.clearCard();   // une carte sans moteur derrière n'attend plus rien
            root.problem = root.tr.service_stopped;
        }
    }

    // Le bandeau de la voix : sa propre fenêtre, sans voile ni clavier (voir VoiceStrip.qml).
    VoiceStrip {
        app: root
    }

    PanelWindow {
        id: panel
        visible: root.opened
        // Quel que soit le chemin qui masque la fenêtre (close(), widget de barre, shell),
        // le micro se coupe et le backend n'écoute plus tant que le panneau est masqué.
        onVisibleChanged: {
            if (!visible) {
                root.opened = false;
                root.quietOpen = false;
                root.write({ command: "hidden" });
            }
        }
        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }
        color: "transparent"
        WlrLayershell.namespace: "omarchy-companion"
        WlrLayershell.layer: WlrLayer.Overlay
        // Comme KeyboardPanel d'Omarchy : bref passage en Exclusive pour prendre le clavier à
        // l'ouverture, puis OnDemand. Rester en Exclusive enverrait tous les clics à ce panneau,
        // même ceux faits sur un autre écran.
        WlrLayershell.keyboardFocus: root.opened
            ? (focusPrimeTimer.primed ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.Exclusive)
            : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore

        // Voile propre à Alison : le bureau s'efface derrière le panneau. Celui du thème est
        // presque transparent et laissait lire le terminal au travers.
        Rectangle {
            anchors.fill: parent
            color: Util.alpha(Color.menu.background, 0.8)
        }
        MouseArea {
            anchors.fill: parent
            onClicked: root.dismiss()
        }
        BorderSurface {
            id: card
            anchors.centerIn: parent
            width: Math.min(Style.space(660), panel.width - Style.gapsOut * 2)
            height: Math.min(Style.space(730), panel.height - Style.gapsOut * 2)
            radius: Style.cornerRadius
            color: Color.menu.background
            borderSpec: Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(2)))
            MouseArea {
                anchors.fill: parent
            }
            // Raccourcis du panneau pour tout élément qui laisse passer la touche (bulle cliquée,
            // pastille, bouton). Le champ de saisie, lui, avale Entrée : il appelle `shortcut` lui-même.
            Keys.onPressed: event => root.shortcut(event)
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Style.spacing.panelPadding
                spacing: Style.spacing.lg

                PanelHeader {
                    app: root
                    Layout.fillWidth: true
                }
                // Pendant l'assistant, ni mode ni accès : on suit le parcours, on ne le contourne pas (QA du 18/10).
                StatusChips {
                    app: root
                    visible: root.view !== "welcome"
                    Layout.fillWidth: true
                }
                PanelSeparator {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    foreground: Color.menu.text
                }
                ChatView {
                    id: chat
                    app: root
                    visible: root.view === "chat"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
                SettingsView {
                    id: settingsView
                    app: root
                    visible: root.view === "settings"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
                JournalView {
                    id: journalView
                    app: root
                    visible: root.view === "journal"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
                WelcomeView {
                    id: welcomeView
                    app: root
                    visible: root.view === "welcome"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.problem !== ""
                    text: root.problem
                    wrapMode: Text.Wrap
                    color: Color.urgent
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.bodySmall
                }
                Button {
                    // Seulement quand le moteur est vraiment arrêté : pendant qu'il démarre,
                    // l'en-tête dit déjà « Connexion… ».
                    visible: !root.connected && !bridge.running
                    text: root.tr.reconnect
                    bordered: true
                    foreground: Color.menu.text
                    fontFamily: Style.font.menuFamily
                    onClicked: {
                        root.problem = "";
                        bridge.running = true;
                    }
                }
                ApprovalCard {
                    app: root
                    Layout.fillWidth: true
                }
                // Pendant l'assistant de première installation, ni saisie ni micro : on règle, on ne parle pas.
                Composer {
                    id: composer
                    app: root
                    visible: root.view !== "welcome"
                    Layout.fillWidth: true
                }
                HarnessLine {
                    app: root
                    visible: root.provider === "omarchy" && root.view !== "welcome"
                    Layout.fillWidth: true
                }
            }
        }
    }
}
