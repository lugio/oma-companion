"""Outil de développement : installe la copie de travail comme plugin utilisateur d'Omarchy.

Un utilisateur installe Alison par `omarchy plugin add <dépôt git> --enable` (voir README) ; ce
script sert à essayer les sources locales sans dépôt. Il ne passe que par les commandes publiques
d'Omarchy (`omarchy plugin validate|enable`, `omarchy-shell shell rescanPlugins`) : il n'écrit
jamais shell.json ni les raccourcis Hyprland.
"""
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import time

SOURCE = Path(__file__).resolve().parent
MANIFEST = json.loads((SOURCE / "manifest.json").read_text())
PLUGIN_ID = MANIFEST["id"]
DEST = Path.home() / ".config/omarchy/plugins" / PLUGIN_ID
BINDING = f'o.bind("SUPER + ALT + L", "Alison", "omarchy-shell shell toggle {PLUGIN_ID} \'{{}}\'")'
# Fichiers du plugin : ce que le shell charge et ce que le moteur lance. Ni tests, ni docs, ni outils.
RUNTIME = ["manifest.json", "LICENSE", "download_models.py", "reachy_page.html",   # la page du robot (11/10)
           "roles-exemples.json"]                                                # rôles d'exemple (18/10)
TOOLS = {"install.py", "uninstall.py"}


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def runtime_files():
    files = [SOURCE / name for name in RUNTIME]
    files += sorted(path for path in SOURCE.glob("*.qml"))
    files += sorted(path for path in SOURCE.glob("*.js"))   # formatage des textes du panneau (I18n.js)
    files += sorted(path for path in SOURCE.glob("*.py") if path.name not in TOOLS and path.name not in RUNTIME)
    return files


def sync_plugin_files():
    """Copie les fichiers du plugin et retire ceux qui n'existent plus dans la source
    (le dossier `.git` d'une installation par `omarchy plugin add` est laissé en place)."""
    DEST.mkdir(parents=True, exist_ok=True)
    wanted = {path.name for path in runtime_files()}
    for source in runtime_files():
        target = DEST / source.name
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copy2(source, target)
    # Les fichiers de langue, dans leur dossier : une langue = un fichier `lang/<code>.json`.
    (DEST / "lang").mkdir(exist_ok=True)
    languages = sorted((SOURCE / "lang").glob("*.json"))
    for source in languages:
        target = DEST / "lang" / source.name
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copy2(source, target)
    for stale in (DEST / "lang").iterdir():
        if stale.name not in {path.name for path in languages}:
            stale.unlink()
    for stale in DEST.iterdir():
        if stale.name == "__pycache__":
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.is_file() and stale.name not in wanted:
            stale.unlink()


def settle(since, quiet=3.0, limit=20.0):
    """Attend que le shell ait fini de recharger le plugin : « Local plugin changed, reloading »
    ne bouge plus depuis `quiet` secondes.

    🛑 Sans cette attente, `omarchy restart shell` lancé juste après la copie arrive pendant que le
    shell ré-instancie encore des objets QML, et quickshell segfaute au démontage (bug Qt 6.11 au
    démontage, reproduit à l'identique les 20 et 21/09). Le shell se relance seul, mais chaque fois
    c'est un core dump de plus à expliquer."""
    deadline = time.monotonic() + limit
    last_seen = time.monotonic()
    seen = 0
    while time.monotonic() < deadline:
        try:
            out = subprocess.run(["journalctl", "--user", "-t", "omarchy-shell", "--since", f"@{int(since)}",
                                  "-o", "cat", "--no-pager"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return
        count = out.count("Local plugin changed, reloading")
        if count > seen:
            seen, last_seen = count, time.monotonic()
        elif time.monotonic() - last_seen >= quiet:
            return
        time.sleep(0.5)


def enabled(plugin_id):
    plugins = json.loads(run("omarchy", "plugin", "list", "--json").stdout or "[]")
    return any(p.get("id") == plugin_id and p.get("enabled") for p in plugins)


if __name__ == "__main__":
    run("omarchy", "plugin", "validate", str(SOURCE))
    if DEST.exists():
        backup = Path.home() / ".local/state/omarchy-companion/backups" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for folder in (backup.parent, backup.parent.parent):   # `mode=` ne vaut que pour la feuille
            folder.chmod(0o700)
        shutil.copytree(DEST, backup, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    started = time.time()
    sync_plugin_files()
    run("omarchy-shell", "shell", "rescanPlugins")
    if not enabled(PLUGIN_ID):
        run("omarchy", "plugin", "enable", PLUGIN_ID, "--section", MANIFEST.get("barWidget", {}).get("defaultSection", "right"))
    settle(started)
    print(f"Alison installée ({PLUGIN_ID}), rechargement du shell terminé. Après une modification : omarchy restart shell")
    bindings = Path.home() / ".config/hypr/bindings.lua"
    if not bindings.exists() or PLUGIN_ID not in bindings.read_text():
        print("Raccourci clavier (à ajouter toi-même dans ~/.config/hypr/bindings.lua) :\n  " + BINDING)
