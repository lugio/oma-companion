"""Fenêtre d'aperçu d'Alison : une page ou un fichier, à côté du panneau.

Un seul endroit qui sait l'ouvrir — le moteur l'appelle, et l'agent aussi (commande pré-autorisée
en mode Code). Sinon l'agent recopie la commande à la main et sème un profil de navigateur de
120 Mo dans le dossier du projet, comme le 19/09.

  python3 apercu.py <url|fichier>     ouvre (remplace la fenêtre précédente)
  python3 apercu.py --close           ferme

Profil **jetable** dans l'état privé : ni session, ni compte, ni historique. Identifiant Wayland
`alison-apercu` (via MOZ_APP_REMOTINGNAME, que Chromium ignore) pour que la règle Hyprland du
README puisse la placer.
"""
import os
from pathlib import Path
import subprocess
import sys

WINDOW_CLASS = "alison-apercu"
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy-companion"
PROFILE = STATE / "apercu-profile"
PID_FILE = STATE / "apercu.pid"


def target(argument):
    """Adresse http(s) ou fichier local existant. Rien d'autre ne s'ouvre."""
    argument = str(argument or "").strip()
    if argument.startswith(("http://", "https://")):
        return argument
    if argument.startswith("file://"):
        argument = argument[7:]
    path = Path(argument).expanduser()
    return "file://" + str(path.resolve()) if path.is_file() else ""


def default_browser():
    try:
        return subprocess.run(["xdg-settings", "get", "default-web-browser"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def close():
    """Ferme la fenêtre ouverte par un appel précédent. Vrai si quelque chose a été fermé."""
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 15)
    except OSError:
        pass
    PID_FILE.unlink(missing_ok=True)
    return True


def open_window(url):
    """Ouvre l'aperçu (en remplaçant le précédent). Retourne le processus, ou None."""
    address = target(url)
    if not address:
        return None
    close()
    PROFILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if default_browser().startswith("firefox"):
        environment = dict(os.environ, MOZ_APP_REMOTINGNAME=WINDOW_CLASS)
        argv = ["firefox", "--profile", str(PROFILE), "--new-window", address]
    else:
        # Sans Firefox : la fenêtre s'ouvre par Omarchy, sans identifiant stable donc sans placement.
        environment, argv = dict(os.environ), ["omarchy", "launch", "webapp", address]
    try:
        process = subprocess.Popen(argv, env=environment, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return None
    try:
        PID_FILE.write_text(str(process.pid))
        PID_FILE.chmod(0o600)
    except OSError:
        pass
    return process


if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else ""
    if argument in ("--close", "-c", "close"):
        print("aperçu fermé" if close() else "aucun aperçu ouvert")
        sys.exit(0)
    if not target(argument):
        print("usage : apercu.py <url http(s) ou fichier existant> | --close", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if open_window(argument) else 1)
