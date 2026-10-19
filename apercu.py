"""Fenêtre d'aperçu d'Alison : une page ou un fichier, à côté du panneau.

Un seul endroit qui sait l'ouvrir — le moteur l'appelle, et l'agent aussi (commande pré-autorisée
en mode Code). Sinon l'agent recopie la commande à la main et sème un profil de navigateur de
120 Mo dans le dossier du projet, comme le 19/09.

  python3 apercu.py <url|fichier>     ouvre (remplace la fenêtre précédente)
  python3 apercu.py --close           ferme

Chaque ouverture utilise un profil neuf en 700, effacé après sortie du navigateur ou fermeture.
Firefox et Chromium sont lancés directement, sans repli vers un profil personnel.
"""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile

import storage

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


def cleanup_profile(path):
    """Ne peut effacer qu'un profil temporaire créé par ce module, jamais un chemin libre."""
    path = Path(path)
    if (path.parent.resolve() == PROFILE.parent.resolve()
            and path.name.startswith(PROFILE.name + "-") and not path.is_symlink()):
        shutil.rmtree(path, ignore_errors=True)


def process_start(pid):
    try:
        # Le champ 22 distingue un processus d'un PID réutilisé après sa sortie.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return ""


def wait_exit(pid, timeout=None):
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return True
    try:
        return bool(select.select([fd], [], [], timeout)[0])
    finally:
        os.close(fd)


def watch_cleanup(process, profile):
    """Un veilleur indépendant survit au CLI et nettoie aussi après fermeture à la souris."""
    try:
        fd = os.pidfd_open(process.pid)
    except ProcessLookupError:
        cleanup_profile(profile)
        return
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--cleanup", str(profile), str(fd)],
                         pass_fds=(fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    finally:
        os.close(fd)


def close():
    """Ferme l'instance identifiée et efface son profil après sortie, pas celui d'un autre PID."""
    try:
        data = json.loads(PID_FILE.read_text())
        pid = int(data["pid"])
        profile = Path(data["profile"])
        if pid <= 1:
            return False
    except (OSError, ValueError, TypeError, KeyError):
        return False
    try:
        if data.get("start") == process_start(pid):
            os.kill(pid, 15)
            exited = wait_exit(pid, 5)
        else:
            exited = True
        if exited:
            cleanup_profile(profile)
    except OSError:
        pass                  # le veilleur garde le pidfd jusqu'à la sortie réelle
    PID_FILE.unlink(missing_ok=True)
    return True


def open_window(url):
    """Un profil neuf à chaque ouverture ; aucun repli vers le navigateur personnel."""
    address = target(url)
    if not address:
        return None
    close()
    browser = default_browser()
    if browser.startswith("firefox"):
        executable = "firefox"
    elif browser.startswith(("chromium", "google-chrome", "brave")):
        executable = next((name for name in ("chromium", "google-chrome", "brave") if shutil.which(name)), "")
    else:
        return None
    if not executable:
        return None
    storage.private_dir(PROFILE.parent)
    profile = Path(tempfile.mkdtemp(prefix=PROFILE.name + "-", dir=PROFILE.parent))
    environment = dict(os.environ, MOZ_APP_REMOTINGNAME=WINDOW_CLASS)
    if executable == "firefox":
        argv = [executable, "--no-remote", "--profile", str(profile), "--new-window", address]
    else:
        argv = [executable, "--user-data-dir=" + str(profile), "--no-first-run", "--app=" + address]
    process = None
    try:
        process = subprocess.Popen(argv, env=environment, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        storage.private_write(PID_FILE, json.dumps({"pid": process.pid, "profile": str(profile),
                                                    "start": process_start(process.pid)}))
        watch_cleanup(process, profile)
    except OSError:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        cleanup_profile(profile)
        PID_FILE.unlink(missing_ok=True)
        return None
    return process


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--cleanup":
        # Le descripteur hérité désigne le navigateur précis, même si son PID est réutilisé.
        select.select([int(sys.argv[3])], [], [])
        cleanup_profile(sys.argv[2])
        sys.exit(0)
    argument = sys.argv[1] if len(sys.argv) > 1 else ""
    if argument in ("--close", "-c", "close"):
        print("aperçu fermé" if close() else "aucun aperçu ouvert")
        sys.exit(0)
    if not target(argument):
        print("usage : apercu.py <url http(s) ou fichier existant> | --close", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if open_window(argument) else 1)
