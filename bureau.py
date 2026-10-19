"""Le bureau d'Alison : les gestes qu'elle fait ELLE-MÊME, sans réveiller l'agent.

Un aller-retour vers l'agent coûte cinq secondes ; poser un rappel en coûte moins d'une. Tout passe
par les commandes livrées avec Omarchy (`omarchy reminder`, `omarchy menu…`, `omarchy share`,
`omarchy capture…`) et par Hyprland en Lua — jamais par un chemin parallèle qui casserait à la
prochaine mise à jour de l'OS.

Les motifs de phrases vivent dans `texts.py` (une langue = une liste) ; ici, l'exécution.
"""
import datetime
import json
import os
import re
import subprocess
from pathlib import Path

import memory
import storage
import texts

TIMEOUT = 20                 # une commande du bureau répond tout de suite, ou pas du tout
MAX_DELAY = 7 * 24 * 60      # un rappel au-delà d'une semaine est une erreur de transcription
MESSAGE_MAX = 200            # ce qu'on garde du texte d'un rappel
NOTE_MAX = 600               # une ligne de note, comme les notes du jour
REMINDERS_SPOKEN = 5         # au-delà, on donne le compte plutôt que la liste


def _number(word, lang):
    """Un nombre écrit en chiffres ou en lettres (« dans une heure » n'arrive jamais en « 1 »)."""
    word = str(word).strip().casefold()
    if word.isdigit():
        return int(word)
    return texts.DESK_NUMBERS[texts.base(lang)].get(word)


def when(rest, lang="fr", now=None):
    """(minutes, texte) pour « dans 20 minutes de sortir le gâteau ». (None, texte) sans délai."""
    now = now or datetime.datetime.now()
    for pattern, kind in texts.DESK_DELAY[texts.base(lang)]:
        found = re.search(pattern, rest, re.IGNORECASE)
        if not found:
            continue
        minutes = None
        if kind == "hm":
            minutes = int(found[1]) * 60 + int(found[2])
        elif kind in ("m", "h"):
            count = _number(found[1], lang)
            minutes = count * (60 if kind == "h" else 1) if count is not None else None
        elif kind == "at":
            hour, minute = int(found[1]), int(found[2] or 0)
            half = found[3] if found.re.groups >= 3 else None   # am/pm, en anglais seulement
            if half and half.casefold() == "pm" and hour < 12:
                hour += 12
            if half and half.casefold() == "am" and hour == 12:
                hour = 0
            if hour > 23 or minute > 59:
                continue
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)   # « à 8h » dit le soir, c'est demain matin
            minutes = round((target - now).total_seconds() / 60)
        if not minutes or minutes < 1 or minutes > MAX_DELAY:
            continue
        message = (rest[:found.start()] + " " + rest[found.end():]).strip()
        message = re.sub(texts.DESK_STRIP[texts.base(lang)], "", message, flags=re.IGNORECASE)
        return minutes, " ".join(message.split())[:MESSAGE_MAX]
    return None, rest


def _run(argv):
    """Une commande d'Omarchy. Retourne (succès, sortie) ; une commande absente n'explose pas."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
        return result.returncode == 0, (result.stdout or result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)[:200]


def reminder(minutes, message, lang="fr"):
    """Pose un rappel. Le texte dicté finit dans une unité systemd et dans une notification à
    l'écran : ce qui ressemble à une valeur secrète y est masqué avant d'y arriver.
    Exception volontaire : le CLI Omarchy reçoit ce texte en argument ; ps et l'unité utilisateur
    peuvent donc le montrer. Ce rappel est destiné à être affiché, pas à garder un texte privé."""
    message = storage.redact(message) if message else ""
    ok, _ = _run(["omarchy", "reminder", str(int(minutes))] + ([message] if message else []))
    if not ok:
        return texts.t(lang, "reply.desk_failed")
    at = (datetime.datetime.now() + datetime.timedelta(minutes=minutes)).strftime("%H:%M")
    return texts.t(lang, "reply.reminder_set", at=at, message=message or texts.t(lang, "reply.reminder_nothing"))


def reminders(lang="fr"):
    ok, out = _run(["omarchy", "reminder", "show", "--json"])
    try:
        pending = json.loads(out)["reminders"] if ok else []
    except (ValueError, KeyError, TypeError):
        return texts.t(lang, "reply.desk_failed")
    if not pending:
        return texts.t(lang, "reply.reminders_none")
    if len(pending) > REMINDERS_SPOKEN:
        return texts.t(lang, "reply.reminders_many", count=len(pending))
    lines = [texts.t(lang, "reply.reminder_line", at=item.get("atTime", "?"),
                     message=str(item.get("message") or item.get("label") or "").strip()[:MESSAGE_MAX])
             for item in pending]
    return texts.t(lang, "reply.reminders_head", count=len(pending)) + "\n" + "\n".join(lines)


def reminders_clear(lang="fr"):
    ok, out = _run(["omarchy", "reminder", "show", "--json"])
    try:
        count = len(json.loads(out)["reminders"]) if ok else 0
    except (ValueError, KeyError, TypeError):
        count = 0
    if not count:
        return texts.t(lang, "reply.reminders_none")
    _run(["omarchy", "reminder", "clear"])
    return texts.t(lang, "reply.reminders_cleared", count=count)


def menu(which, lang="fr"):
    """Presse-papier et émojis : les menus du shell, ouverts sans attendre qu'ils se referment."""
    argv = {"clipboard": ["omarchy", "menu", "clipboard"], "emoji": ["omarchy", "menu", "emoji"]}[which]
    try:
        subprocess.Popen(argv, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return texts.t(lang, "reply.desk_failed")
    return texts.t(lang, "reply.menu_" + which)


def share(lang="fr"):
    """Le presse-papier envoyé à un autre appareil (LocalSend). La fenêtre fait le reste."""
    try:
        subprocess.Popen(["omarchy", "share", "clipboard"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return texts.t(lang, "reply.desk_failed")
    return texts.t(lang, "reply.share_started")


def capture(lang="fr"):
    """Capture d'écran : la sélection à la souris bloque tant que tu n'as pas choisi la zone, donc
    on la détache. L'image part dans tes images et dans le presse-papier, comme SUPER+MAJ+S."""
    try:
        subprocess.Popen(["omarchy", "capture", "screenshot"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return texts.t(lang, "reply.desk_failed")
    return texts.t(lang, "reply.capture_started")


def workspace(index, lang="fr"):
    """Aller sur un bureau. Hyprland est configuré en Lua ici : `dispatch workspace 4` est refusé."""
    if not 1 <= int(index) <= 20:
        return texts.t(lang, "reply.desk_failed")
    ok, _ = _run(["hyprctl", "dispatch", 'hl.dsp.focus({ workspace = "%d" })' % int(index)])
    return texts.t(lang, "reply.workspace_done" if ok else "reply.desk_failed", index=int(index))


def vault_note(vault, text, lang="fr", now=None):
    """Une ligne dans la note du jour d'un coffre Obsidian : `AAAA-MM-JJ.md`, à la racine ou dans
    le dossier indiqué. Le fichier est celui d'Obsidian, pas un format à nous : on ajoute une puce
    horodatée à la fin, sans toucher au reste ni créer de modèle."""
    text = " ".join(str(text or "").split())[:NOTE_MAX]
    if not text:
        return texts.t(lang, "reply.note_empty")
    if memory.looks_secret(text):
        return texts.t(lang, "reply.note_secret")
    folder = Path(os.path.expanduser(str(vault or "").strip()))
    if not vault or not folder.is_dir():
        return texts.t(lang, "reply.note_no_vault")
    now = now or datetime.datetime.now()
    target = folder / (now.strftime("%Y-%m-%d") + ".md")
    line = "- %s %s\n" % (now.strftime("%H:%M"), storage.redact(text))
    try:
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        with open(target, "a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(line)
    except OSError:
        return texts.t(lang, "reply.note_failed")
    return texts.t(lang, "reply.note_added", day=now.strftime("%Y-%m-%d"))


def run(command, lang="fr", vault=""):
    """Exécute une commande du bureau et retourne la phrase à dire. `screen` reste au moteur :
    elle a besoin d'une carte et de l'agent."""
    kind = command.get("kind")
    if kind == "reminder":
        minutes, message = when(command.get("rest", ""), lang)
        return reminder(minutes, message, lang) if minutes else texts.t(lang, "reply.reminder_unclear")
    if kind == "reminders":
        return reminders(lang)
    if kind == "reminders_clear":
        return reminders_clear(lang)
    if kind in ("clipboard", "emoji"):
        return menu(kind, lang)
    if kind == "share":
        return share(lang)
    if kind == "capture":
        return capture(lang)
    if kind == "workspace":
        return workspace(command.get("index", 0), lang)
    if kind == "note":
        return vault_note(vault, command.get("rest", ""), lang)
    raise ValueError(kind)
