"""Adaptateurs vers l'agent par défaut d'Omarchy.

Le cerveau n'est pas choisi ici : il vient de `omarchy default agent`
(~/.config/omarchy/defaults/agent). Chaque adaptateur lance cet agent en mode
non interactif avec SES permissions natives, calqué sur la table de
`omarchy-agent`. Aucune couche externe.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import shlex
import shutil
import time
import uuid

import extensions
import modes
import roles
import texts

HOME = Path.home()
# Consigne et réglages du processus Claude : passés par FICHIERS privés, jamais en arguments — une ligne de
# commande est lisible par tout programme de la session (`ps`), et la consigne contient le carnet de
# l'utilisateur, les réglages ses emplacements privés (revue du store, 19/10/2026).
RUN_DIR = (Path(os.environ["XDG_RUNTIME_DIR"]) / "omarchy-companion" / "cerveau" if os.environ.get("XDG_RUNTIME_DIR")
           else HOME / ".local/state/omarchy-companion/cerveau")


def private_file(text, suffix):
    """Écrit `text` dans un fichier 600 d'un dossier 700 (nom imprévisible) et rend son chemin."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUN_DIR, 0o700)
    fd, path = tempfile.mkstemp(prefix="claude-", suffix=suffix, dir=str(RUN_DIR))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path
PLUGIN_DIR = Path(__file__).resolve().parent
GUARD = PLUGIN_DIR / "guard.py"

# Noms affichés des agents d'Omarchy (`omarchy default agent`).
NAMES = {"pi": "Pi", "omp": "Oh My Pi", "opencode": "OpenCode", "claude": "Claude Code",
         "codex": "Codex", "grok": "Grok", "gemini": "Gemini", "openclaw": "OpenClaw",
         "hermes": "Hermes", "copilot": "GitHub Copilot", "crush": "Crush",
         "cursor-agent": "Cursor CLI", "muse": "Muse Code"}

# Commandes de lecture autorisées à Claude Code sans carte (permissions natives).
# Deux listes, parce qu'une règle `Bash(x:*)` accepte TOUS les arguments :
# - préfixes : programmes dont aucun argument ne peut exécuter, écrire ni révéler un secret ;
# - commandes exactes : programmes qui le peuvent avec d'autres arguments. Exclus d'office :
#   `env` (lance n'importe quoi), `printenv` et `ps e` (variables d'environnement, donc clés d'API),
#   `find` (-exec, -delete), `rg` (--pre), `fastfetch` (module Command), `nmcli` (coupe le réseau,
#   `--show-secrets`), `omarchy default agent <nom>` (change l'agent et le lance), `hyprctl` (--batch).
READ_ONLY_PREFIXES = [
    "ls", "cat", "head", "tail", "grep", "stat", "df", "du", "free", "uptime", "pgrep", "journalctl",
    "uname", "lsblk", "lscpu", "lsusb", "lspci", "nproc", "date", "cal", "wc", "file", "which", "sensors",
    "id", "whoami", "systemctl status", "systemctl list-units", "systemctl list-unit-files",
    "systemctl is-active", "systemctl is-enabled", "systemctl --user status", "systemctl --user list-units",
    "pacman -Q", "wpctl get-volume", "bluetoothctl devices", "bluetoothctl show", "acpi", "upower",
]
READ_ONLY_EXACT = [
    "ps aux", "ps -ef", "hostname", "fastfetch", "ip a", "ip addr", "ip route", "ip link",
    "nmcli device", "nmcli device status", "nmcli general", "nmcli general status",
    "nmcli connection show", "nmcli connection show --active",
    "hyprctl activewindow", "hyprctl clients", "hyprctl monitors", "hyprctl workspaces", "hyprctl binds",
    "hyprctl version", "hyprctl devices", "hyprctl configerrors", "hyprctl -j activewindow",
    "hyprctl -j clients", "hyprctl -j monitors", "hyprctl -j workspaces", "hyprctl -j devices",
    "omarchy version", "omarchy commands", "omarchy theme current", "omarchy theme list",
    "omarchy theme bg current", "omarchy plymouth current", "omarchy default agent", "omarchy plugin list",
    "omarchy plugin list --json", "omarchy debug --no-sudo --print",
    "wpctl status", "brightnessctl get", "brightnessctl info",
]

# Outils du terminal Claude Code qui n'ont pas de surface dans le panneau : la question
# ou le document partirait dans le vide. L'agent doit répondre ou demander en français.
INTERACTIVE_TOOLS = ["AskUserQuestion", "ExitPlanMode", "EnterPlanMode",
                     "SendUserFile", "Artifact", "Workflow", "SendMessage"]

def guard_hook(mode, private=(), forbid=()):
    """Le garde connaît le mode : en Code il ouvre les emplacements privés et les .env, en Assistant
    non. Les emplacements privés déclarés dans les réglages lui sont passés en arguments, et les
    mots interdits par le rôle actif avec eux — c'est le harnais qui porte la loi d'un rôle."""
    command = (f"python3 {GUARD} {mode}"
               + "".join(f" --private {shlex.quote(str(path))}" for path in private)
               + "".join(f" --forbid {shlex.quote(str(word))}" for word in forbid))
    return {
        "PreToolUse": [{
            "matcher": "Read|Grep|Glob|Bash|Edit|MultiEdit|Write",
            "hooks": [{"type": "command", "command": command, "timeout": 10}],
        }]
    }

# Mode Assistant : permissions natives serrées, lecture pré-autorisée, le reste par carte.
# Web (choix de conception) : la recherche est libre, elle part vers le moteur de recherche et
# non vers un site choisi par l'agent. Lire une page (WebFetch) passe par la carte, adresse complète
# visible : une page piégée qui voudrait faire sortir un fichier dans une adresse se voit avant de
# partir. Les sites de confiance sont décidés par le moteur (backend.wait_permission), sans relance.
# Les quatre modes, du plus fermé au plus ouvert. Seuls les deux derniers peuvent faire apparaître
# une carte de validation : dans les autres, une demande d'action est refusée d'office par le
# moteur — c'est ce qui rend « elle ne peut rien faire » démontrable et pas seulement promis.
MODES = modes.MODES
CARD_MODES = modes.CARD_MODES
ACT_MODES = modes.ACT_MODES

# Mode Discussion : aucun outil. Elle répond de ce qu'elle sait, et c'est tout. Le plus rapide
# aussi — pas un aller-retour d'outil.
CHAT_SETTINGS = {
    "permissions": {
        "allow": [],
        "deny": ["Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Grep", "Glob",
                 "WebSearch", "WebFetch", "Agent", "Skill"] + INTERACTIVE_TOOLS,
    },
    "hooks": guard_hook("chat"),
}

ASSISTANT_SETTINGS = {
    "permissions": {
        "allow": ["Read", "Grep", "Glob", "WebSearch"]
                 + [f"Bash({prefix}:*)" for prefix in READ_ONLY_PREFIXES]
                 + [f"Bash({prefix})" for prefix in READ_ONLY_PREFIXES + READ_ONLY_EXACT],
        # Edit/Write/Bash de modification et WebFetch passent par la validation dans le panneau.
        # Reste interdit sans discussion : sous-agents, root, effacement récursif, disques.
        # `Skill` : aucune skill n'est chargée ici (`skills: []`), l'outil ne ferait qu'échouer
        # et pousser l'agent à inventer une « autorisation » à activer.
        "deny": ["Agent", "NotebookEdit", "Skill"] + INTERACTIVE_TOOLS
                + ["Bash(sudo:*)", "Bash(pkexec:*)", "Bash(su:*)", "Bash(dd:*)", "Bash(mkfs:*)", "Bash(shred:*)"],
    },
    "hooks": guard_hook("assistant"),
}

# Programmes de lecture supplémentaires d'une session de développement : les faire valider à chaque
# fois noyait les vraies décisions (onze cartes pour un jeu, 19/09). Certaines de leurs options
# écrivent ou exécutent (`find -delete`, `sort -o`, `rg --pre`…) : `guard.needs_card` les renvoie à
# une carte (audit du 18/10). Les interpréteurs (`python3 -c`, `node -e`) n'en font plus partie.
CODE_READ_ONLY = [
    "sed -n", "awk", "cut", "sort", "uniq", "diff", "tree", "realpath", "basename", "dirname",
    "rg", "fd", "find", "jq", "git status", "git log", "git diff",
    "git show", "git branch", "git remote", "git ls-files", "git blame", "git stash list",
    "npm ls", "pip list", "pip show", "qmllint", "shellcheck", "curl -s -o /dev/null",
]

# Mode Code : session de dev complète. Ce qui LIT ne demande plus rien (les programmes ci-dessus et
# ceux du mode Assistant) ; ce qui ÉCRIT, installe, lance ou sort sur le réseau garde sa carte. Le
# hook garde la protection des secrets et du root, et refuse une lecture en vrac d'un emplacement
# privé : le coffre se lit par l'outil `Read`, qui lui demande toujours. Seul l'irrémédiable est
# barré d'office.
CODE_SETTINGS = {
    "permissions": {
        "allow": [f"Bash({prefix}:*)" for prefix in READ_ONLY_PREFIXES + CODE_READ_ONLY]
                 + [f"Bash({rule})" for rule in READ_ONLY_PREFIXES + CODE_READ_ONLY + READ_ONLY_EXACT],
        "deny": INTERACTIVE_TOOLS
                + ["Bash(sudo:*)", "Bash(pkexec:*)", "Bash(su:*)", "Bash(dd:*)", "Bash(mkfs:*)", "Bash(shred:*)"],
    },
    "hooks": guard_hook("code"),
}


# Mode Autonome : les outils du mode Code, et AUCUNE carte — le moteur accepte à la place de
# l'utilisateur et l'écrit au journal. Ce qui reste : le garde, le mur système, les refus d'office.
# Et le coffre : personne ne relit avant, donc il reste fermé comme en Assistant (build_settings).
AUTO_SETTINGS = {
    "permissions": CODE_SETTINGS["permissions"],
    "hooks": guard_hook("auto"),
}


# Mode Lecture : elle lit la machine et cherche sur le web, elle ne change RIEN. Mêmes lectures
# qu'en Assistant ; ce qui écrit, installe ou lance est refusé — et comme aucune carte n'existe
# dans ce mode, rien ne peut être autorisé au passage. Lire une page (WebFetch) demanderait une
# carte : en Lecture, seuls les sites déjà déclarés de confiance restent lisibles.
READ_SETTINGS = {
    "permissions": {
        "allow": list(ASSISTANT_SETTINGS["permissions"]["allow"]),
        "deny": ["Write", "Edit", "MultiEdit", "NotebookEdit", "Agent", "Skill"] + INTERACTIVE_TOOLS
                + ["Bash(sudo:*)", "Bash(pkexec:*)", "Bash(su:*)", "Bash(dd:*)", "Bash(mkfs:*)", "Bash(shred:*)"],
    },
    "hooks": guard_hook("read"),
}

# Bac à sable natif de Claude Code (bubblewrap) : le mur au niveau du système, sous le garde.
# Le garde lit le TEXTE des commandes et se contourne avec un joker ou un chemin découpé ;
# le bac à sable, lui, refuse l'accès au fichier quel que soit le programme qui le demande.
# Les règles `Read(...)` en refus s'appliquent aux outils de lecture ET alimentent le refus
# de lecture du bac à sable (doc « sandboxing » et « permissions », Claude Code 2.1.268).
SECRET_READS = [
    "~/.ssh/**", "~/.gnupg/**", "~/.local/share/keyrings/**",
    "~/.config/mozilla/**", "~/.mozilla/**", "~/.config/chromium/**", "~/.config/BraveSoftware/**",
    "~/.thunderbird/**", "~/.aws/**", "~/.kube/**", "~/.docker/config.json", "~/.config/gh/**",
    "~/.netrc", "~/.codex/auth.json", "~/.claude/.credentials.json", "~/.claude.json",
    "~/.git-credentials", "~/.password-store/**", "~/.config/rclone/**", "~/.npmrc", "~/.pypirc",
    "~/.bash_history", "~/.zsh_history", "~/.local/share/fish/fish_history", "~/.python_history",
    # Variables d'environnement des processus (clés d'API).
    "//proc/*/environ",
    # Le jeton Home Assistant : seul le helper le lit, et il tourne hors bac à sable.
    "~/.config/omarchy-companion/ha.json",
]
# Fermés au seul mode Assistant : en mode Code, ce sont les outils de travail des projets. Les
# emplacements privés de l'utilisateur (réglage `privatePaths`) s'y ajoutent.
SECRET_READS_ASSISTANT = ["//**/.env", "//**/vault.json", "//**/secrets.json",
                          # La mémoire et l'état d'Alison : le garde les refusait par le TEXTE seulement ;
                          # un joker (« mem*.json ») passait (revue Codex du 18/10).
                          "~/.local/state/omarchy-companion/**"]

# Pilotage du bureau : ces outils parlent à Hyprland, PipeWire ou D-Bus par des sockets Unix,
# que le bac à sable coupe (mesuré : « Couldn't open a socket »). Ouvrir TOUS les sockets serait
# une brèche (`hyprctl dispatch exec`, `systemd-run --user`, trousseau par D-Bus) ; on sort donc
# du mur ces seuls programmes. Doc : une commande composée dont une partie est exclue tourne
# entière hors du mur, mais elle passe par les règles de permission, donc par la carte, sauf
# les sous-commandes de lecture pré-autorisées une à une. Le garde relit le texte en plus.
DESKTOP_UNSANDBOXED = ["hyprctl *", "wpctl *", "pactl *", "playerctl *", "brightnessctl *",
                       "notify-send *", "makoctl *", "bluetoothctl *", "nmcli *",
                       "systemctl --user *", "omarchy *", "uwsm app *", "xdg-open *"]

# Mode Code : ce qui a légitimement besoin de la clé SSH ou du réseau local tourne hors du mur,
# toujours par carte. Le bac à sable ne relaie que le web (HTTP) : ping, SSH ou une connexion TCP
# brute y échouent. Constaté : l'agent a testé une machine du réseau local par ping et /dev/tcp dans
# le mur, a conclu « réseau bloqué » et n'a jamais essayé ssh.
CODE_UNSANDBOXED = ["git push *", "git pull *", "git fetch *", "git clone *", "ssh *", "scp *",
                    "sftp *", "rsync *", "ping *", "nc *"]


def ha_host():
    """Hôte Home Assistant, pour l'autoriser au réseau du bac à sable. Jamais le jeton."""
    try:
        from urllib.parse import urlparse
        url = json.loads((HOME / ".config/omarchy-companion/ha.json").read_text()).get("url", "")
        return urlparse(url).hostname or ""
    except (OSError, ValueError):
        return ""


def build_settings(mode, home, private=(), mail=False, role=None, erp=False, portail=False, delegate=False, robot=False):
    """Réglages complets passés à Claude Code : permissions, garde et bac à sable. `private` =
    emplacements privés de l'utilisateur (réglage `privatePaths`), fermés en mode Assistant.

    `role` = le rôle actif (roles.load), qui ne peut que RETIRER : fermer un accès et ajouter des
    mots interdits au garde. Le mode lui a déjà été rabattu par roles.mode_for, donc rien ici ne
    peut remonter l'échelle."""
    base = {"chat": CHAT_SETTINGS, "read": READ_SETTINGS, "code": CODE_SETTINGS,
            "auto": AUTO_SETTINGS}.get(mode, ASSISTANT_SETTINGS)
    # Le coffre et les emplacements privés ne s'ouvrent qu'en mode Code : là, chaque lecture passe
    # par une carte. En Autonome il n'y a pas de carte, donc ils restent fermés.
    reads = SECRET_READS + ([] if mode == "code" else SECRET_READS_ASSISTANT + [f"{p.rstrip('/')}/**" for p in private])
    permissions = dict(base["permissions"])
    permissions["deny"] = list(permissions.get("deny", [])) + [f"Read({path})" for path in reads]
    sandbox = {
        "enabled": True,
        # Bubblewrap absent = Claude Code refuse de démarrer, jamais de repli sans mur.
        "failIfUnavailable": True,
        # Pas d'échappatoire : une commande bloquée ne peut pas être relancée hors du mur.
        "allowUnsandboxedCommands": False,
        # Le bac à sable ne remplace PAS la carte de validation : chaque action reste validée.
        "autoAllowBashIfSandboxed": False,
        "excludedCommands": list(DESKTOP_UNSANDBOXED),
        "network": {"allowedDomains": []},
    }
    if mode in modes.DEV_MODES:
        sandbox["excludedCommands"] += CODE_UNSANDBOXED
        # Le lanceur d'aperçu ouvre une fenêtre : hors du mur, et sans carte en mode Code — sinon
        # l'agent recopie la commande du navigateur à la main (profil semé dans le projet, 19/09).
        permissions["allow"] = list(permissions.get("allow", [])) + [f"Bash({apercu_prefix()}:*)"]
        sandbox["excludedCommands"] += [f"{apercu_prefix()} *"]
    # Les aides pré-autorisées court-circuitent la carte PAR CONSTRUCTION : c'est leur raison
    # d'être. Elles doivent donc suivre l'échelle des modes, sinon « en Lecture elle ne change
    # rien » est faux — en mode maison, `ha.py on script.x` déclenchait n'importe quel script
    # (trouvé à l'audit du 19/09 au soir). Le courrier, lui, ne fait que LIRE : il a sa place en
    # Lecture, pas en Discussion où il n'y a aucun outil.
    if not roles.allows(role, "mail"):
        mail = False
    if not roles.allows(role, "erp"):
        erp = False
    if not roles.allows(role, "home"):
        home = False
    if not roles.allows(role, "portail"):
        portail = False
    if not roles.allows(role, "robot"):
        robot = False
    if mail and mode != "chat":
        # Le lecteur de courrier tourne hors du bac à sable : lui seul ouvre le coffre et parle à
        # l'IMAP. Les EN-TÊTES ne demandent rien (« lis mon dernier mail » ne doit pas coûter une
        # carte à chaque fois) ; ouvrir un message ou chercher dedans en demande toujours une.
        permissions["allow"] = list(permissions.get("allow", [])) + [
            f"Bash({mail_prefix()} liste:*)", f"Bash({mail_prefix()} dossiers:*)",
            f"Bash({mail_prefix()} dossiers)", f"Bash({mail_prefix()} liste)",
            f"Bash({mail_prefix()} tester)"]
        sandbox["excludedCommands"] += [f"{mail_prefix()} *"]
    if erp and mode != "chat":
        # Lecteur Dolibarr : hors bac à sable (lui seul ouvre le coffre et parle à l'ERP), et
        # **entièrement** pré-autorisé — contrairement au courrier, aucun de ses verbes n'écrit,
        # ne valide, n'envoie ni ne supprime : ces verbes n'existent pas dans le fichier. Demander
        # une carte pour lire une liste d'impayés noierait les vraies décisions.
        # Disponible dès le mode LECTURE, comme le courrier : ce qui ne fait que lire n'a pas à
        # attendre le mode Assistant. En Discussion il n'y a aucun outil, donc rien ici non plus.
        permissions["allow"] = list(permissions.get("allow", [])) + [f"Bash({erp_prefix()}:*)"]
        sandbox["excludedCommands"] += [f"{erp_prefix()} *"]
    extension = extensions.portail() if portail else None
    if extension and mode != "chat":
        # Portail : une EXTENSION PRIVÉE (extensions.py), jamais livrée avec le plugin. Hors bac à
        # sable (lui seul ouvre sa session). Les verbes qui LISENT, déclarés par l'extension, sont
        # pré-autorisés dès Lecture ; ceux qui ÉCRIVENT ne le sont pas : une carte chacun, donc
        # refusés d'office en Lecture.
        permissions["allow"] = list(permissions.get("allow", [])) + [
            rule for verb in extension["read_verbs"]
            for rule in (f"Bash({portail_prefix()} {verb}:*)", f"Bash({portail_prefix()} {verb})")]
        sandbox["excludedCommands"] += [f"{portail_prefix()} *"]
    if robot and mode != "chat":
        # Robot (Reachy Mini) : hors bac à sable (la caméra est un appareil), et JAMAIS pré-autorisé :
        # une photo = une carte, comme « regarde mon écran » (une caméra peut montrer un code sur un
        # post-it). Donc refusé d'office en Lecture, où aucune carte n'existe.
        sandbox["excludedCommands"] += [f"{robot_prefix()} *"]
        if mode in ACT_MODES:
            # Les GESTES (lot 4, 09/10) : bouger la tête ne touche à rien d'autre —
            # pré-autorisés à partir du mode Assistant, comme la maison. Regarder reste par carte.
            permissions["allow"] = list(permissions.get("allow", [])) + [
                rule for verb in ("gestes", "emotion", "danse")
                for rule in (f"Bash({robot_prefix()} {verb}:*)", f"Bash({robot_prefix()} {verb})")]
    if delegate and mode != "chat":
        # Un rôle en appelle un autre : `delegue.py <rôle> "<question>"`, hors bac à sable (il lance
        # le cerveau une fois, avec le garde du rôle appelé intersecté). Pré-autorisé : la
        # délégation est en LECTURE au plus, rien ne peut en sortir qu'une réponse.
        permissions["allow"] = list(permissions.get("allow", [])) + [f"Bash({delegue_prefix()}:*)"]
        sandbox["excludedCommands"] += [f"{delegue_prefix()} *"]
    if home and mode in ACT_MODES:
        # Le helper HA est pré-autorisé (actions maison directes, sans carte) et tourne hors
        # bac à sable parce qu'il est seul à lire le jeton. L'agent, lui, ne peut pas le lire.
        # Allumer une lumière est une action : pas en mode fermé.
        permissions["allow"] = list(permissions.get("allow", [])) + [f"Bash({ha_prefix()}:*)"]
        sandbox["excludedCommands"] += [f"{ha_prefix()} *"]
        if ha_host():
            sandbox["network"]["allowedDomains"].append(ha_host())
    # Un accès que le rôle ferme doit être REFUSÉ, pas seulement retiré des pré-autorisations :
    # sinon `ha.py on light.salon` repassait par une simple carte et « ce rôle ne touche pas à la
    # maison » redevenait une façon de parler. On réutilise la liste d'interdits du garde.
    forbid = list(role.get("forbid", ())) if role else []
    if role is not None:
        forbid += [name for name, key in (("ha.py", "home"), ("mail.py", "mail"),
                                         ("dolibarr.py", "erp"), ("portail.py", "portail"),
                                         ("reachy.py", "robot"))
                   if not roles.allows(role, key)]
    forbid = tuple(dict.fromkeys(forbid))
    return dict(base, permissions=permissions, sandbox=sandbox, hooks=guard_hook(mode, private, forbid))


def ha_prefix():
    """Préfixe de commande du helper HA, à pré-autoriser et à donner au prompt."""
    return f"python3 {PLUGIN_DIR / 'ha.py'}"


def mail_prefix():
    """Préfixe du lecteur de courrier, donné au prompt et pré-autorisé pour les seuls en-têtes."""
    return f"python3 {PLUGIN_DIR / 'mail.py'}"


def erp_prefix():
    """Préfixe du lecteur Dolibarr, donné au prompt et pré-autorisé là où elle peut agir."""
    return f"python3 {PLUGIN_DIR / 'dolibarr.py'}"


def robot_prefix():
    """Préfixe du robot (reachy.py), donné au prompt ; aucun de ses verbes n'est pré-autorisé."""
    return f"python3 {PLUGIN_DIR / 'reachy.py'}"


def portail_prefix():
    """Préfixe de l'extension « portail », donné au prompt ; seuls ses verbes de lecture sont pré-autorisés."""
    return f"python3 {extensions.DIR / 'portail.py'}"


def delegue_prefix():
    """Préfixe de la délégation entre rôles, pré-autorisé dès Lecture quand un autre rôle existe."""
    return f"python3 {PLUGIN_DIR / 'delegue.py'}"


def apercu_prefix():
    """Préfixe du lanceur d'aperçu, pré-autorisé en mode Code et donné au prompt."""
    return f"python3 {PLUGIN_DIR / 'apercu.py'}"


# Ce que le cerveau hérite de l'environnement du moteur : tout, SAUF ce qui ressemble à un secret. Les
# variables d'authentification du cerveau lui-même restent (sans elles, il ne démarre pas). Revue Codex
# du 18/10 : « aucun secret dans l'environnement » n'était pas garanti, un jeton exporté dans le shell passait.
SECRET_ENV = re.compile(r"(TOKEN|SECRET|PASSW|API_?KEY|PRIVATE_?KEY|CREDENTIAL|_AUTH\b|COOKIE|SESSION_?KEY)", re.IGNORECASE)
BRAIN_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY")


def brain_env():
    """L'environnement donné au cerveau : celui du moteur, sans les secrets qui ne sont pas les siens."""
    return {key: value for key, value in os.environ.items()
            if key in BRAIN_ENV or not SECRET_ENV.search(key)}


def default_agent():
    """L'agent choisi dans Omarchy, ou une chaîne vide si aucun."""
    try:
        result = subprocess.run(["omarchy-default-agent"], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


# Niveau de prise en charge d'un cerveau, affiché dans les Réglages et l'assistant de première installation.
# Un niveau n'est accordé qu'après PREUVE (contrat des adaptateurs : mécanisme documenté + isolation +
# sonde adverse reproductible), pour une version donnée. Aujourd'hui : Claude Code complet ; Codex en
# cours de certification (son adaptateur ne relaie pas encore les cartes) ; les autres pas encore.
LEVELS = {"claude": "complete", "codex": "certifying"}
# Versions pour lesquelles le niveau « complet » a été PROUVÉ (tests/check_harness.py + sondes) : préfixe
# de `<agent> --version`. Une autre version retombe à « à revérifier » jusqu'à une nouvelle preuve.
CERTIFIED = {"claude": ("2.1.",)}


def support_level(agent):
    """"complete", "certifying", "uncertified" (agent connu d'Omarchy, pas encore pris en charge),
    "missing" (choisi mais introuvable) ou "none" (aucun agent choisi dans Omarchy)."""
    if not agent:
        return "none"
    command = {"claude": "claude", "codex": "codex"}.get(agent, agent)
    if shutil.which(command) is None:
        return "missing"
    level = LEVELS.get(agent, "uncertified")
    if level == "complete" and not agent_version(command).startswith(CERTIFIED.get(agent, ("\0",))):
        return "recheck"
    return level


_VERSIONS = {}


def agent_version(command):
    """`<commande> --version`, premier mot ; "" si illisible. Gardé 10 min : chaque état envoyé au
    panneau en a besoin, et la commande peut prendre plusieurs secondes."""
    cached = _VERSIONS.get(command)
    if cached and time.monotonic() - cached[0] < 600:
        return cached[1]
    version = _read_version(command)
    _VERSIONS[command] = (time.monotonic(), version)
    return version


def _read_version(command):
    try:
        out = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    words = out.strip().split()
    return next((w for w in words if w[:1].isdigit()), "")


def describe(agent, lang="fr"):
    if not agent:
        return texts.t(lang, "agent.none")
    if agent not in ADAPTERS:
        return texts.t(lang, "agent.unsupported", name=NAMES.get(agent, agent))
    if agent == "codex":
        # Mesuré le 12/09/2026 sur codex-cli 0.154.0 : le bac à sable « read-only » laisse
        # lire tout le disque, les hooks avant-outil ne se déclenchent pas dans `codex exec`,
        # et les profils de permissions n'accordent des droits que, ils n'en retirent jamais.
        return texts.t(lang, "agent.codex")
    return None


def unsafe(agent):
    """Vrai quand la lecture de l'agent n'est pas filtrable (le panneau l'affiche en alerte)."""
    return agent == "codex"


def harness(agent, mode, lang="fr"):
    """Une phrase, affichée dans le panneau : quel garde s'applique réellement, là, maintenant."""
    if agent == "claude":
        return texts.t(lang, {"chat": "harness.claude_chat", "read": "harness.claude_read",
                              "code": "harness.claude_code", "auto": "harness.claude_auto"}.get(mode, "harness.claude_assistant"))
    if agent == "codex":
        return texts.t(lang, "harness.codex")
    return texts.t(lang, "harness.unsupported", name=NAMES.get(agent, agent or texts.t(lang, "harness.no_agent")))


def workdir():
    """Dossier de travail : ~/Work si présent (comme omarchy-agent), sinon le home."""
    return HOME / "Work" if (HOME / "Work").is_dir() else HOME


def summarize_tool(name, tool_input, lang="fr"):
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command", ""))
        if "delegue.py" in command:
            # Le fil dit À QUI et QUOI, pas une ligne de commande : « délégation → Compta : … ».
            try:
                words = shlex.split(command)
                index = next(i for i, w in enumerate(words) if w.endswith("delegue.py"))
                return texts.t(lang, "tool.delegation", role=words[index + 1] if len(words) > index + 1 else "?",
                               question=" ".join(words[index + 2:])[:160])
            except (ValueError, StopIteration):
                pass
        for key in ("command", "file_path", "pattern", "path", "query"):
            if key in tool_input:
                return f"{name}: {str(tool_input[key])[:200]}"
    return name


class ClaudeSession:
    """Un processus Claude Code gardé vivant entre les questions (entrée et sortie en flux JSON).

    Le contexte (CLAUDE.md, skills, mémoire) n'est chargé qu'une fois : chaque tour
    suivant ne coûte que la question. Si le processus meurt, il est relancé avec
    `--resume` sur le même identifiant de session pour garder la conversation.
    """

    def __init__(self, system_prompt, model, session_id=None, journal=lambda *_: None, mode="assistant", home=False, lang="fr", private=(), mail=False, role=None, erp=False, portail=False, delegate=False, robot=False):
        self.erp = bool(erp)
        self.portail = bool(portail)
        self.robot = bool(robot)
        self.delegate = bool(delegate)
        self.role = role
        self.system_prompt = system_prompt
        self.model = model
        self.mode = mode
        self.home = home
        self.lang = lang
        self.private = tuple(private)
        self.mail = bool(mail)
        self.session_id = session_id
        self.journal = journal
        self.process = None
        self.lines = None
        self.lock = threading.Lock()
        self.files = []                # consigne et réglages du processus en cours (fichiers 600)

    def forget_files(self):
        for path in self.files:
            try:
                os.unlink(path)
            except OSError:
                pass
        self.files = []

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self, resume):
        # Mode « default » + demandes de permission relayées à l'hôte (le panneau).
        # Les outils pré-autorisés ne demandent rien ; tout le reste passe par la carte.
        settings = build_settings(self.mode, self.home, self.private, self.mail, self.role, self.erp, self.portail, self.delegate,
                                  self.robot)
        self.forget_files()
        self.files = [private_file(json.dumps(settings), ".json"), private_file(self.system_prompt, ".txt")]
        argv = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--permission-mode", "default", "--permission-prompt-tool", "stdio",
                "--settings", self.files[0], "--append-system-prompt-file", self.files[1], "--max-turns", "20"]
        if self.mode == "code":
            # Session de dev complète : réglages user/projet/local, MCP, skills, agents, mémoire.
            argv += ["--setting-sources", "user,project,local"]
        else:
            argv += ["--setting-sources", "project", "--strict-mcp-config", "--add-dir", str(HOME)]
        if self.model:
            argv += ["--model", self.model]
        if resume and self.session_id:
            argv += ["--resume", self.session_id]
        else:
            self.session_id = str(uuid.uuid4())
            argv += ["--session-id", self.session_id]
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, cwd=workdir(), env=brain_env())
        self.lines = queue.Queue()
        process, lines = self.process, self.lines

        # Le fil garde SA file et SON processus : après un redémarrage, la fin de flux de l'ancien
        # ne doit pas tomber dans la conversation suivante (audit du 18/10).
        def pump():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)
        threading.Thread(target=pump, daemon=True).start()
        # Poignée de main de l'hôte, comme le SDK : Claude Code sait alors à qui adresser
        # ses demandes de permission. En mode Assistant, `skills: []` coupe aussi les skills
        # intégrées de Claude Code (revue de code, run, init…) : elles sont orientées
        # développement et n'ont rien à faire dans un assistant de bureau. Le mode Code les garde.
        request = {"subtype": "initialize"}
        if self.mode != "code":
            request["skills"] = []
        elif self.role is not None and self.role.get("skills") is not None:
            # Liste blanche du rôle. Elle ne s'applique QU'ICI, en mode Code, parce que c'est le
            # seul mode où les skills sont chargées : un rôle restreint ce que le mode donne déjà,
            # il ne donne jamais une skill à un mode qui les refuse.
            request["skills"] = list(self.role["skills"])
        self.write({"type": "control_request", "request_id": "companion-init", "request": request})

    def write(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def answer_permission(self, request_id, decision, tool_input):
        """Réponse à une demande de permission : allow (avec l'entrée inchangée) ou deny (avec motif)."""
        if decision.get("behavior") == "allow":
            body = {"behavior": "allow", "updatedInput": tool_input}
        else:
            body = {"behavior": "deny", "message": decision.get("message", "Refusé par l'utilisateur.")}
        self.write({"type": "control_response",
                    "response": {"subtype": "success", "request_id": request_id, "response": body}})

    def close(self):
        if self.process is not None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            if self.process.stdout is not None:
                self.process.stdout.close()
            self.process = None
        self.forget_files()

    def ask(self, question, on_partial, on_permission=None, timeout=180):
        """Pose la question. `on_permission(request)` est appelé pour chaque demande de
        permission et doit rendre {"behavior": "allow"|"deny", "message": ...} ; sans
        gestionnaire, tout est refusé. Le temps d'attente d'une validation ne compte
        pas dans le délai de réponse."""
        with self.lock:
            if not self.alive():
                resumed = self.session_id is not None
                self.start(resume=resumed)
                if resumed:
                    self.journal(texts.t(self.lang, "journal.claude_resumed"))
            try:
                self.write({"type": "user", "message": {"role": "user", "content": question}})
            except (OSError, ValueError):
                self.close()
                raise RuntimeError(texts.t(self.lang, "err.claude_dead"))
            deadline = time.monotonic() + timeout
            reply, error = None, ""
            while True:
                try:
                    line = self.lines.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    self.close()
                    raise RuntimeError(texts.t(self.lang, "err.claude_timeout"))
                if line is None:
                    self.close()
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "control_request":
                    request = event.get("request", {})
                    if request.get("subtype") == "can_use_tool":
                        waited = time.monotonic()
                        decision = {"behavior": "deny", "message": "Aucun gestionnaire de validation."}
                        if on_permission:
                            # Un gestionnaire qui plante laisserait Claude Code attendre sa réponse pour
                            # toujours : la question suivante bloquerait 180 s. On refuse et on continue.
                            try:
                                decision = on_permission(request) or decision
                            except Exception as problem:
                                self.journal(texts.t(self.lang, "journal.validation_failed", error=str(problem)[:160]), "securite", "alerte")
                                decision = {"behavior": "deny", "message": "Validation impossible : " + str(problem)[:200]}
                        deadline += time.monotonic() - waited
                        try:
                            self.answer_permission(event.get("request_id"), decision, request.get("input", {}))
                        except (OSError, ValueError):
                            self.close()
                            raise RuntimeError(texts.t(self.lang, "err.claude_dead"))
                elif kind == "system" and event.get("subtype") == "permission_denied":
                    self.journal(texts.t(self.lang, "journal.native_deny", message=str(event.get("message", ""))[:160]), "securite", "alerte")
                elif kind == "stream_event":
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {}).get("text", "")
                        if delta:
                            try:
                                on_partial(delta)
                            except Exception as problem:   # l'affichage progressif n'arrête pas la réponse
                                self.journal(texts.t(self.lang, "journal.stream_ignored", error=str(problem)[:160]))
                elif kind == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            self.journal(summarize_tool(block.get("name", "?"), block.get("input"), self.lang), "tool")
                elif kind == "result":
                    if event.get("is_error") or event.get("subtype") not in (None, "success"):
                        error = str(event.get("result") or event.get("subtype") or "erreur")
                    else:
                        reply = event.get("result", "")
                    break
            if reply is None:
                raise RuntimeError(texts.t(self.lang, "err.claude_no_reply") + error[:300])
            return reply


_claude = None


def reset():
    """Nouvelle conversation : on ferme le processus persistant."""
    global _claude
    if _claude is not None:
        _claude.close()
        _claude = None


def prompt_stamp(system_prompt):
    return hashlib.sha256(system_prompt.encode()).hexdigest()[:12]


def run_claude(system_prompt, history, question, model, session, on_partial, journal, on_permission=None, mode="assistant", home=False, lang="fr", private=(), memory="", mail=False, role=None, erp=False, portail=False, delegate=False, robot=False):
    global _claude
    # L'empreinte ignore la mémoire : un souvenir pris en cours de route relance le processus
    # (nouvelle consigne) sur la MÊME session, la conversation continue.
    # Hermes fige au contraire son carnet pour toute la session, pour garder le cache de préfixe du
    # modèle — parce qu'il écrit à chaque tour. Ici les écritures sont rares (une phrase « retiens
    # que… », ou la promotion nocturne du rêve) : on préfère qu'un souvenir serve tout de suite.
    stamp = prompt_stamp(system_prompt + "|" + mode + "|" + str(home) + "|" + (role or {}).get("name", ""))
    system_prompt = system_prompt + memory
    session_id = session.get("id") if session.get("agent") == "claude" else None
    if session_id and session.get("prompt") != stamp:
        # Consigne, mode ou mode HA modifiés : ne pas reprendre une conversation dont le
        # contexte contredit les nouvelles règles ; on ouvre une session propre.
        journal(texts.t(lang, "journal.context_changed"))
        session_id = None
    if (_claude is None or _claude.system_prompt != system_prompt or _claude.model != model
            or _claude.mode != mode or _claude.home != home or _claude.private != tuple(private)
            or _claude.mail != bool(mail) or _claude.erp != bool(erp) or _claude.portail != bool(portail) \
            or _claude.robot != bool(robot)
            or _claude.delegate != bool(delegate)
            or (_claude.role or {}).get("name", "") != (role or {}).get("name", "")):
        reset()
        _claude = ClaudeSession(system_prompt, model, session_id or None, journal, mode, home, lang, private, mail, role, erp, portail, delegate,
                                robot)
    _claude.journal = journal
    _claude.lang = lang
    reply = _claude.ask(question, on_partial, on_permission)
    return reply, {"agent": "claude", "id": _claude.session_id, "prompt": stamp}


def ask_once(question, model="", timeout=180):
    """Une question, une réponse, sans outil, sans session, sans mémoire.

    Sert aux travaux internes du moteur (le rêve). Tous les outils sont refusés : le processus ne
    peut ni lire, ni écrire, ni exécuter quoi que ce soit — il ne voit que le texte qu'on lui donne.
    Retourne "" si l'agent n'est pas disponible ou dépasse le délai.
    """
    argv = ["claude", "-p", "--output-format", "text", "--max-turns", "1",
            "--allowed-tools", "", "--disallowed-tools",
            "Bash,Read,Write,Edit,NotebookEdit,Glob,Grep,WebFetch,WebSearch,Task,TodoWrite"]
    if model:
        argv += ["--model", model]
    try:
        done = subprocess.run(argv, input=question, capture_output=True, text=True, timeout=timeout,
                              cwd=workdir(), env=brain_env())
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def describe_request(request, lang="fr"):
    """Texte de la carte de validation : l'action exacte, lisible d'un coup d'œil."""
    tool = request.get("tool_name", "?")
    tool_input = request.get("input", {}) or {}
    if tool == "Bash":
        text = str(tool_input.get("command", ""))
        title = str(tool_input.get("description", "")) or texts.t(lang, "card.command")
        return f"{title}\n$ {text}"
    if tool in ("Edit", "MultiEdit"):
        path = tool_input.get("file_path", "?")
        old = str(tool_input.get("old_string", ""))[:300]
        new = str(tool_input.get("new_string", ""))[:300]
        return texts.t(lang, "card.edit", path=path) + f"\n— {old}\n+ {new}"
    if tool == "WebFetch":
        # L'adresse ENTIÈRE, requête comprise : c'est là qu'une fuite se cacherait.
        url = str(tool_input.get("url", "?"))
        question = str(tool_input.get("prompt", "")).strip()
        return texts.t(lang, "card.page") + f"\n{url}" + ("\n" + texts.t(lang, "card.question") + question[:300] if question else "")
    if tool == "SandboxNetworkAccess":
        # Carte émise par le bac à sable, pas par l'agent : premier accès à un hôte réseau.
        return texts.t(lang, "card.network", host=tool_input.get("host", "?"))
    if tool == "Write":
        content = str(tool_input.get("content", ""))
        return texts.t(lang, "card.write", path=tool_input.get("file_path", "?"), lines=len(content.splitlines())) + f"\n{content[:400]}"
    return f"{tool}\n{json.dumps(tool_input, ensure_ascii=False)[:400]}"


def run_codex(system_prompt, history, question, model, session, on_partial, journal, on_permission=None, mode="assistant", home=False, lang="fr", private=(), memory="", mail=False, role=None, erp=False, portail=False, delegate=False, robot=False):
    system_prompt = system_prompt + memory
    # Codex exec n'a pas de demande d'approbation en mode commande : il reste en lecture seule.
    # Cette lecture seule n'est PAS filtrable (vérifié sur 0.154.0), donc le mode Code, qui
    # suppose un garde, ne peut pas être honnête ici : on le refuse plutôt que de faire semblant.
    if mode == "code":
        raise RuntimeError(texts.t(lang, "err.codex_code"))
    messages = [{"role": "system", "content": system_prompt}] + history[-30:] + [{"role": "user", "content": question}]
    with tempfile.TemporaryDirectory(prefix="companion-") as directory:
        output = Path(directory) / "reply.txt"
        argv = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--json",
                "-C", directory, "--color", "never", "-o", str(output)]
        if model:
            argv += ["-m", model]
        result = subprocess.run(argv + ["-"], input=json.dumps(messages, ensure_ascii=False),
                                capture_output=True, text=True, timeout=180, env=brain_env())
        previous = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item") if isinstance(event.get("item"), dict) else event
            command = item.get("command") or item.get("cmd")
            if command and command != previous:  # started + completed = même commande
                journal("commande: " + str(command)[:200], "tool")
                previous = command
        if result.returncode or not output.exists():
            raise RuntimeError(texts.t(lang, "err.codex_no_reply"))
        return output.read_text().strip(), {"agent": "codex", "id": ""}


ADAPTERS = {"claude": run_claude, "codex": run_codex}


def run(agent, system_prompt, history, question, model, session, on_partial, journal, on_permission=None, mode="assistant", home=False, lang="fr", private=(), memory="", mail=False, role=None, erp=False, portail=False, delegate=False, robot=False):
    """Pose la question à l'agent Omarchy courant. Retourne (réponse, état de session)."""
    problem = describe(agent, lang)
    if problem:
        raise RuntimeError(problem)
    started = time.monotonic()
    # L'étiquette du journal dit ce qui s'applique VRAIMENT : les trois accès tels que le moteur les
    # a calculés (un rôle qui ferme la maison la ferme aussi ici), puis le rôle. Le 20/09 au soir,
    # « assistant+HA+compta » était écrit alors que le rôle avait coupé Home Assistant, et le
    # courrier comme la comptabilité n'y figuraient jamais — c'est la trace qu'on relit pour
    # comprendre une conversation passée.
    label = mode + "".join(f"+{key}" for key, on in (("home", home), ("mail", mail), ("erp", erp), ("portail", portail),
                                                             ("robot", robot)) if on) \
        + (f"+{role['name']}" if role else "")
    journal(texts.t(lang, "journal.request", agent=NAMES.get(agent, agent), mode=label, text=question[:110]),
            "echange", "message")
    try:
        reply, state = ADAPTERS[agent](system_prompt, history, question, model, session, on_partial, journal, on_permission, mode, home, lang, private, memory, mail, role, erp, portail, delegate,
                                       robot)
    except Exception as error:
        journal(texts.t(lang, "journal.failure", seconds=f"{time.monotonic() - started:.1f}", error=str(error)[:200]), "echange", "alerte")
        raise
    journal(texts.t(lang, "journal.reply", seconds=f"{time.monotonic() - started:.1f}", chars=len(reply)), "echange", "message")
    return reply, state
