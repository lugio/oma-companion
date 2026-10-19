#!/usr/bin/env python3
"""Garde natif Claude Code (hook PreToolUse).

Étape 2 : l'agent peut modifier la machine en ton nom, chaque action passant par ta
validation dans le panneau. Le garde ne bloque plus que ce qui ne doit JAMAIS passer,
même validé d'un clic : les emplacements de secrets, l'élévation de privilèges et les
commandes destructrices ou qui touchent au système hors de ton espace.

Deux niveaux, selon le mode du panneau (`guard.py code|assistant [--policy-file <fichier-600>]`) :
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
import tempfile

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
# emplacements privés déclarés dans les réglages (politique privée par fichier) s'y ajoutent.
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
        _, words = leading_assignments(part.strip().split())
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

# Catalogue fermé des variantes de lecture. Toute option inconnue repasse par une carte
# (ou un refus en Lecture), y compris les abréviations GNU et les options groupées.
# (drapeaux courts, options courtes à valeur, drapeaux longs, options longues à valeur)
READ_OPTIONS = {
    "ls": ("aAbBcCdDfFgGhHiIklLmNnOpqQrRsStTuUvwxX1Z", "IwT", "all almost-all directory human-readable inode numeric-uid-gid recursive reverse size color classify file-type group-directories-first", "color format sort time time-style quoting-style block-size width tabsize ignore hide"),
    "cat": ("AbEnstTuv", "", "show-all number-nonblank show-ends number squeeze-blank show-tabs show-nonprinting", ""),
    "head": ("qv", "cn", "quiet silent verbose zero-terminated", "bytes lines"),
    "tail": ("fFqv", "cns", "follow retry quiet silent verbose zero-terminated", "bytes lines sleep-interval max-unchanged-stats pid"),
    "grep": ("EFGHPivwxyoznqslLchbrRUIa", "e f A B C m d D".replace(" ", ""), "extended-regexp fixed-strings basic-regexp perl-regexp ignore-case word-regexp line-regexp invert-match only-matching count files-with-matches files-without-match line-number byte-offset with-filename no-filename quiet silent recursive dereference-recursive text binary line-buffered null-data null no-messages", "regexp file after-context before-context context max-count directories devices binary-files include exclude exclude-from exclude-dir color"),
    "stat": ("Lf", "ct", "dereference file-system terse", "format printf"),
    "df": ("ahHiklmPT", "Btx", "all human-readable si inodes local portability print-type sync no-sync total", "block-size type exclude-type output"),
    "du": ("abcDhHklLmsSx", "Bd", "all apparent-size bytes total human-readable si count-links dereference no-dereference summarize one-file-system null", "block-size max-depth exclude exclude-from threshold time time-style"),
    "free": ("bkmghwlt", "s c".replace(" ", ""), "bytes kilo mega giga tera kibi mebi gibi tebi human wide lohi total si", "seconds count"),
    "uptime": ("ps", "", "pretty since", ""),
    "pgrep": ("flanovxcw", "dPuUgGsStFr", "full list-name list-full newest oldest inverse count exact lightweight ignore-case", "delimiter parent pgroup group egroup uid euid session terminal pidfile runstates ns nslist cgroup env"),
    "uname": ("asnrvmpio", "", "all kernel-name nodename kernel-release kernel-version machine processor hardware-platform operating-system", ""),
    "lsblk": ("abdfilmnOpPrsStzJ", "oIxE", "all bytes discard ascii fs inverse list merge noheadings nodeps pairs paths raw scsi topology json", "output exclude include sort dedup tree"),
    "lscpu": ("abBceJx", "", "all online offline bytes json hex", "extended parse caches output-all"),
    "lsusb": ("tvV", "sd", "tree verbose version", "show device"),
    "lspci": ("vntbDkmm", "sd", "", ""),
    "nproc": ("", "", "all", "ignore"),
    "date": ("uIR", "dr", "utc universal iso-8601 rfc-email", "date reference rfc-3339 resolution"),
    "cal": ("13jmy", "AB", "", ""),
    "wc": ("clmwL", "", "bytes chars lines words max-line-length", "files0-from"),
    "file": ("bchiLNprsv0", "efFmP", "brief mime mime-type mime-encoding dereference no-dereference no-buffer separator preserve-date raw special-files keep-going", "exclude exclude-quiet files-from separator magic-file parameter"),
    "which": ("as", "", "all skip-alias skip-functions skip-dot skip-tilde show-dot show-tilde", ""),
    "sensors": ("Auj", "c", "no-adapter fahrenheit", "config-file"),
    "id": ("GgnruzZ", "", "groups group name real user zero context", ""),
    "whoami": ("", "", "", ""),
    "acpi": ("abctVifs", "", "battery ac-adapter cooling thermal everything fahrenheit kelvin show-empty", ""),
    "upower": ("edimv", "", "enumerate dump monitor monitor-detail version", "show-info"),
    "systemctl": ("alq", "ntp", "user all full no-pager no-legend plain quiet failed reverse recursive", "lines type state property output"),
    "journalctl": ("abefklmqrux", "b n u t p o S U D".replace(" ", ""), "all boot catalog follow kernel list-boots no-pager no-hostname quiet reverse system user utc disk-usage header verify", "boot lines unit user-unit identifier priority output since until directory file field grep output-fields"),
    "pacman": ("Qqelisumndt", "", "query quiet explicit info list search upgrades foreign native deps unrequired", ""),
    "wpctl": ("", "", "", ""),
    "bluetoothctl": ("", "", "", ""),
    "cut": ("nsz", "bcdf", "only-delimited complement zero-terminated", "bytes characters delimiter fields output-delimiter"),
    "sort": ("bdfgihMnRrsuVz", "kt", "ignore-leading-blanks dictionary-order ignore-case general-numeric-sort human-numeric-sort month-sort numeric-sort random-sort reverse stable unique version-sort zero-terminated check merge", "key field-separator sort random-source parallel batch-size buffer-size files0-from"),
    "uniq": ("cduiz", "fsw", "count repeated unique ignore-case zero-terminated", "skip-fields skip-chars check-chars all-repeated group"),
    "diff": ("abBcdefilnNpqrsStTuywZ", "CUxX", "text ignore-space-change ignore-blank-lines ignore-case brief recursive report-identical-files strip-trailing-cr normal ed forward-ed rcs side-by-side expand-tabs initial-tab left-column suppress-common-lines", "context unified exclude exclude-from label width tabsize horizon-lines line-format old-line-format new-line-format unchanged-line-format old-group-format new-group-format unchanged-group-format changed-group-format"),
    "tree": ("adfghilnpqrsuDFJQNUxAC", "LPI", "all dirsfirst filesfirst noreport prune full-path noemptydirs du inodes device human-readable si ascii charset gitignore", "level pattern ignore matchdirs filelimit sort timefmt ignorefile"),
    "realpath": ("eLmqsz", "", "canonicalize-existing logical canonicalize-missing quiet strip no-symlinks zero", "relative-to relative-base"),
    "basename": ("asz", "", "multiple zero", "suffix"),
    "dirname": ("z", "", "zero", ""),
    "rg": ("FhilLnNoqsvwxcIuUPzSa", "e f g t T m A B C j".replace(" ", ""), "fixed-strings ignore-case case-sensitive smart-case invert-match word-regexp line-regexp line-number no-line-number only-matching count count-matches files files-with-matches files-without-match hidden no-ignore no-ignore-vcs no-heading heading with-filename no-filename json multiline multiline-dotall text null null-data line-buffered no-messages stats", "regexp file glob iglob type type-not max-count after-context before-context context threads max-depth max-filesize color colors encoding sort sortr"),
    "fd": ("aHILlps0", "eEgdtj", "absolute-path hidden no-ignore no-ignore-vcs follow list-details full-path print0 show-errors", "extension exclude glob type max-depth min-depth exact-depth threads size changed-within changed-before newer older base-directory search-path color"),
    "jq": ("acejnrRMsS", "", "compact-output ascii-output exit-status join-output null-input raw-output raw-input monochrome-output slurp sort-keys tab", "indent"),
    "shellcheck": ("aCxsV", "efPSW", "check-sourced external-sources version wiki-link-count", "exclude format shell severity source-path enable"),
}


def leading_assignments(words):
    """Les affectations n'existent qu'avant le programme : après, ce sont ses arguments."""
    index = 0
    while index < len(words) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[index]):
        index += 1
    return words[:index], words[index:]


def closed_read_options(program, args):
    if program not in READ_OPTIONS:
        return ""
    flags, valued, long_flags, long_valued = READ_OPTIONS[program]
    long_flags = set(long_flags.split()) | {"help", "version"}
    long_valued = set(long_valued.split())
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            break
        if arg in ("", "-") or not arg.startswith("-"):
            continue
        if program in ("head", "tail") and re.fullmatch(r"-\d+", arg):
            continue
        if arg.startswith("--"):
            option, equals, _ = arg[2:].partition("=")
            if option in long_valued:
                if not equals:
                    if index >= len(args):
                        return f"{program} (option sans valeur)"
                    index += 1
            elif option not in long_flags or equals:
                return f"{program} (option non autorisée)"
        else:
            for pos, char in enumerate(arg[1:], 1):
                if char in valued:
                    if pos == len(arg) - 1:
                        if index >= len(args):
                            return f"{program} (option sans valeur)"
                        index += 1
                    break
                if char not in flags:
                    return f"{program} (option non autorisée)"
    if program == "systemctl":
        # Les préfixes natifs ne donnent accès qu'à ces lectures, jamais aux verbes de mutation.
        operands = [arg for arg in args if not arg.startswith("-")]
        if not operands or operands[0] not in SYSTEMCTL_READ:
            return "systemctl (action)"
    return ""


SYSTEMCTL_READ = {"status", "list-units", "list-unit-files", "is-active", "is-enabled"}
HELPERS = {"ha.py", "mail.py", "dolibarr.py", "portail.py", "reachy.py", "delegue.py"}
HELPER_EXPANSION = re.compile(r"[?*\[\]{}~$`\\<>;|&()]|\n")


def helper_expansion(command):
    """Les helpers hors bac à sable ne reçoivent que des arguments littéraux, même cités."""
    parts = segments(command)
    if parts is None:
        return "commande illisible"
    for words in parts:
        _, words = leading_assignments(words)
        if any(Path(word).name in HELPERS for word in words):
            if HELPER_EXPANSION.search(command):
                return "expansion ou redirection dans un appel sensible"
    return ""


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


def shell_evaluates(command):
    """Aucune pré-autorisation ne vaut pour une commande que le shell transforme ou compose.

    Les motifs cités littéralement restent des données (`grep '[abc]'`, `sed -n '$p'`). Une
    variable, un joker non cité ou une substitution pourrait fabriquer une option d'écriture ; une
    redirection disparaîtrait au découpage. Les enchaînements `|`, `;`, `&&`, `||` restent permis :
    `segments()` contrôle chaque commande simple séparément (sans eux, `cat f | grep x` était refusé
    en Lecture — relecture du 19/10).
    """
    quote, escaped = "", False
    for char in command:
        if escaped:
            escaped = False
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            continue
        if char == "\\":
            escaped = True
        elif char in ("'", '"') and not quote:
            quote = char
        elif char == quote:
            quote = ""
        elif char in "$`" or (not quote and char in "*?[{~<>()"):
            return True
    return bool(quote or escaped)


def risky_read(words):
    """Raison de redemander une carte pour UNE commande simple, ou chaîne vide."""
    assignments, words = leading_assignments(words)
    if assignments:
        return "environnement de commande modifié"
    if not words:
        return ""
    program, args = Path(words[0]).name, words[1:]
    # Ces outils peuvent charger des exécutables depuis leur configuration locale/de projet.
    # Ils restent disponibles par carte ; aucune option n'est une preuve de lecture seule.
    if program in ("git", "npm", "pip", "pip3", "qmllint", "fastfetch"):
        return f"{program} (configuration exécutable)"
    if program == "fdfind":
        closed = closed_read_options("fd", args)
        if closed:
            return closed
    closed = closed_read_options(program, args)
    if closed:
        return closed
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
        return "awk (interpréteur)"
    if program == "find":
        flags = {"-P", "-L", "-H", "-print", "-print0", "-ls", "-prune", "-quit", "-empty", "-readable", "-writable", "-executable", "-true", "-false", "-a", "-and", "-o", "-or", "-not", "!"}
        valued = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-type", "-size", "-mtime", "-mmin", "-maxdepth", "-mindepth", "-user", "-group", "-perm", "-newer", "-samefile", "-links"}
        index = 0
        while index < len(args):
            arg = args[index]
            index += 1
            if arg in valued and index < len(args):
                index += 1
            elif arg.startswith("-") and arg not in flags:
                return "find (expression non autorisée)"
    if program == "diff" and any(arg.startswith(("--output", "--from-file", "--to-file")) for arg in args):
        return "diff (option non autorisée)"
    if program == "uniq" and len([arg for arg in args if not arg.startswith("-")]) > 1:
        return "uniq (fichier de sortie)"
    if program == "jq" and any(re.search(r"\benv\b|\bimport\b|\binclude\b|\$ENV|\$__loc__|input_filename", arg) for arg in args):
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

    Les variantes qui écrivent ou exécutent demandent une carte en modes d'action, et sont refusées
    en Lecture. Le même contrôle s'applique donc aux programmes pré-autorisés dans les quatre modes."""
    if tool != "Bash" or mode not in ("read", "assistant", "code", "auto"):
        return ""
    command = str(tool_input.get("command", ""))
    if shell_evaluates(command):
        return "expansion, redirection ou composition shell"
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
    """Catalogue fermé : aucun interpréteur, Lua, chemin exécutable ou option inconnue."""
    parts = segments(command)
    if parts is None:
        return "commande illisible"
    desktop = {"hyprctl", "uwsm", "omarchy", "xdg-open", "systemctl", "wpctl", "pactl", "playerctl",
               "brightnessctl", "notify-send", "makoctl", "bluetoothctl", "nmcli"}
    if len(parts) > 1 and any(words and Path(leading_assignments(words)[1][0]).name in desktop
                              for words in parts if leading_assignments(words)[1]):
        return "commande composée avec un outil hors bac à sable"
    for words in parts:
        assignments, words = leading_assignments(words)
        if not words:
            continue
        head = Path(words[0]).name
        if head in INTERPRETERS | {"command", "nice", "timeout", "stdbuf"} and any(
                re.search(r"(?:^|[/\s;|&])(?:hyprctl|uwsm|omarchy|xdg-open|systemctl)(?=\s|$)", word) for word in words[1:]):
            return "lanceur indirect non autorisé"
        launcher = any(tuple([head] + words[1:len(key)]) == key for key in LAUNCHERS)
        # Les options avant le sous-verbe ne doivent pas masquer un lanceur.
        if head == "hyprctl":
            reads = {"activewindow", "clients", "monitors", "workspaces", "binds", "version", "devices", "configerrors"}
            rest = words[1:]
            if rest[:1] == ["-j"]:
                rest = rest[1:]
            if not assignments and len(rest) == 1 and rest[0] in reads:
                continue
            launcher = True
        elif head == "systemctl":
            if "--user" not in words[1:]:
                if not assignments and not closed_read_options("systemctl", words[1:]):
                    continue
                return "systemctl (forme absente du catalogue)"
            launcher = True
        elif head == "uwsm":
            launcher = True
        if not launcher:
            continue
        if assignments or any(re.search(r"[*\[\]{}$`\\~\n]", word) for word in words[1:]):
            return f"{head} (expansion ou environnement)"
        args = words[1:]
        allowed = False
        if head == "hyprctl":
            dispatchers = {
                "workspace": r"(?:[1-9]|1[0-9]|20)", "focusmonitor": r"[0-9]+",
                "movefocus": r"[lrud]", "swapwindow": r"[lrud]", "fullscreen": r"[012]",
                "togglefloating": r"", "killactive": r"",
            }
            if len(args) in (2, 3) and args[0] == "dispatch" and args[1] in dispatchers:
                allowed = re.fullmatch(dispatchers[args[1]], args[2] if len(args) == 3 else "") is not None
        elif head == "uwsm":
            # Un identifiant du catalogue, jamais un binaire ou ses arguments.
            rest = args[1:]
            if rest[:2] == ["-t", "service"]:
                rest = rest[2:]
            if rest[:1] == ["--"]:
                rest = rest[1:]
            allowed = args[:1] == ["app"] and len(rest) == 1 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.desktop", rest[0]) is not None
        elif head in ("omarchy", "xdg-open"):
            rest = args
            if head == "omarchy":
                rest = args[2:] if len(args) >= 2 and args[1] in ("browser", "webapp") else []
            allowed = len(rest) == 1 and re.fullmatch(r"https?://[^\s'\"`$\\<>]+", rest[0]) is not None
        elif head == "systemctl":
            # --user doit être le seul préfixe des mutations ; les lectures gardent leurs options.
            rest = args[1:] if args[:1] == ["--user"] else []
            if rest and rest[0] in SYSTEMCTL_READ:
                allowed = not closed_read_options("systemctl", args)
            elif rest == ["daemon-reload"]:
                allowed = True
            elif rest and rest[0] in {"start", "stop", "restart", "reload", "try-restart", "enable", "disable", "mask", "unmask"}:
                allowed = len(rest) > 1 and all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_@:.+-]*", unit)
                                                for unit in rest[1:])
        if not allowed:
            return f"{head} (forme absente du catalogue)"
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
        # Une question de délégation ne doit jamais atteindre un shell dans argv. Seul le hook
        # ci-dessous transforme les requêtes JSON en un appel par fichier privé.
        try:
            tokens = shlex.split(command)
        except ValueError:
            return "Compagnon : commande illisible, refusée."
        if any(Path(token).name == "delegue.py" for token in tokens):
            if (len(tokens) != 5 or Path(tokens[0]).name not in ("python3", "python")
                    or Path(tokens[1]).name != "delegue.py" or tokens[3] != "--question-file"):
                return "Compagnon : délégation attendue par fichier privé créé par le hook."
        expansion = helper_expansion(command)
        if expansion:
            return "Compagnon : appel sensible non littéral, refusé."
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
        if mode == "read" and needs_card(tool, tool_input, mode):
            return "Compagnon : mode Lecture — cette variante peut écrire ou exécuter, action refusée."
    return None


def delegation_input(tool, tool_input, policy_path, enabled):
    """Réécrit AVANT le shell : la question arrive dans le JSON stdin du hook, pas dans ps.

    Contrat officiel PreToolUse.updatedInput : la permission native est réévaluée sur la nouvelle
    commande. Ne jamais renvoyer « allow » ici, ni élargir les droits du rôle appelé.
    """
    if tool != "Bash" or not enabled or policy_path is None:
        return tool_input, None
    try:
        words = shlex.split(str(tool_input.get("command", "")))
    except ValueError:
        return tool_input, None
    helper = str(Path(__file__).resolve().parent / "delegue.py")
    if len(words) != 4 or words[:2] != ["python3", helper]:
        return tool_input, None
    import roles
    if not roles.canonical_name(words[2]) or not words[3].strip() or len(words[3]) > 16000:
        raise ValueError("délégation illisible")
    descriptor, name = tempfile.mkstemp(prefix=policy_path.name + "-question-", dir=policy_path.parent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(words[3])
    # Aucun texte métier dans la commande, même celle du shell parent.
    command = shlex.join(["python3", helper, words[2], "--question-file", name])
    return dict(tool_input, command=command, description=""), Path(name)


def main():
    # Fermé par défaut : pour Claude Code, seul le code 2 bloque. Une entrée illisible ou une
    # erreur du garde qui sortirait en code 1 laisserait l'outil s'exécuter.
    question_file = None
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError("entrée non objet")
        args = sys.argv[1:]
        mode = next((word for word in args if word in ("chat", "read", "code", "assistant", "auto")), "assistant")
        private, forbid, policy_path, delegate = [], [], None, False
        if "--policy-file" in args:
            path = Path(args[args.index("--policy-file") + 1])
            # Ne jamais suivre un lien ni charger une politique lisible/modifiable par d'autres.
            stat = path.lstat()
            if path.is_symlink() or not path.is_file() or stat.st_uid != os.getuid() or stat.st_mode & 0o077 \
                    or path.parent.stat().st_mode & 0o077 or stat.st_size > 65536:
                raise ValueError("politique non privée")
            policy = json.loads(path.read_text(encoding="utf-8"))
            private, forbid = policy["private"], policy["forbid"]
            policy_path, delegate = path, policy.get("delegate") is True
            if not all(isinstance(items, list) and all(isinstance(item, str) for item in items)
                       for items in (private, forbid)):
                raise ValueError("politique illisible")
        elif "--private" in args or "--forbid" in args:
            raise ValueError("politique privée attendue par fichier")
        original = data.get("tool_input", {}) or {}
        updated, question_file = delegation_input(str(data.get("tool_name", "")), original, policy_path, delegate)
        data["tool_input"] = updated
        refusal = check(str(data.get("tool_name", "")), data.get("tool_input", {}) or {}, mode, private, forbid)
    except Exception as error:  # noqa: BLE001 - tout échec du garde doit refuser
        print(f"Compagnon : garde en échec ({type(error).__name__}), action refusée.", file=sys.stderr)
        if question_file is not None:
            question_file.unlink(missing_ok=True)
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
        if question_file is not None:
            question_file.unlink(missing_ok=True)
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
    if question_file is not None:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}},
                         ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
