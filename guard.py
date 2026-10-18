#!/usr/bin/env python3
"""Garde natif Claude Code (hook PreToolUse).

Étape 2 : l'agent peut modifier la machine en ton nom, chaque action passant par ta
validation dans le panneau. Le garde ne bloque plus que ce qui ne doit JAMAIS passer,
même validé d'un clic : les emplacements de secrets, l'élévation de privilèges et les
commandes destructrices ou qui touchent au système hors de ton espace.

Deux niveaux, selon le mode du panneau (`guard.py code|assistant [--private <chemin>]…`) :
- Assistant : assistant de bureau. Le coffre et les fichiers d'environnement restent
  fermés, il n'a aucune raison d'y toucher.
- Code : vraie session de développement. Le coffre et les .env s'ouvrent, parce que les
  projets en dépendent ; la règle redevient celle du terminal, s'en servir sans jamais
  l'afficher dans le panneau ni le faire lire à voix haute.
Dans les deux modes restent fermés les secrets qu'aucun travail ne demande de LIRE :
clés privées, trousseau, profils de navigateur et de messagerie.

Contrat du hook : JSON sur stdin ({tool_name, tool_input}), code 2 = refus,
le message sur stderr est renvoyé au modèle.
"""
import json
import os
from pathlib import Path
import re
import shlex
import sys

# Fermés dans TOUS les modes : aucun travail légitime ne demande de lire ces fichiers-là.
PROTECTED = [
    r"\.ssh\b", r"id_(rsa|ed25519|ecdsa)", r"\.gnupg\b", r"\.netrc\b",
    r"\.aws\b", r"\.kube\b", r"\.docker/config\.json",
    r"\.config/gh\b", r"hosts\.yml", r"\.credentials\.json", r"\.codex/auth\.json",
    r"\.local/share/keyrings", r"\.config/mozilla", r"\.mozilla\b",
    r"\.config/chromium", r"BraveSoftware", r"thunderbird",
    r"wireguard", r"system-connections", r"\.pem\b",
    # Une clé privée est TOUJOURS un chemin : exiger le chemin, sinon `e.key` d'un jeu et
    # `jq '.key'` étaient refusés (trouvé à l'essai du 19/09, deux Write refusés).
    r"[/~][\w.@-]*/?[\w.@-]*\.key\b",
    r"\.git-credentials\b", r"\.password-store\b", r"rclone\.conf\b", r"\.npmrc\b", r"\.pypirc\b",
    r"\.claude\.json\b",
    # Idem pour les historiques : les vrais, nommés, précédés d'un point ou d'un slash — sinon
    # `game_history` ou `self.chat_history` étaient refusés.
    r"[/.](bash|zsh|ksh|ash|sh|fish|python|node_repl|psql|mysql|sqlite|irb|redis|lesshst)_history\b",
    r"/proc/[^/\s]+/environ\b",
]

# Fermés au seul mode Assistant. En mode Code ce sont les outils de travail : sans le
# coffre ni les .env, un agent de développement ne peut rien faire sur les projets. Les
# emplacements privés déclarés dans les réglages (`--private ~/mon-coffre`) s'y ajoutent.
PROTECTED_ASSISTANT = [
    r"vault\.json", r"secrets\.json", r"\.env\b",
]

# L'état privé du compagnon : tout ce que l'utilisateur lui a dit depuis le premier jour (notes du
# jour, carnet, historique, rêves, extraits de code, courrier). L'agent n'a aucune raison d'y puiser
# en vrac — le moteur lui donne déjà ce qu'il faut — et une page piégée qui l'y enverrait repartirait
# avec des mois de conversations. En Assistant : refusé. En Code : par l'outil Read, donc par carte.
# `state/` en tête : le dossier des SOURCES s'appelle aussi omarchy-companion, et lire son code
# n'a rien d'interdit.
OWN_STATE = [
    r"state/omarchy-companion/(memory|dreams|extraits)\b",
    r"state/omarchy-companion/(memory|conversation|mail|mail-source)\.json\b",
    r"state/omarchy-companion/(journal\.log|dreams\.md|apercu\.pid)\b",
]


def private_patterns(paths):
    """Un motif par emplacement privé : son nom de fichier ou de dossier, entier."""
    return [r"(^|/)" + re.escape(Path(str(path)).name) + r"(/|\b)" for path in paths if str(path).strip()]

# Ce qu'aucun clic ne peut autoriser : root, destruction, système hors espace utilisateur.
FORBIDDEN = [
    r"\bsudo\b", r"\bpkexec\b", r"\bsu\b", r"\bdoas\b",
    # Le trousseau du système (18/10) : seuls le moteur et les utilitaires d'accès y touchent.
    r"\bsecret-tool\b", r"org\.freedesktop\.secrets", r"\bgnome-keyring", r"\bkeyring\b\s+(get|set|del)",
    # rm récursif ET forcé, options groupées (-rf) ou séparées (-r -f, --recursive --force).
    r"\brm\b(?=[^;&|]*\s(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b)(?=[^;&|]*\s(-[a-zA-Z]*f[a-zA-Z]*|--force)\b)",
    r"\brm\b.*\s(/|~|\$HOME|/home/\w+)/?(\s|$)",
    r"\bmkfs", r"\bdd\b", r"\bshred\b", r"\bwipefs\b", r"\bcryptsetup\b", r"\bparted\b", r"\bfdisk\b",
    r"\bchmod\s+(-R\s+)?[0-7]*777\b", r"\bchown\b.*\broot\b",
    r"\bpacman\s+-(S|R|U)", r"\byay\b", r"\bparu\b", r"\bmakepkg\b",
    r"\bomarchy\s+(update|install|remove|reinstall|pkg|setup|plymouth\s+set)\b",
    r"\bsystemctl\s+(?!--user\b)(start|stop|restart|enable|disable|mask|daemon-reload|kill)\b",
    r"\breboot\b", r"\bshutdown\b", r"\bpoweroff\b", r"\bhalt\b", r"\bkexec\b",
    r"\bkill(all)?\s+(-9\s+)?(-1|1)\b", r"\bpkill\s+(-9\s+)?(-u\s+)?root\b",
    r"\bgit\s+push\b.*(--force|-f)\b", r"\bgit\s+reset\s+--hard\b",
    r"\bcurl\b.*\|\s*(ba)?sh\b", r"\bwget\b.*\|\s*(ba)?sh\b",
    r"\btee\b\s+(-a\s+)?/(etc|usr|boot|var|opt|root)/",
    r"\bcrontab\s+-r\b", r"\bnmcli\b.*\b(delete)\b",
]
# Programmes à fenêtre lancés au premier plan : la commande ne rend la main qu'à la fermeture de
# la fenêtre, et Alison reste bloquée sur « je réfléchis » pendant ce temps (constaté le
# 19/09 : un article Wikipédia ouvert, le panneau figé jusqu'à ce qu'il ferme l'onglet). Refusé avec
# la bonne commande dans le message : Omarchy lance tout par `systemd-run`/`uwsm`, qui rendent la
# main tout de suite. Seul le PREMIER mot compte — `pkill firefox` ou `grep firefox` n'ont rien à voir.
WINDOWED = ("firefox", "chromium", "google-chrome", "google-chrome-stable", "brave", "brave-browser",
            "microsoft-edge", "vivaldi", "opera", "zen-browser", "thunderbird", "nautilus", "obsidian",
            "signal-desktop", "spotify", "xdg-open", "gio")


def windowed_launch(command):
    """Premier programme de la commande s'il ouvre une fenêtre au premier plan, sinon une chaîne vide."""
    for part in re.split(r"[;&|]+", command):
        words = [word for word in part.strip().split() if not re.match(r"^[A-Z_][A-Z0-9_]*=", word)]
        # Enveloppes qui ne changent rien au problème : `sh -c firefox …` bloque autant que
        # `firefox …`. On les retire pour regarder le vrai programme derrière.
        while words and words[0].rsplit("/", 1)[-1] in ("sh", "bash", "zsh", "env", "nice", "timeout", "stdbuf"):
            words = [word for word in words[1:] if not word.startswith("-") and not word.isdigit()]
        if not words:
            continue
        # Déjà détaché (setsid, systemd-run, uwsm, omarchy launch…) : ce n'est plus le problème.
        if words[0].rsplit("/", 1)[-1] in ("setsid", "systemd-run", "uwsm", "uwsm-app", "nohup",
                                           "omarchy", "hyprctl", "gtk-launch", "dex"):
            continue
        name = words[0].rsplit("/", 1)[-1]
        if name in WINDOWED:
            return name
    return ""


# Redirections vers le système : lues sur le texte HORS apostrophes, parce qu'un programme awk ou
# sed entre apostrophes contient des « > » de comparaison (`awk 'NR>1'`).
FORBIDDEN_REDIRECTS = [r"(^|\s)(>|>>)\s*/(etc|usr|boot|var|opt|root)(/|\s|$)"]

# Chemins système : aucune écriture par les outils Edit/Write.
SYSTEM_PATHS = r"^/(etc|usr|boot|var|opt|root|sys|proc)(/|$)"


def unquoted(text):
    """Texte sans apostrophes, guillemets ni barres obliques inverses : `su''do`, `~/.co"ff"re`
    ou `sh -c 'sudo …'` redeviennent lisibles. Le mur système (bac à sable) reste la vraie
    barrière ; le garde ne lit que du texte."""
    return re.sub(r"[\"'\\]", "", text)


# Ce qui écrit, quel que soit le chemin. Refusé d'office dans les modes qui ne peuvent rien changer.
WRITING_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def forbidden_word(command, forbid):
    """Premier mot interdit par le RÔLE trouvé dans la commande, sinon une chaîne vide.

    C'est ici que vit la loi d'un rôle (`"forbid": ["smtp", "sendmail"]` dans son role.json).
    Écrite dans la personnalité, « je n'envoie jamais d'email » est une consigne, et une consigne
    se contourne ; ici, c'est le harnais qui refuse, quoi que le modèle décide. On ne regarde que
    les COMMANDES : interdire le mot dans un fichier écrit reviendrait à refuser d'éditer une
    configuration qui le mentionne.

    Le mot est cherché TEL QUEL, n'importe où, sans frontière de mot : « smtp » attrape aussi
    `msmtp` et `smtplib`. C'est voulu — avec une frontière, interdire « smtp » laissait passer
    `msmtp -t` (trouvé par le test au premier essai). Une loi qui se contourne en changeant de
    programme n'est pas une loi ; c'est l'auteur du rôle qui choisit ses mots.
    """
    lowered = command.casefold()
    for word in forbid:
        word = str(word).casefold().strip()
        if word and word in lowered:
            return word
    return ""


# Programmes pré-autorisés en mode Code parce qu'ils LISENT — mais certaines options leur font
# écrire, exécuter ou sortir sur le réseau (audit du 18/10 : `find -delete`, `sort -o`, `rg --pre`…).
# Ces formes-là repassent par une carte : le garde répond « ask » au lieu de laisser passer.
RISKY_OPTIONS = {
    "find": ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"),
    "fd": ("-x", "-X", "--exec", "--exec-batch"),
    "fdfind": ("-x", "-X", "--exec", "--exec-batch"),
    "rg": ("--pre", "--pre-glob"),
    "sort": ("-o", "--output", "--compress-program", "-T", "--temporary-directory"),
    "tree": ("-o",),
    "git": ("--output", "--ext-diff", "--textconv", "--upload-pack", "--exec"),
    "qmllint": ("--fix", "-f", "--write-defaults"),
}
SED_OPTIONS = ("-n", "--quiet", "--silent", "-E", "-r", "--regexp-extended", "-s", "--separate", "-u",
               "--unbuffered", "-z", "--null-data", "--posix", "--debug")
JOURNALCTL_WRITES = ("--vacuum", "--rotate", "--flush", "--sync", "--relinquish", "--smart-relinquish",
                     "--setup-keys", "--update-catalog", "--cursor-file")
SHORT_LETTERS = {"sort": "oT", "tree": "o", "fd": "xX", "fdfind": "xX", "qmllint": "f"}
GIT_BRANCH_WRITES = ("-d", "-D", "-m", "-M", "-c", "-C", "-f", "-u", "--delete", "--move", "--copy", "--force",
                     "--unset-upstream", "--edit-description", "--track", "--no-track")
GIT_BRANCH_WRITES_LONG = ("--set-upstream-to", "--track=", "--create-reflog")
SHELL_SEPARATORS = re.compile(r"&&|\|\||[;|&\n`]|\$\(|<\(|>\(|[<>]")
# Un programme sed/awk ne se lit pas à coup de listes d'options : on n'accepte sans carte que des
# formes qu'on sait lire (afficher des lignes, imprimer des champs).
SED_PRINT = re.compile(r"^\s*(\d+|\$)?\s*(,\s*(\d+|\$))?\s*p\s*$")
AWK_DANGER = re.compile(r"system|getline|[|>]|@load|ENVIRON|\bclose\b|fflush", re.IGNORECASE)
LOCAL_URL = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/|$)")


def segments(command):
    """Les commandes simples d'une ligne shell, découpées hors guillemets. None si illisible."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()`\n")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    out, current = [], []
    for token in tokens:
        if token and all(char in ";&|<>()`\n" for char in token):
            if current:
                out.append(current)
            current = []
        else:
            current.append(token)
    if current:
        out.append(current)
    return out


def risky_read(words):
    """Raison de redemander une carte pour UNE commande simple, ou chaîne vide."""
    words = [word for word in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word)]
    if not words:
        return ""
    program, args = Path(words[0]).name, words[1:]
    for option in RISKY_OPTIONS.get(program, ()):
        short = len(option) == 2          # « -o » colle sa valeur : « -ofichier »
        if any(arg == option or arg.startswith(option + "=") or (short and arg.startswith(option))
               for arg in args):
            return f"{program} {option}"
    # Options courtes groupées (« sort -rofichier ») : la lettre dangereuse peut être au milieu.
    letters = SHORT_LETTERS.get(program, "")
    if letters and any(arg.startswith("-") and not arg.startswith("--") and set(arg[1:]) & set(letters)
                       for arg in args):
        return f"{program} (options groupées)"
    if program == "git" and args:
        sub = [arg for arg in args[1:] if not arg.startswith("-")]
        if args[0] == "remote" and sub[:1] not in ([], ["show"], ["get-url"]):
            return "git remote " + sub[0]
        if args[0] == "branch" and (sub or any(arg.split("=", 1)[0] in GIT_BRANCH_WRITES
                                               or arg.startswith(GIT_BRANCH_WRITES_LONG) for arg in args[1:])):
            return "git branch (écriture)"
    if program == "sed":
        # Liste POSITIVE : afficher des lignes (« sed -n '1,20p' f »), rien d'autre — ni script
        # chargé d'un fichier, ni édition sur place, ni option inconnue.
        options = [arg for arg in args if arg.startswith("-")]
        scripts = [arg for arg in args if not arg.startswith("-")][:1]
        if any(arg not in SED_OPTIONS for arg in options) \
                or not scripts or not all(SED_PRINT.match(part) for part in scripts[0].split(";") if part.strip()):
            return "sed (script)"
    if program == "journalctl" and any(arg.startswith(JOURNALCTL_WRITES) for arg in args):
        return "journalctl (écriture)"
    if program == "file" and any(arg in ("-C", "--compile") or (arg.startswith("-") and not arg.startswith("--")
                                                                 and "C" in arg) for arg in args):
        return "file --compile"
    if program in ("awk", "gawk", "mawk"):
        if any(arg.startswith(("-f", "-i", "-l", "-E", "--file", "--include", "--load", "--exec", "--source"))
               for arg in args) \
                or any(AWK_DANGER.search(arg) for arg in args):
            return "awk (programme)"
    if program == "uniq" and len([arg for arg in args if not arg.startswith("-")]) > 1:
        return "uniq (fichier de sortie)"
    if program == "jq" and any(re.search(r"\benv\b|\$ENV|\$__loc__|input_filename", arg) for arg in args):
        return "jq (environnement)"
    if program == "curl":
        # Liste POSITIVE : vérifier qu'une page locale répond, rien d'autre (pas de config -K, pas
        # d'envoi, pas de sortie vers un fichier). Toute autre option repasse par une carte.
        # Pas de -L : une redirection mènerait hors de la machine.
        flags = {"-s", "--silent", "-S", "--show-error", "-f", "--fail", "-I", "--head",
                 "-sS", "-Ss", "-fsS", "-sSf", "-fs", "-sf", "-sI", "-Is"}
        valued = {"-w", "--write-out", "-m", "--max-time", "--connect-timeout", "-o", "--output"}
        index = 0
        while index < len(args):
            arg = args[index]
            if arg in valued:
                if index + 1 >= len(args) or (arg in ("-o", "--output") and args[index + 1] != "/dev/null"):
                    return "curl (réseau)"
                # « -w » sait écrire un fichier (%output{…}) ou en lire un (@fichier).
                if arg in ("-w", "--write-out") and ("%output" in args[index + 1] or args[index + 1].startswith("@")):
                    return "curl (réseau)"
                index += 2
                continue
            if arg.startswith("-") and arg not in flags:
                return "curl (réseau)"
            if not arg.startswith("-") and not LOCAL_URL.match(arg):
                return "curl (réseau)"
            index += 1
    return ""


# Home Assistant : le helper est pré-autorisé pour allumer une lampe sans carte. Mais un ouvrant
# (portail, porte de garage, volet), un interrupteur (qui peut commander une gâche), un script ou une
# scène (qui font n'importe quoi derrière) demandent une carte (audit du 18/10).
HA_CARD_DOMAINS = ("cover", "switch", "script", "scene", "input_boolean")


def ha_action(words):
    """Raison de redemander une carte pour un appel au helper HA, ou chaîne vide."""
    if len(words) < 3 or Path(words[0]).name not in ("python3", "python") or Path(words[1]).name != "ha.py":
        return ""
    verb, rest = words[2], words[3:]
    if verb in ("areas", "state"):
        return ""
    entities = rest[:-1] if verb == "set" else rest
    for entity in entities:
        domain = entity.split(".", 1)[0]
        if domain in HA_CARD_DOMAINS:
            return f"maison : {entity}"
    return ""


def apercu_action(words):
    """L'aperçu est pré-autorisé en Code pour regarder un serveur de dev local : une adresse
    distante y deviendrait un canal de sortie sans carte (revue Codex du 18/10)."""
    if len(words) < 3 or Path(words[0]).name not in ("python3", "python") or Path(words[1]).name != "apercu.py":
        return ""
    target = words[2]
    if target == "--close" or LOCAL_URL.match(target) or not re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
        return ""
    if target.startswith("file://"):
        return ""
    return "aperçu d'une adresse distante"


def needs_card(tool, tool_input, mode):
    """Forme d'une commande pré-autorisée qui doit quand même passer par une carte.

    Assistant, Code et Autonome : programmes de lecture pré-autorisés aux options qui écrivent ou
    exécutent (`journalctl --vacuum…` l'est dès l'Assistant), et actions maison sensibles. Les modes
    fermés n'en ont pas besoin : rien n'y passe sans être refusé."""
    if tool != "Bash" or mode not in ("assistant", "code", "auto"):
        return ""
    command = str(tool_input.get("command", ""))
    parts = segments(command)
    if parts is None:
        return "commande illisible"
    for words in parts:
        reason = ha_action(words) or apercu_action(words) or risky_read(words)
        if reason:
            return reason
    return ""


# Les lanceurs du bureau tournent HORS du bac à sable (agents.DESKTOP_UNSANDBOXED) : ils servent à ouvrir une
# application, jamais à lancer un interpréteur qui, lui aussi hors du mur, lirait le trousseau ou un fichier
# fermé (revue Codex du 18/10 : `uwsm app -- python3 -c …` contournait la protection du trousseau).
LAUNCHERS = {("uwsm", "app"), ("hyprctl", "dispatch"), ("omarchy", "launch"), ("xdg-open",), ("systemctl", "--user")}
INTERPRETERS = {"python", "python3", "perl", "ruby", "node", "deno", "bun", "php", "lua", "sh", "bash", "zsh",
                "fish", "dash", "ksh", "env", "busybox", "awk", "gawk", "gdbus", "busctl", "dbus-send", "qdbus",
                "secret-tool", "sudo", "pkexec", "nohup", "setsid", "xargs", "exec", "eval", "systemd-run"}


def launcher_escape(command):
    """Raison de refuser un lanceur du bureau qui lancerait un interpréteur, ou chaîne vide."""
    parts = segments(command)
    if parts is None:
        return "commande illisible"
    for words in parts:
        words = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
        if not words:
            continue
        head = Path(words[0]).name
        launcher = any(tuple([head] + words[1:len(key)]) == key for key in LAUNCHERS)
        if not launcher:
            continue
        for word in words[1:]:
            # Un joker (« pytho?3 ») ou une substitution se résout APRÈS le garde : refusé d'office.
            if re.search(r"[*?\[\]{}$`\\]", word):
                return f"{head} → {word}"
            name = Path(word.strip("'\"")).name
            base = re.sub(r"[0-9.]+$", "", name)
            if name in INTERPRETERS or base in INTERPRETERS or name.endswith((".py", ".sh", ".pl", ".js")):
                return f"{head} → {name}"
    return ""


def check(tool, tool_input, mode="assistant", private=(), forbid=()):
    if not isinstance(tool_input, dict):
        return f"Compagnon : requête d'outil illisible ({tool}), refusée."
    # Modes fermés : la limite est posée trois fois (permissions natives, refus des cartes par le
    # moteur, et ici). Un seul de ces trois qui tiendrait suffirait ; on ne parie pas là-dessus.
    if mode == "chat":
        return ("Compagnon : mode Discussion — aucun outil n'est disponible. Réponds de ce que tu "
                "sais, ou dis que tu aurais besoin d'un autre mode.")
    if mode in ("chat", "read") and "ha.py" in unquoted(str(tool_input.get("command", ""))):
        return ("Compagnon : mode fermé — la maison ne se pilote qu'à partir du mode Assistant. "
                "Dis ce que tu ferais, l'utilisateur changera de mode s'il le veut.")
    if mode == "read" and tool in WRITING_TOOLS:
        return ("Compagnon : mode Lecture — rien ne s'écrit et rien ne se lance. Dis ce qu'il "
                "faudrait faire, l'utilisateur changera de mode s'il le veut.")
    text = unquoted(" ".join(str(value) for value in tool_input.values()))
    # Le coffre et l'état privé ne s'ouvrent qu'en mode Code, où chaque lecture passe par une carte.
    # En Autonome il n'y a pas de carte : ils restent fermés comme en Assistant (règle d'or : jamais
    # un secret à l'écran, et personne ne relit avant).
    for pattern in (PROTECTED if mode == "code" else PROTECTED + PROTECTED_ASSISTANT + OWN_STATE + private_patterns(private)):
        if re.search(pattern, text, re.IGNORECASE):
            return f"Compagnon : accès refusé ({tool}), emplacement protégé. Ne réessaie pas autrement."
    # Mode Code : les lectures ne demandent plus de carte, sauf sur un emplacement privé. Une
    # commande qui y puise est refusée et renvoyée vers l'outil `Read`, lui toujours validé d'un
    # clic : le coffre reste accessible en Code, mais jamais sans que l'utilisateur le voie.
    if mode == "code" and tool == "Bash":
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in private_patterns(private) + OWN_STATE):
            return ("Compagnon : emplacement privé — passe par l'outil Read, qui demande sa validation, "
                    "au lieu d'une commande.")
    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        path = str(tool_input.get("file_path", tool_input.get("path", "")))
        if re.match(SYSTEM_PATHS, path):
            return "Compagnon : écriture refusée hors de l'espace utilisateur."
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        stripped = re.sub(r"'[^']*'", "''", command)
        barred = forbidden_word(unquoted(command), forbid)
        if barred:
            return (f"Compagnon : « {barred} » est interdit dans ton rôle actuel. C'est une règle du "
                    "harnais, aucune validation ne peut l'autoriser : dis simplement que ce n'est pas "
                    "de ton ressort.")
        if any(re.search(pattern, unquoted(command), re.IGNORECASE) for pattern in FORBIDDEN) \
                or any(re.search(pattern, stripped, re.IGNORECASE) for pattern in FORBIDDEN_REDIRECTS):
            return "Compagnon : commande refusée, elle demande le root ou serait destructrice. Aucune validation ne peut l'autoriser."
        escape = launcher_escape(command)
        if escape:
            return (f"Compagnon : « {escape} » refusé — un lanceur du bureau ouvre une application, jamais un "
                    "interpréteur ou un script (il tournerait hors du bac à sable). Aucune validation ne peut l'autoriser.")
        windowed = windowed_launch(unquoted(command))
        if windowed:
            return (f"Compagnon : `{windowed}` lancé comme ça reste au premier plan et bloque la conversation "
                    "jusqu'à la fermeture de la fenêtre. Utilise `omarchy launch browser <adresse>` pour une page, "
                    "`omarchy launch webapp <adresse>` pour une application web, "
                    "`uwsm app -t service -- <identifiant>.desktop` pour une application installée.")
    return None


def main():
    # Fermé par défaut : pour Claude Code, seul le code 2 bloque. Une entrée illisible ou une
    # erreur du garde qui sortirait en code 1 laisserait l'outil s'exécuter.
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError("entrée non objet")
        args = sys.argv[1:]
        mode = next((word for word in args if word in ("chat", "read", "code", "assistant", "auto")), "assistant")
        private = [args[i + 1] for i, arg in enumerate(args) if arg == "--private" and i + 1 < len(args)]
        forbid = [args[i + 1] for i, arg in enumerate(args) if arg == "--forbid" and i + 1 < len(args)]
        refusal = check(str(data.get("tool_name", "")), data.get("tool_input", {}) or {}, mode, private, forbid)
    except Exception as error:  # noqa: BLE001 - tout échec du garde doit refuser
        print(f"Compagnon : garde en échec ({type(error).__name__}), action refusée.", file=sys.stderr)
        sys.exit(2)
    if not refusal:
        try:
            reason = needs_card(str(data.get("tool_name", "")), data.get("tool_input", {}) or {}, mode)
        except Exception:  # noqa: BLE001 - dans le doute, une carte
            reason = "contrôle en échec"
        if reason:
            # « ask » : Claude Code repasse par la demande de permission, donc par une carte du panneau,
            # même si la commande commence comme une lecture pré-autorisée.
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "ask",
                "permissionDecisionReason": f"Compagnon : « {reason} » peut écrire, exécuter ou sortir sur le réseau."}},
                ensure_ascii=False))
            sys.exit(0)
    if refusal:
        journal = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy-companion/journal.log"
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import storage
            summary = json.dumps(data.get("tool_input", {}), ensure_ascii=False)[:160]
            storage.append_journal(journal, f"REFUS {data.get('tool_name', '')} {summary}")
        except (OSError, ImportError):
            pass
        print(refusal, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
