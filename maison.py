"""La maison prévient Alison (lot 8 du corps, chantier « Proactivité ») : quelques capteurs de Home
Assistant, lus par `ha.py` (seul détenteur du jeton), et ce qu'elle fait quand ils changent.

Décisions du 09/10/2026 : la **sonnette** et le **jour Tempo rouge** pour commencer ; le robot
ET la voix réagissent ; **silence de 22 h à 7 h, sauf la sonnette**. La veille ne tourne que si
l'accès Maison est ouvert (la pastille) — aucun réglage de plus.

Ce fichier est PUR : des règles (données, lues dans un fichier privé) et leur jugement. Le moteur lit
les capteurs, appelle `Watch.update`, puis joue l'émotion du robot et dit la phrase. Ajouter un
événement = une règle dans `maison.json` et ses phrases `notice.<nom>.NN` dans les fichiers de langue.
"""
import datetime
import json
import os
from pathlib import Path
import re

QUIET = (22, 7)                    # heures de silence : de 22 h à 7 h

# entity   : le capteur Home Assistant
# when     : l'état qui déclenche (comparé sans casse)
# edge     : True = au PASSAGE à cet état (sonnette) ; False = une fois par jour tant qu'il y est
# every    : secondes entre deux lectures
# cooldown : secondes minimum entre deux réactions
# night    : True = aussi pendant le silence de nuit
# emotion  : l'émotion du robot (bibliothèque de Pollen)
# who      : (facultatif) détections déjà faites par les caméras UniFi Protect, lues tout de suite :
#            la première allumée complète la phrase (« c'est une personne ») — en moins de 2 s
# follow   : (facultatif) un champ texte de Home Assistant à suivre ensuite : la description que
#            fait l'automatisation de Home Assistant (« … » pendant qu'elle se fait), dite dès qu'elle arrive.
#            Une seule description pour toute la maison (option A, 09/10) : Alison ne
#            refait pas le travail.
# Les règles viennent d'un fichier PRIVÉ (`~/.config/omarchy-companion/maison.json`, ou `COMPANION_HOUSE_CONFIG`) :
# les capteurs sont ceux de CHAQUE maison, jamais dans le code (18/10). Sans fichier : aucune règle, la veille dort.
#   {"rules": [{"name": "sonnette", "entity": "binary_sensor.…", "when": "on", "edge": true, "every": 2,
#               "cooldown": 20, "night": true, "emotion": "surprised1",
#               "who": [["person", "binary_sensor.…"]], "follow": {"entity": "input_text.…", "pending": "…", "wait": 40}}]}
CONFIG = Path(os.environ.get("COMPANION_HOUSE_CONFIG",
                             str(Path.home() / ".config/omarchy-companion/maison.json")))
NAME = re.compile(r"[a-z][a-z0-9_]{0,30}")
ENTITY = re.compile(r"[a-z_]+\.[a-z0-9_]+")


def _rule(raw):
    """Une règle validée (types, bornes, entités), ou None : rien n'est deviné."""
    if not isinstance(raw, dict):
        return None
    try:
        rule = {"name": raw["name"], "entity": raw["entity"], "when": str(raw["when"]).strip().lower(),
                "edge": bool(raw.get("edge", False)), "every": int(raw.get("every", 60)),
                "cooldown": int(raw.get("cooldown", 0)), "night": bool(raw.get("night", False)),
                "emotion": str(raw.get("emotion", ""))}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not (isinstance(rule["name"], str) and NAME.fullmatch(rule["name"]) and isinstance(rule["entity"], str)
            and ENTITY.fullmatch(rule["entity"]) and rule["when"] and 1 <= rule["every"] <= 86400
            and 0 <= rule["cooldown"] <= 86400 and (not rule["emotion"] or NAME.fullmatch(rule["emotion"]))):
        return None
    who = raw.get("who") or ()
    if isinstance(who, (list, tuple)):
        rule["who"] = tuple((kind, entity) for kind, entity in (w for w in who if isinstance(w, (list, tuple)) and len(w) == 2)
                            if isinstance(kind, str) and NAME.fullmatch(kind) and isinstance(entity, str)
                            and ENTITY.fullmatch(entity))
    lieu = raw.get("lieu")
    if isinstance(lieu, str) and lieu.strip():
        rule["lieu"] = lieu.strip()[:40]
    elif isinstance(lieu, dict):
        rule["lieu"] = {k: str(v).strip()[:40] for k, v in lieu.items() if k in ("fr", "en") and str(v).strip()}
    follow = raw.get("follow")
    if isinstance(follow, dict) and isinstance(follow.get("entity"), str) and ENTITY.fullmatch(follow["entity"]):
        rule["follow"] = {"entity": follow["entity"], "pending": str(follow.get("pending", "…"))[:20],
                          "wait": max(1, min(int(follow.get("wait", 40)) if str(follow.get("wait", 40)).isdigit() else 40, 300))}
    return rule


def load(path=None):
    """Les règles du fichier privé, validées ; () sans fichier ou s'il est illisible."""
    path = Path(path) if path else CONFIG
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return ()
    raw = data.get("rules") if isinstance(data, dict) else None
    try:
        return tuple(rule for rule in (_rule(r) for r in (raw if isinstance(raw, list) else ())) if rule)
    except Exception:  # noqa: BLE001 - un fichier hostile ne doit jamais empêcher le moteur de démarrer
        return ()


RULES = load()


def quiet(now):
    """Pendant le silence de nuit ?"""
    start, end = QUIET
    return now.hour >= start or now.hour < end


class Watch:
    """Le jugement des règles, d'une lecture à l'autre. `update` rend les règles à jouer maintenant."""

    def __init__(self, rules=None):
        self.rules = load() if rules is None else rules
        self.previous = {}         # nom -> dernier état lu
        self.fired = {}            # nom -> dernière réaction (datetime)
        self.read_at = {}          # nom -> dernière lecture (datetime)

    def due(self, now):
        """Les règles à relire maintenant."""
        return [rule for rule in self.rules
                if (now - self.read_at.get(rule["name"], datetime.datetime.min)).total_seconds() >= rule["every"]]

    def update(self, rule, state, now):
        """Une lecture du capteur de `rule` : vrai s'il faut réagir maintenant."""
        name = rule["name"]
        self.read_at[name] = now
        state = str(state or "").strip().lower()
        before, self.previous[name] = self.previous.get(name), state
        if state != rule["when"]:
            return False
        if rule["edge"] and before in (None, rule["when"]):
            return False           # pas un passage (premier tour, ou toujours appuyé)
        if not rule["night"] and quiet(now):
            return False           # on retentera après 7 h
        last = self.fired.get(name)
        if last is not None:
            if not rule["edge"] and last.date() == now.date():
                return False       # une fois par jour
            if (now - last).total_seconds() < rule["cooldown"]:
                return False
        self.fired[name] = now
        return True


def who(rule, states):
    """La première détection allumée de la règle (`states` : entité -> état), ou ""."""
    for kind, entity in rule.get("who", ()):
        if str(states.get(entity, "")).strip().lower() == "on":
            return kind
    return ""


def read_state(output):
    """L'état dans la sortie de `ha.py state` (« Nom lisible : état »)."""
    return str(output or "").strip().rsplit(" : ", 1)[-1].strip() if " : " in str(output or "") else ""
