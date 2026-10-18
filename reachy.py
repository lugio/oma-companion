#!/usr/bin/env python3
"""Robot d'Alison : un Reachy Mini (Pollen Robotics), son corps.

Utilitaire du plugin, sur le modèle de `ha.py` et `portail.py` : **seul** à parler au robot, par
l'API réseau de son service (`reachy-mini-daemon`, port 8000). Aucun appel libre à cette API :
des verbes fixes, et rien d'autre.

  reachy.py tester        la connexion, et rien d'autre
  reachy.py regarder      une photo de sa caméra (1280×720), son chemin imprimé — une carte à
                          chaque fois ; le moteur l'efface après la réponse
  reachy.py gestes        les émotions et les danses qui existent (listes de Pollen)
  reachy.py emotion <nom> joue une émotion de la liste, et attend qu'elle soit finie
  reachy.py danse [nom]   une danse de la liste (au hasard sans nom), et attend la fin

Le moteur l'importe aussi pour le **reflet** (`Body`) : le robot montre ce qu'elle fait — elle
écoute, réfléchit, parle — comme l'avatar du panneau. Le reflet ne fait que bouger la tête et les
antennes ; il ne passe pas par le cerveau et n'agit sur rien d'autre.

Adresse : `~/.local/state/omarchy-companion/robot-source.json` (600), écrite par le moteur d'après
les Réglages — {"url": "http://127.0.0.1:8000"}. Le robot peut être branché sur ce portable ou sur
une autre machine du réseau : seule l'adresse change.

Pièges mesurés le 09/10/2026 (spec `2026-10-09-corps-reachy-mini.md`) :
- `POST /api/move/stop` exige `{"uuid": …}`, lu dans `GET /api/move/running` (sinon 422) ;
- réveillé mais moteurs désactivés, il accepte tout et ne bouge pas : `set_mode/enabled` d'abord.
"""
import collections
import json
import texts
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import reachy_reglages
from reachy_reglages import Reglages

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy-companion"
SOURCE = STATE / "robot-source.json"
TIMEOUT = 2.0                     # rien n'attend le robot plus longtemps
EMOTIONS = "pollen-robotics/reachy-mini-emotions-library"
VERBS = ("tester", "regarder", "gestes", "emotion", "danse")
DANCES = "pollen-robotics/reachy-mini-dances-library"
GESTURE_MAX = 30                   # secondes : au-delà, on rend la main (une danse dure 5 à 15 s)
# La photo de « regarder » : un seul fichier, écrasé à chaque fois, effacé par le moteur après la
# réponse (comme la capture d'écran). Dossier 700, fichier 600.
VIEW = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "omarchy-companion" / "robot" / "vue.jpg"
# « Observer les gestes sans réagir » (11/10) : chaque geste vu y est gardé (image + mesures), dossier 700, 100 au plus.
GESTES_PREUVES = VIEW.parent / "gestes"

# Ce que montre le corps pour chaque état publié par le moteur (`note_activity`). Des DONNÉES :
# une émotion de la bibliothèque Pollen, ou un geste nommé ci-dessous. Un état absent = rien.
REFLECT = {
    "listening": "attentive1",     # seulement au réveil : voir `QUIET_AFTER` (recette du 09/10)
    "thinking": "thoughtful1",
    "acting": "thoughtful2",
    "waiting": "inquiring2",       # une carte attend une décision
    "speaking": "@parole",          # hochements tant qu'elle parle
    "idle": "@neutre",
    "error": "oops1",
    "incompris": "@incompris",      # sa réponse est « pas compris » : la mimique choisie dans la page (11/10)
}
# Une écoute qui SUIT ces états est la réécoute automatique de la conversation, souvent sans
# parole (deux écoutes vides puis micro coupé) : rejouer « attentif » à chaque fois faisait bouger le
# robot sans qu'on lui parle (recette du 09/10). Seul le réveil (depuis le repos) le joue.
QUIET_AFTER = ("speaking", "incompris", "transcribing", "thinking", "acting", "waiting")
# Retour visible d'une décision de carte (validée au clic ou à la voix).
DECISION = {"allow": "yes1", "deny": "no1"}


def load_url():
    try:
        return str(json.loads(SOURCE.read_text()).get("url") or "").strip().rstrip("/")
    except (OSError, ValueError):
        return ""


class Robot:
    """Les quelques appels permis à l'API du robot. Chacun rend la réponse décodée, ou lève."""

    def __init__(self, url):
        self.url = url.rstrip("/")
        self.last_goto = None       # (heure, (lacet, tangage, roulis) visés en radians, durée) — proprioception
        self.busy_until = 0.0       # un mouvement enregistré (émotion, réveil, sommeil) : trajectoire inconnue

    def moving(self):
        """Le démon exécute-t-il un mouvement (n'importe lequel, lancé par le corps ou par Home Assistant) ? (15/10)"""
        en_cours = self.call("/api/move/running")
        return isinstance(en_cours, list) and any(isinstance(m, dict) and m.get("uuid") for m in en_cours)

    def call(self, path, body=None, method=None):
        data = None if body is None and method != "POST" else json.dumps(body or {}).encode()
        request = urllib.request.Request(self.url + path, data=data, method=method or ("POST" if data else "GET"),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            raw = answer.read()
        return json.loads(raw) if raw else None

    def status(self):
        return self.call("/api/daemon/status")

    def enable(self):
        self.call("/api/motors/set_mode/enabled", method="POST")

    def stop(self):
        for move in self.call("/api/move/running") or []:
            uuid = move.get("uuid") if isinstance(move, dict) else move
            if uuid:
                self.call("/api/move/stop", {"uuid": str(uuid)})

    def emotion(self, name):
        self.play(EMOTIONS, name)

    def play(self, dataset, name):
        self.busy_until = time.monotonic() + RECORDED_MOVE
        self.stop()
        self.call(f"/api/move/play/recorded-move-dataset/{dataset}/{name}", method="POST")

    def sleep(self):
        """La posture de sommeil de Pollen (`/api/move/play/goto_sleep` : tête basse, antennes repliées)."""
        self.busy_until = time.monotonic() + RECORDED_MOVE
        self.stop()
        self.call("/api/move/play/goto_sleep", method="POST")

    def wake(self):
        """Le réveil de Pollen (`/api/move/play/wake_up` : retour à la pose initiale). `goto_sleep` finit
        moteurs COUPÉS (« rest limp », démon 1.11) : sans `enable` d'abord, le réveil ne bouge rien
        (10/10, robot resté couché une heure alors que le corps se croyait réveillé)."""
        self.busy_until = time.monotonic() + RECORDED_MOVE
        self.stop()
        self.enable()
        self.call("/api/move/play/wake_up", method="POST")

    def target(self, head, antennas):
        """Une pose du contrôle continu (`set_target`) : ignorée si un mouvement enregistré tourne."""
        self.call("/api/move/set_target", {"target_head_pose": head, "target_antennas": list(antennas)})

    def pose(self, pitch=0.0, yaw=0.0, roll=0.0, antennas=(0.0, 0.0), duration=0.5):
        self.last_goto = (time.monotonic(), (yaw, pitch, roll), duration)
        self.call("/api/move/goto", {
            "head_pose": {"x": 0, "y": 0, "z": 0, "roll": roll, "pitch": pitch, "yaw": yaw},
            "antennas": list(antennas), "duration": duration})


# Les mouvements continus reprennent les réglages de l'appli de conversation de Pollen, lus dans
# son code le 09/10 (reachy_mini/motion/speech_tapper.py `SwayRollRT`, moves.py `BreathingMove`) :
# pendant la parole, des sinus sur six axes MODULÉS PAR LE VOLUME de la voix ; au repos, une
# respiration lente. Envoyés par `set_target` (le contrôle continu), jamais par des `goto` en rafale :
# un `goto` en cours fait ignorer tous les `set_target`.
TICK = 0.05                        # 20 poses par seconde (le service du robot tourne à 50 Hz)
SWAY = {                           # axe : (fréquence en Hz, amplitude) — degrés ou mètres (SWAY_F_*, SWAY_A_*)
    "pitch": (2.2, 4.5), "yaw": (0.6, 7.5), "roll": (1.3, 2.25),
    "x": (0.35, 0.0045), "y": (0.45, 0.00375), "z": (0.25, 0.00225),
}
SWAY_MASTER = 1.5
ATTACK, RELEASE = 0.05, 0.25       # montée et retombée de l'enveloppe (secondes)
ANTENNA_REST = 10.0                # degrés, repos (-10°, +10°) : à 0° immobiles, elles tremblent (doc Pollen)
# Antennes = témoin du micro (10/10, idée de Hermes Voice — parichai/hermes_voice, sans licence : l'idée
# seulement, aucun code) : DRESSÉES quand elle écoute, au repos sinon, BAISSÉES quand le micro est coupé.
# 0° = verticales (Pollen : `INIT_ANTENNAS_JOINT_POSITIONS` ±10° « pour qu'elles ne tremblent pas à la
# verticale ») ; ±175° = repliées (`SLEEP_ANTENNAS_JOINT_POSITIONS` ±3,05 rad), même signe que le repos.
ANTENNA_LISTEN = 3.0               # degrés : presque droites, le temps d'une écoute (quelques secondes)
ANTENNA_MUTE = 110.0               # degrés : baissées sur le côté, bien visibles, loin du sommeil (175°)
# Au repos : un lent hochement, ±7° sur 4 s, par `goto` — le contournement de la communauté à la
# respiration de Pollen (z ±5 mm en `set_target` continu), qui fait frémir les moteurs de la
# plateforme (reachy_mini_conversation_app, issue #224, non résolue ; constaté ici le 09/10).
NOD_PITCH = 7.0                    # degrés
NOD_HALF = 2.0                     # secondes par demi-cycle (4 s le cycle)
BLEND = 0.35                       # secondes : retour en douceur avant le balancement (pas de saut)
BREATH_SECONDS = 120               # au repos, elle respire deux minutes puis se tient immobile


# Se tourner vers celui qui parle (lot 5) : la direction d'arrivée du son, lue sur la carte son du
# robot (XMOS XVF3800) par USB — comme `media/audio_doa.py` du SDK. Seulement si le robot est branché
# SUR CETTE machine (sinon : pas d'oreilles, il garde le reflet). Exige `python-pyusb` et la règle
# udev officielle de Pollen (38fb:1001, posée le 09/10).
# Angle renvoyé : 0 = sa gauche, π/2 = face, π = sa droite (doc Pollen) ; la tête tourne de
# (π/2 − angle) — lacet positif = vers sa gauche. Sens confirmé à la recette du 09/10 (« vers moi »).
# Les micros sont DANS LA TÊTE : l'angle se lit depuis la tête, pas depuis le socle (exemple officiel
# `examples/sound_doa.py` du SDK : le point est tourné par la pose de tête courante). Corrigé le 09/10 :
# lu comme absolu, une voix déjà en face (π/2) ramenait la tête au centre.
DOA_SIGN = 1.0
FACE_LIMIT = 50.0                  # degrés de lacet au plus (tête/corps ≤ 65° dans le SDK)
FACE_STEP = 8.0                    # on ne retourne la tête que si la voix s'est déplacée d'autant
EARS_EVERY = 0.2                   # secondes entre deux lectures pendant qu'elle écoute


# Toucher une antenne = la réveiller (lot 6). Le service de Pollen sait le détecter (écart ≥ 0,25 rad,
# `AntennaTouchDetector`), mais moteurs actifs un doigt n'écarte l'antenne que de 5,4° (mesuré le
# 09/10 ; bruit 0,6°) : seuil à 3°, relâché sous 1,5°. Seulement au REPOS, après un temps de grâce
# (le retour au neutre déplace les antennes), et une fois toutes les 3 s au plus.
TOUCH_PRESS = 3.0                  # degrés
TOUCH_RELEASE = 1.5
TOUCH_EVERY = 0.1                  # secondes entre deux lectures, au repos
TOUCH_GRACE = 1.5                  # secondes après l'arrivée au repos
TOUCH_COOLDOWN = 3.0
TOUCH_TIMEOUT = 1.5                # secondes : un appui plus long est jugé sans attendre le relâché
# Appui LONG (10/10, idée de la classe `AntennaButton` de l'app Radio de Pollen — sans licence déclarée :
# l'idée seulement) : une antenne tenue écartée TOUCH_LONG secondes = un bouton (« coupe le micro »).
# Seulement si le corps sait quoi en faire (`Touch(long=True)`) ; sinon, comme avant, jugé à 1,5 s.
TOUCH_LONG = 2.5
# Doux ou brusque (recette du 09/10, 11 touchers mesurés) : caresses à 4-7°, montée lente (32°/s) ;
# tapes à 17-35°, jusqu'à 227°/s. Brusque dès qu'on dépasse l'un des deux seuils.
TOUCH_HARD_DEGREES = 12.0
TOUCH_HARD_SPEED = 60.0            # degrés par seconde
# 11/10 toucher silencieux : les émotions enregistrées de Pollen ci-dessous FONT DU SON (même la nuit). Par
# défaut, une antenne touchée déclenche un geste silencieux de notre bibliothèque (`TOUCH_GESTE`, plus bas) ;
# TOUCH_REACTION ne sert plus que si la personne active « Réaction sonore de Pollen » (réglage `toucher_son`).
TOUCH_REACTION = {"doux": "cheerful1", "brusque": "surprised1"}
# Le toucher du CORPS (10/10, facultatif : `alive["toucher"]`). Le démon donne la position réelle des 7
# moteurs (le corps + les 6 qui portent la tête), pas leur effort. Mesuré le 10/10, robot immobile, moteurs
# actifs : bruit 0,09° ; main posée sur la tête 0,8-1° ; tête poussée 2-8° (et elle RESTE où on l'a mise) ;
# corps tourné 3,7° (il revient seul). On compare à la position d'avant le contact, pas à une position fixe.
FULL_STATE = ("/api/state/full?with_head_joints=true&with_antenna_positions=true&with_body_yaw=true"
              "&with_head_pose=true")
BODY_PRESS = 0.5                   # degrés sur un moteur : une main est là
BODY_PUSH = 1.5                    # degrés : au-delà, on pousse (en dessous : une main posée, une caresse)
BODY_STILL = 0.2                   # degrés : écart maximal sur BODY_SETTLE s pour dire « ça ne bouge plus »
BODY_SETTLE = 0.5                  # secondes
BODY_HOLD = 5.0                    # secondes : un contact plus long est jugé sans attendre
BODY_COOLDOWN = 2.0                # secondes entre deux contacts


RECORDED_MOVE = 6.0                # secondes : durée prudente d'un mouvement enregistré de Pollen
FOREIGN_GRACE = 2.0                # secondes après un mouvement du démon lancé par un autre (HA) : antennes qui reviennent
PROPRIO_LOG = (Path(os.environ["XDG_RUNTIME_DIR"]) if os.environ.get("XDG_RUNTIME_DIR") else
               Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))) / "reachy-proprio.jsonl"
PROPRIO_LINES = 20000


def minimum_jerk(s):
    """La courbe des `goto` de Pollen (`InterpolationTechnique.MIN_JERK`) : 0 → 1 sans à-coup."""
    s = max(0.0, min(1.0, s))
    return 10 * s ** 3 - 15 * s ** 4 + 6 * s ** 5


class Proprio:
    """Où la tête DEVRAIT être : le dernier `goto` commandé, rejoué sur la courbe de Pollen depuis la
    position mesurée au moment de la commande. Pure, testable. Angles en radians, (lacet, tangage, roulis)."""

    def __init__(self):
        self.command = None
        self.start = None
        self.present = None

    def expected(self, last_goto, now):
        if last_goto is None:
            return None
        if last_goto is not self.command:
            self.command = last_goto
            self.start = self.present if self.present is not None else last_goto[1]
        t0, goal, duration = last_goto
        k = minimum_jerk((now - t0) / duration if duration > 0 else 1.0)
        return tuple(a + (b - a) * k for a, b in zip(self.start, goal))

    def moving(self, last_goto, now, margin=0.3):
        return last_goto is not None and now < last_goto[0] + last_goto[2] + margin


class BodyTouch:
    """Le toucher du corps : un écart des moteurs par rapport à la position d'avant le contact, jugé quand
    tout s'immobilise de nouveau. → ("tête", "caresse" | "poussée sur le côté" | "poussée vers le bas" |
    "levée" | "penchée") ou ("corps", "tourné à gauche" | "tourné à droite"), sinon None. Pure, testable.
    `joints` = [corps, 6 moteurs de la tête] et `pose` = (lacet, tangage, roulis), en radians."""

    def __init__(self, reglages=None):
        self.r = reglages if reglages is not None else Reglages()   # seuils : constantes, ou le fichier (11/10)
        self.reset()
        self.last = -1e9

    def reset(self):
        self.reference, self.history, self.press = None, [], None

    def update(self, joints, pose, now):
        j = [math.degrees(v) for v in joints]
        p = [math.degrees(v) for v in pose]
        self.history = [h for h in self.history if now - h[0] <= BODY_SETTLE] + [(now, j)]
        if self.reference is None:
            self.reference = (j, p)
            return None
        rj, rp = self.reference
        body = abs(j[0] - rj[0])
        head = max(abs(a - b) for a, b in zip(j[1:], rj[1:]))
        if self.press is None:
            if max(body, head) >= self.r("body_press") and now - self.last >= self.r("body_cooldown"):
                self.press = {"start": now, "body": body, "head": head, "turn": j[0] - rj[0],
                              "pose": [a - b for a, b in zip(p, rp)]}
            return None
        press = self.press
        if body > press["body"]:
            press["body"], press["turn"] = body, j[0] - rj[0]
        if head > press["head"]:
            press["head"], press["pose"] = head, [a - b for a, b in zip(p, rp)]
        old = self.history[0]
        still = now - old[0] >= BODY_SETTLE - 0.05 and all(
            max(abs(a - b) for a, b in zip(h[1], j)) <= BODY_STILL for h in self.history)
        if not (still and now - press["start"] >= BODY_SETTLE) and now - press["start"] < BODY_HOLD:
            return None
        self.reference, self.press, self.last = (j, p), None, now
        push = self.r("body_push")
        if press["body"] >= push and press["body"] >= press["head"]:
            return "corps", "tourné à gauche" if press["turn"] > 0 else "tourné à droite"
        if press["head"] < push:
            return "tête", "caresse"
        yaw, pitch, roll = press["pose"]
        biggest = max((abs(yaw), "yaw"), (abs(pitch), "pitch"), (abs(roll), "roll"))[1]
        if biggest == "yaw":
            return "tête", "poussée sur le côté"
        if biggest == "pitch":
            return "tête", "poussée vers le bas" if pitch > 0 else "levée"
        return "tête", "penchée"


class Touch:
    """Hystérésis sur l'écart des antennes à leur position de repos mesurée, et le jugement du
    toucher : « doux » ou « brusque », rendu au relâché (ou après TOUCH_TIMEOUT). Pure, testable."""

    def __init__(self, long=False, reglages=None):
        self.r = reglages if reglages is not None else Reglages()   # seuils : constantes, ou le fichier (11/10)
        self.reference = None
        self.armed = False
        self.last = -1e9
        self.long = long           # l'appui long existe-t-il (`"long"`) ?
        self.press = None          # appui en cours : {début, crête, vitesse, dernier écart, dernière heure}

    def reset(self):
        self.reference, self.armed, self.press = None, False, None

    def update(self, present, now):
        """"doux" ou "brusque" au moment où un toucher se termine, "long" pour une antenne tenue
        TOUCH_LONG secondes (si `long`), sinon None."""
        if self.reference is None:
            self.reference, self.armed = present, True
            return None
        delta = max(abs(math.degrees(p - r)) for p, r in zip(present, self.reference))
        if self.press is not None:
            press = self.press
            press["peak"] = max(press["peak"], delta)
            if now > press["at"]:
                press["speed"] = max(press["speed"], (delta - press["delta"]) / (now - press["at"]))
            press["delta"], press["at"] = delta, now
            if self.long and delta > TOUCH_RELEASE and now - press["start"] >= self.r("touch_long"):
                self.press, self.last, self.armed = None, now, False
                return "long"
            if delta <= TOUCH_RELEASE or (not self.long and now - press["start"] >= TOUCH_TIMEOUT):
                self.press, self.last = None, now
                self.armed = delta <= TOUCH_RELEASE
                hard = press["peak"] >= self.r("touch_hard_degrees") or press["speed"] >= self.r("touch_hard_speed")
                return "brusque" if hard else "doux"
            return None
        if not self.armed:
            self.armed = delta <= TOUCH_RELEASE
            return None
        if delta >= self.r("touch_press") and now - self.last >= self.r("touch_cooldown"):
            self.armed = False
            self.press = {"start": now, "peak": delta, "speed": 0.0, "delta": delta, "at": now}
        return None


class Ears:
    """La direction d'arrivée du son, ou None (robot ailleurs, pyusb absent, lecture ratée)."""

    IDS = ((0x38FB, 0x1001), (0x2886, 0x001A))   # firmware Reachy, puis ancien firmware ReSpeaker

    def __init__(self):
        self.device = None
        try:
            import usb.core
            self.usb = usb
            for vendor, product in self.IDS:
                self.device = usb.core.find(idVendor=vendor, idProduct=product)
                if self.device is not None:
                    break
        except Exception:
            self.device = None

    def read(self):
        """(angle en radians, parole détectée) — DOA_VALUE_RADIANS : resid 20, cmdid 19, 2 flottants."""
        if self.device is None:
            return None
        import struct
        util = self.usb.util
        try:
            for _ in range(20):
                answer = self.device.ctrl_transfer(
                    util.CTRL_IN | util.CTRL_TYPE_VENDOR | util.CTRL_RECIPIENT_DEVICE, 0, 0x80 | 19, 20, 9, 500)
                if answer[0] == 0:
                    angle, speech = struct.unpack("<ff", bytes(answer[1:9]))
                    return angle, speech > 0.5
                time.sleep(0.01)
        except Exception:
            self.device = None
        return None


def facing_for(angle, facing=0.0, limit=None):
    """Le lacet de tête (radians) pour regarder d'où vient la voix, borné. `facing` = le lacet de la
    tête au moment de la mesure (l'angle est lu depuis la tête). `limit` (degrés) : FACE_LIMIT sans réglage."""
    yaw = facing + DOA_SIGN * (math.pi / 2 - angle)
    limit = math.radians(FACE_LIMIT if limit is None else limit)
    return max(-limit, min(limit, yaw))



# Vivant au repos (09/10/2026, spec `2026-10-09-reachy-vivant.md`). Trois comportements, chacun
# coupable, qui n'existent QU'AU REPOS (le reflet garde la main dès qu'elle écoute, pense ou parle),
# tous par `goto` doux (jamais de flux continu au repos : issue #224 citée plus haut).
# 1. Petits gestes de temps en temps — repris de « Reachy Alive » (HTurlet15/reachy_alive, Apache-2.0 :
#    un geste toutes les 20 à 30 s, le reste du temps elle respire). Ici des gestes BREFS et bornés,
#    écrits ci-dessous, jamais une danse ni une émotion de la bibliothèque.
LIFE_EVERY = (20.0, 40.0)          # secondes entre deux gestes, tirées au hasard
# Un geste = des étapes (tangage, lacet, roulis, antennes — degrés, relatifs au regard du moment ;
# durée en s). La dernière ramène toujours au regard. Le signe du lacet est tiré à chaque fois.
GESTURES = {
    "coup d'œil": [(0, 22, 0, 0, 0.8), (0, 22, 0, 0, 1.2), (0, 0, 0, 0, 0.9)],
    "penche la tête": [(0, 0, 9, 0, 0.8), (0, 0, 9, 0, 1.5), (0, 0, 0, 0, 0.8)],
    "antennes": [(0, 0, 0, 20, 0.3), (0, 0, 0, 0, 0.3), (0, 0, 0, 20, 0.3), (0, 0, 0, 0, 0.4)],
    "soupir": [(7, 0, 0, -8, 1.4), (0, 0, 0, 0, 1.6)],
    "lève les yeux": [(-9, 6, 0, 0, 1.0), (-9, 6, 0, 0, 1.0), (0, 0, 0, 0, 1.0)],
}
# Quelqu'un de connu est reconnu (10/10) : antennes dressées deux fois et un petit hochement, SANS son et
# sans quitter la personne des yeux (décalages relatifs au regard). À part de GESTURES : jamais au hasard.
GREETING = [(-5, 0, 0, 25, 0.4), (0, 0, 0, 0, 0.3), (-5, 0, 0, 25, 0.3), (2, 0, 0, 0, 0.5)]
# 11/10 toucher silencieux : la réponse à une antenne touchée au repos, SANS son. Une caresse = le même petit
# salut que pour une personne connue ; une tape = un sursaut : la tête part en arrière, les antennes se
# dressent d'un coup, puis il se reprend doucement (relatif au regard, la dernière étape ramène au calme).
STARTLE = [(-7, 0, 0, 30, 0.12), (-7, 0, 0, 30, 0.45), (0, 0, 0, 0, 0.8)]
TOUCH_GESTE = {"doux": GREETING, "brusque": STARTLE}
# 2. Regarder d'où vient une voix, même sans mot d'éveil — repris de « Reachy Sound Seeker »
#    (aidn/reachy_sound_seeker) : médiane des 5 dernières directions, on ne bouge que si elle s'est
#    déplacée de 12°, pas plus d'une réaction toutes les 0,55 s, retour au centre après un silence.
VOICE_MEDIAN = 5
VOICE_MIN = 3                      # mesures de parole (0,2 s chacune) avant de croire une direction
VOICE_WINDOW = 1.5                 # secondes : au-delà, une mesure est oubliée
VOICE_STEP = 12.0                  # degrés
VOICE_GAP = 0.55                   # secondes entre deux réactions
VOICE_HOLD = 4.0                   # secondes de regard avant de rendre la main (vue, centre)
# La télé : un secteur ignoré, MESURÉ et écrit dans les réglages (`ignorer`, degrés dans le repère du
# socle). Une habituation à la part de parole a été essayée et retirée le 09/10 : au salon, la télé
# parle 4 à 8 % du temps par secteur de 15°, une voix humaine 6 % — indiscernables par ce critère.
# 3. Suivre une personne du regard : la vue (`reachy_vue.py`, détecteur et suivi de Pollen). On
#    vise par petits `goto` (« saccades ») et on attend que la tête soit arrivée avant de croire la
#    prochaine image (la caméra est dans la tête).
TRACK_DEAD = 4.0                   # degrés : en deçà, on ne bouge pas
TRACK_GAIN = 0.8                   # on vise un peu court : pas de dépassement
TRACK_PITCH = (-10.0, 15.0)        # degrés (positif = vers le bas)
TRACK_FRESH = 1.0                  # secondes : une observation plus vieille ne compte pas
TRACK_LOST = 4.0                   # secondes sans personne avant de revenir au centre
AWARE_EVERY = 5.0                  # secondes entre deux publications de la conscience (10/10)
PERSON_AGAIN = 600.0               # secondes avant d'annoncer de nouveau la même personne (10/10)
SETTLE = 0.4                       # secondes après la fin d'un mouvement avant de croire capteurs
ALIVE_EVERY = 0.1                  # secondes entre deux tours de la boucle au repos
# Un raté (le service a mis plus de TIMEOUT à répondre, vu le 09/10 juste après une conversation)
# marque le robot injoignable ; sans vivant, le prochain état de la voix le réveille. Au repos, rien
# n'arrive : on réessaie donc toutes les RETRY secondes, sinon il resterait figé jusqu'à la prochaine
# conversation.
RETRY = 5.0
# 9. RÉGLAGES À CHAUD (11/10, spec `2026-10-11-reachy-page-reglages.md`, lot 1) : le fichier de réglages
#    (`fichier`, `vivant.json` sur la machine du robot) est relu quand il change, sans redémarrer — seules les clés du
#    schéma (`reachy_reglages`) ; la source de la caméra et le dossier des visages restent ceux du démarrage.
RELIRE_EVERY = 1.0                 # secondes entre deux regards sur la date du fichier
# 10. LA PAGE (11/10, lot 2) : facultative, `alive["page"]` = {"hote": "<adresse du réseau local>", "port": 8010}.
#    Elle lit un instantané du corps (`etat`) déjà en mémoire : aucun appel de plus au robot ni à la caméra.
JOURNAL_LINES = 60                 # lignes de journal gardées pour la page
# 11. LE MODE MESURE (11/10, lot 4 : assistants de calibrage). Pendant qu'un assistant mesure, le corps se fige :
#    ni petits gestes, ni suivi du regard, ni regard vers les voix, ni réaction au toucher, tête immobile —
#    mais il continue de tourner (la page, qui sert l'assistant, vit dedans : on ne l'arrête plus, contrairement
#    à `mesure_toucher.sh` du 10/10). Il se lève seul : fin de l'assistant, annulation, MEASURE_MAX secondes,
#    ou quelqu'un parle au robot. Sans mode mesure, rien ne change.
MEASURE_MAX = 600.0                # secondes : au-delà, le mode se lève tout seul
# 4. Regarder CELLE OU CELUI QUI PARLE (10/10, idée de « Look Who's Talking » — EryriLabs/look_whos_talking,
#    sans licence : l'idée seulement). Quand une voix arrive et que la vue voit des visages, on prend le
#    visage dont la direction (repère du socle) est la plus proche de la voix, à SPEAKER_MATCH près, et le
#    suivi s'y accroche (`Tracker.prefer`). Pas de lecture des lèvres : au canapé (2-3 m) un visage fait
#    ~25 px dans une image floue de 640×360, la bouche quelques pixels, et 3 images par seconde ne voient
#    pas des syllabes à 4-5 Hz — mesure impossible ici, la direction du son suffit à départager.
SPEAKER_MATCH = 20.0               # degrés entre la voix et un visage pour dire « c'est lui »
# 5. DODO (10/10, besoin initial « un mode dodo quand il n'y a plus de bruit de présence ») : personne
#    vu (hors télé) ni entendu (hors secteur ignoré) depuis `dodo` minutes → la posture de sommeil de
#    Pollen, plus de gestes ni de suivi, la vue ralentie à une image toutes les DOZE_EVERY s. Réveil : une
#    voix hors télé, un visage, un toucher, ou une conversation (mot d'éveil) → le réveil de Pollen.
DOZE_EVERY = 3.0                   # secondes entre deux images quand elle dort
WAKE_SETTLE = 3.0                  # secondes : le réveil de Pollen se joue sans être interrompu
# 6. ÉCO (10/10, « mode éco de nuit ou sans production solaire ») : drapeau tenu ailleurs (`set_eco`) ;
#    vue à une image par seconde, gestes deux fois plus rares, dodo après `eco` minutes.
ECO_EVERY = 1.0                    # secondes entre deux images
ECO_LIFE = 2.0                     # gestes ECO_LIFE fois plus espacés


class Attention:
    """Où regarder quand quelqu'un parle, au repos. Pure, testable : `hear()` reçoit le lacet (dans
    le repère du socle) d'une mesure de parole et rend la direction à regarder, ou None."""

    def __init__(self, ignore=(), reglages=None):
        self.r = reglages if reglages is not None else Reglages()
        self.recent = []           # (heure, lacet en degrés) des dernières mesures de parole
        self.ignore = [tuple(sorted(r)) for r in ignore]   # secteurs ignorés, en degrés
        self.last_turn = -1e9
        self.looking = None        # degrés : la direction regardée à cause d'une voix

    def ignored(self, yaw_degrees):
        return any(low <= yaw_degrees <= high for low, high in self.ignore)

    def hear(self, yaw_degrees, now):
        if self.ignored(yaw_degrees):
            return None
        self.recent = [(at, y) for at, y in self.recent if now - at <= VOICE_WINDOW][-(VOICE_MEDIAN - 1):]
        self.recent.append((now, yaw_degrees))
        if len(self.recent) < self.r("voice_min") or now - self.last_turn < VOICE_GAP:
            return None
        middle = sorted(y for _, y in self.recent)[len(self.recent) // 2]
        if self.looking is not None and abs(middle - self.looking) < self.r("voice_step"):
            self.last_turn = now               # toujours la même voix : on garde le regard
            return None
        self.looking, self.last_turn = middle, now
        return middle

    def forget(self):
        self.recent, self.looking = [], None


# 8. HUMEUR (10/10, idée du robot Vector d'Anki, rapport `2026-10-10_robot-vivant-conscience-du-corps.md`) :
#    trois jauges dans [-1, 1] — plaisir, éveil, lien — qui REVIENNENT TOUJOURS au calme (0) avec une
#    demi-vie de MOOD_HALF secondes. Des événements les poussent ; elles ne servent qu'à CHOISIR les petits
#    gestes (silencieux) et leur fréquence. À humeur neutre, rien ne change (même tirage qu'avant).
MOOD_HALF = 300.0
MOOD_NEUTRAL = 0.05                # en dessous (toutes les jauges) : humeur neutre
MOOD_EVENTS = {"caresse": {"plaisir": 0.4, "lien": 0.3}, "tape": {"plaisir": -0.3, "eveil": 0.5},
               "reconnu": {"lien": 0.5, "plaisir": 0.3}, "conversation": {"lien": 0.2, "eveil": 0.2},
               "voix": {"eveil": 0.1}, "seul": {"eveil": -0.3, "lien": -0.2},
               "contact": {"eveil": 0.2, "lien": 0.1}, "coucou": {"lien": 0.4, "plaisir": 0.3}}
GESTURE_MOOD = {"antennes": {"plaisir": 1.0}, "penche la tête": {"lien": 1.0},
                "coup d'œil": {"eveil": 1.0}, "lève les yeux": {"eveil": 0.5, "lien": 0.5},
                "soupir": {"eveil": -1.0, "plaisir": -0.5}}
MOOD_STRENGTH = 1.5                # poids d'un geste = exp(force × affinité · humeur)


class Mood:
    """Plaisir, éveil, lien : poussés par des événements, ramenés au calme par le temps. Pure, testable."""

    def __init__(self, reglages=None):
        self.r = reglages if reglages is not None else Reglages()
        self.gauges = {"plaisir": 0.0, "eveil": 0.0, "lien": 0.0}
        self.at = None

    def peek(self, now):
        """Une copie des jauges à l'heure `now`, SANS toucher à l'humeur : pour la page, lue dans un autre fil."""
        copy = Mood(self.r)
        copy.gauges, copy.at = dict(self.gauges), self.at
        copy.now(now)
        return copy

    def now(self, now):
        """Les jauges à l'heure `now` (le retour au calme est appliqué)."""
        if self.at is not None and now > self.at:
            factor = 0.5 ** ((now - self.at) / self.r("mood_half"))
            self.gauges = {k: v * factor for k, v in self.gauges.items()}
        self.at = now if self.at is None else max(self.at, now)
        return self.gauges

    def feel(self, event, now):
        self.now(now)
        for k, v in MOOD_EVENTS.get(event, {}).items():
            self.gauges[k] = max(-1.0, min(1.0, self.gauges[k] + v))

    def neutral(self, now):
        return all(abs(v) < MOOD_NEUTRAL for v in self.now(now).values())

    def label(self, now):
        g = self.now(now)
        if all(abs(v) < MOOD_NEUTRAL for v in g.values()):
            return "calme"
        if g["plaisir"] <= -0.2 and g["eveil"] >= 0.2:
            return "agacé"
        if g["eveil"] <= -0.2:
            return "un peu las"
        if g["lien"] >= 0.3:
            return "content de voir du monde"
        if g["plaisir"] >= 0.2:
            return "joyeux"
        return "éveillé" if g["eveil"] >= 0.2 else "tranquille"

    def weights(self, names, now):
        import math as _m
        g = self.now(now)
        return [_m.exp(self.r("mood_strength") * sum(a * g.get(k, 0.0) for k, a in GESTURE_MOOD.get(n, {}).items()))
                for n in names]


class Life:
    """Le prochain petit geste, et quand. Pure, testable (`chance` injectable)."""

    def __init__(self, chance=random, reglages=None):
        self.chance = chance
        self.r = reglages if reglages is not None else Reglages()
        self.next = None

    def due(self, now, mood=None):
        """Les étapes du geste à jouer maintenant, ou None. Premier geste après un premier délai.
        `mood` (facultatif, 10/10) : l'humeur choisit le geste et l'éveil resserre l'intervalle ; neutre ou
        absente = exactement le tirage d'avant."""
        if self.next is None:
            self.next = now + self.chance.uniform(*self.r("life_every"))
            return None
        if now < self.next:
            return None
        lively = mood is not None and not mood.neutral(now)
        pace = 1.0 - 0.4 * max(-1.0, min(1.0, mood.gauges["eveil"])) if lively else 1.0
        self.next = now + self.chance.uniform(*self.r("life_every")) * pace
        names = sorted(GESTURES)
        if lively:
            name = self.chance.choices(names, weights=mood.weights(names, now))[0]
        else:
            name = self.chance.choice(names)
        side = self.chance.choice((-1, 1))
        return name, [(pitch, side * yaw, side * roll, antennas, duration)
                      for pitch, yaw, roll, antennas, duration in GESTURES[name]]

    def postpone(self, now):
        self.next = now + self.chance.uniform(*self.r("life_every"))


# 7. CHUCHOTÉ (10/10, besoin initial : « un mode chuchoté, baisser le volume en soirée et si pas de bruit ») : le
#    volume de SA voix suit l'heure ET le bruit de la pièce, mesuré au micro du robot quand personne ne lui
#    parle. Fond mesuré le 10/10 à 1 h, télé éteinte : médiane 51, 90 % sous 86 (RMS 16 bits, 100 ms) ;
#    télé allumée : 200 à 350. Calme → doux, très calme → chuchoté, bruit (télé) → normal pour rester
#    audible. Le volume « normal » est celui de l'utilisateur ; on n'applique que des FACTEURS.
HUSH_DEFAULT = {"de": "21:00", "a": "07:00", "doux": 0.65, "chuchote": 0.4, "calme": 180, "tres_calme": 80}


class Hush:
    """Le cran de volume du moment : ("normal" | "doux" | "chuchote", facteur). Pur, testable.
    `settings` : dict (fusionné avec HUSH_DEFAULT), ou False / None = coupé. `{"actif": false, …}` = coupé
    aussi, en gardant les réglages du soir (11/10 : c'est ainsi que la page coupe la voix du soir)."""

    def __init__(self, settings):
        self.on = (settings is not False and settings is not None
                   and not (isinstance(settings, dict) and settings.get("actif") is False))
        self.settings = {**HUSH_DEFAULT, **(settings if isinstance(settings, dict) else {})}

    @staticmethod
    def minutes(text):
        hours, minutes = str(text).split(":")
        return int(hours) * 60 + int(minutes)

    def evening(self, minute_of_day):
        start, end = self.minutes(self.settings["de"]), self.minutes(self.settings["a"])
        if start <= end:
            return start <= minute_of_day < end
        return minute_of_day >= start or minute_of_day < end

    def step(self, minute_of_day, noise):
        """`noise` = fond sonore médian (None = inconnu : on reste prudent, « doux »)."""
        if not self.on or not self.evening(minute_of_day):
            return "normal", 1.0
        if noise is not None and noise > self.settings["calme"]:
            return "normal", 1.0
        if noise is not None and noise <= self.settings["tres_calme"]:
            return "chuchote", float(self.settings["chuchote"])
        return "doux", float(self.settings["doux"])


class Body:
    """Le reflet : une file et un fil. Le moteur dépose un état, un volume de voix ou une décision ;
    rien n'attend le réseau.

    `on_reach(ok)` est appelé quand le robot devient injoignable ou revient — une fois par
    changement, jamais à chaque mouvement raté (le moteur en fait une ligne de journal).

    `alive` (facultatif) : le comportement vivant au repos, chaque clé coupable —
    {"gestes": bool, "voix": bool, "regard": "<flux ou /dev/videoN>" ou "", "ignorer": [[min, max]…],
     "dodo": minutes sans présence avant de dormir (0 ou absent = jamais), "eco": idem en mode éco,
     "visages": dossier d'empreintes de visages (absent = pas de noms, 10/10)}.
    Absent = rien de plus que le reflet. `on_note(texte)` : une ligne de journal par décision.

    `on_mute(muet)` (facultatif) : l'appui long sur une antenne coupe / rétablit le micro ; le corps
    baisse les antennes tant qu'il est coupé (`set_muted` pour l'état de départ). Absent = pas d'appui long.

    Réglages (11/10, `reachy_reglages.py`) : les seuils et durées du corps se lisent par `self.reglage(clé)` —
    la valeur de `alive` si elle est valide, sinon la constante de ce fichier. Sans clé : comme avant. Trois
    clés neuves, actives sans réglage : `antennes` (réagir à une antenne touchée), `appui_long` (antenne tenue
    = micro), `suivre` (la tête suit la personne vue) ; `reconnaitre` met un nom sur un visage.
    `fichier` (facultatif) : le fichier d'où vient `alive` ; relu quand il change, appliqué sans redémarrer.
    """

    # Sans `alive`, rien du comportement vivant : ces valeurs de classe sont l'état « immobile ».
    alive = {}
    reglages = Reglages()       # les constantes du code (11/10) ; chaque corps a les siennes
    fichier = page = None       # page de réglages (11/10) : rien sans `fichier` ni `alive["page"]`
    journal = touches = None    # ce que la page affiche : des files propres à chaque corps (`__init__`)
    heard = motors_seen = None
    eyes = None
    person = on_person = None   # qui est là (10/10) : défauts de classe, comme `eyes`
    on_other = None             # une AUTRE personne reconnue (14/10) : défaut de classe, comme `on_person`
    on_aware = last_felt = None
    on_gesture = gesture_seen = last_gesture = None
    aware, aware_at = "", -1e9
    mood = None                 # l'humeur (10/10) : None = gestes tirés comme avant
    body_touch = None           # le toucher du corps (10/10) : None = les antennes seules, comme avant
    proprio = None              # la mesure « où devrait être ma tête » (10/10, `toucher: "mesure"`)
    announced = {}              # {nom: dernière annonce} — remplacé par un dict propre à chaque corps
    state = "idle"
    muted = asleep = eco = False
    on_mute = None
    waking_until = 0.0
    presence_at = 0.0
    steps = ()
    measure_name, measure_until, measure_reason = "", 0.0, ""   # le mode mesure (lot 4) : "" = pas de mesure
    settled = 0.0
    voice_at = seen_at = -1e9
    pitch = 0.0

    def __init__(self, url, on_reach=lambda ok: None, on_touch=None, alive=None, on_note=lambda text: None,
                 on_mute=None, on_person=None, on_aware=None, on_gesture=None, fichier=None, on_other=None):
        self.robot = Robot(url)
        self.on_reach = on_reach
        self.on_person = on_person  # la personne suivie est reconnue (10/10) : son nom, ou "inconnu"
        self.on_other = on_other    # une autre personne reconnue en même temps (14/10) : son nom ; None = journal seul
        self.on_aware = on_aware    # sa « conscience » (10/10) : une phrase à la 1re personne, quand elle change
        self.aware, self.aware_at, self.last_felt = "", -1e9, None
        self.on_gesture = on_gesture  # un geste vu (11/10) : on_gesture(« coucou » | « main », nom ou None)
        self.gesture_seen, self.last_gesture = None, None
        self.person = None
        self.announced = {}
        # Les réglages d'abord (11/10) : toucher, attention, humeur et gestes partagent CE même objet.
        self.reglages = Reglages(alive)
        self.mood = Mood(self.reglages)

        self.on_touch = on_touch    # une antenne touchée au repos (lot 6) ; None = pas de détection
        self.on_mute = on_mute      # appui long = micro coupé / rétabli (10/10) ; None = pas d'appui long
        self.muted = False
        self.asleep = False
        self.eco = False
        self.waking_until = 0.0
        self.presence_at = time.monotonic()
        self.touch = Touch(long=on_mute is not None and bool(self.reglages("appui_long")), reglages=self.reglages)
        self.inbox = queue.Queue()
        self.measure_lock = threading.Lock()      # le mode mesure se prend et se lève depuis plusieurs fils
        self.state = "idle"
        self.reachable = None
        self.enabled = False
        self.running = True
        self.voice = 0.0            # dernier volume de sa voix (0..1), publié 20 fois par seconde
        self.envelope = 0.0
        self.since = time.monotonic()
        self.phase = {axis: 0.0 for axis in SWAY}   # tirées au hasard à chaque prise de parole
        self.facing = 0.0           # lacet vers celui qui parle (lot 5), gardé jusqu'au repos
        self.ears = Ears() if url.startswith(("http://127.0.0.1", "http://localhost")) else None
        self.alive = dict(alive or {})
        # APRÈS `alive` (10/10 : créés avant, ils lisaient le dict vide de la classe et n'étaient jamais actifs)
        self.body_touch = BodyTouch(self.reglages) if self.alive.get("toucher") else None
        self.proprio = Proprio() if self.alive.get("toucher") == "mesure" else None
        self.next_proprio = 0.0
        self.journal = collections.deque(maxlen=JOURNAL_LINES)
        self.touches = collections.deque(maxlen=5)

        def note(text):                         # chaque ligne garde aussi son heure pour la page (11/10)
            self.journal.appendleft((time.strftime("%H:%M:%S"), text))
            on_note(text)
        self.on_note = note
        self.attention = Attention(self.alive.get("ignorer") or (), reglages=self.reglages)
        self.life = Life(reglages=self.reglages)
        self.steps = []             # le geste en cours : [(heure, pose), …]
        self.pitch = 0.0            # tangage du regard (radians), comme `facing` pour le lacet
        self.settled = 0.0          # heure où la tête aura fini de bouger (+ SETTLE)
        self.voice_at = -1e9        # dernière fois qu'une voix a tourné la tête
        self.seen_at = -1e9         # dernière fois qu'une personne a été vue
        self.next_ears = 0.0
        self.eyes = None
        if self.alive.get("regard"):
            try:
                import reachy_vue
                self.eyes = reachy_vue.Eyes(self.alive["regard"], every=self.frame_every(),
                                            faces=self.alive.get("visages") or None,
                                            hands=self.gestes_actifs(), reglages=self.reglages)
                self.eyes.names_on = bool(self.reglage("reconnaitre"))
                self.eyes.preuves = GESTES_PREUVES if self.reglage("mains_observer") else None
                self.eyes.cameras = self.alive.get("cameras") if self.reglage("cams_robot") else None
                self.eyes.animaux = self.alive.get("cameras") if self.reglage("cams_robot") and self.reglage("cams_animaux") else None
                self.eyes.exclude = self.on_tv
            except Exception as trouble:
                on_note(f"vue indisponible : {str(trouble)[:120]}")
        if self.reglages.rejetes:
            on_note("réglages ignorés (valeur hors bornes) : " + ", ".join(self.reglages.rejetes))
        self.fichier = Path(fichier) if fichier else None
        threading.Thread(target=self.worker, daemon=True).start()
        if self.fichier is not None:
            threading.Thread(target=self.watch, daemon=True).start()
        self.page = None
        if self.alive.get("page"):
            try:
                import reachy_page
                self.page = reachy_page.Page(self, self.alive["page"])
            except Exception as trouble:        # adresse absente, port pris : le corps vit sans sa page
                self.on_note(f"page de réglages indisponible : {str(trouble)[:120]}")

    def gestes_actifs(self):
        """Le détecteur de gestes tourne : pour y répondre (`mains`) ou pour les observer sans réagir (11/10)."""
        return bool(self.alive.get("mains") or self.reglage("mains_observer"))

    def reglage(self, cle):
        """Un réglage du corps, dans l'unité du code (`reachy_reglages`) : le fichier, sinon la constante."""
        return self.reglages(cle)

    def watch(self):
        """Un fil à part (la boucle du corps garde ses cadences) : le fichier de réglages a changé (la page,
        ou une édition à la main) → son contenu part dans la file, appliqué par `apply_settings`."""
        def stamp():
            try:
                info = self.fichier.stat()
                return info.st_mtime_ns, info.st_size
            except OSError:
                return None
        seen, broken = stamp(), None
        while self.running:
            time.sleep(RELIRE_EVERY)
            now = stamp()
            if now == seen:
                continue
            seen = now
            try:
                content = reachy_reglages.lire(self.fichier)
            except ValueError as trouble:            # erreur de frappe à la main : on garde les réglages d'avant
                if str(trouble) != broken:
                    self.on_note(f"réglages illisibles, rien changé : {str(trouble)[:120]}")
                broken = str(trouble)
                continue
            broken = None
            self.inbox.put(("reglages", content))

    def apply_settings(self, content):
        """Applique à chaud le contenu du fichier : seules les clés du schéma changent. Dans la boucle du corps."""
        alive = {k: v for k, v in self.alive.items() if k not in reachy_reglages.RACINES}
        alive.update({k: v for k, v in content.items() if k in reachy_reglages.RACINES})
        changed = [k for k in reachy_reglages.RACINES if self.alive.get(k) != alive.get(k)]
        if not changed:
            return []
        self.alive = alive
        self.reglages.charger(alive)
        try:
            self.attention.ignore = [tuple(sorted(r)) for r in reachy_reglages.valider("ignorer", alive.get("ignorer") or [])]
        except ValueError:
            pass                                  # directions illisibles : on garde celles d'avant
        self.touch.long = self.on_mute is not None and bool(self.reglage("appui_long"))
        if bool(alive.get("toucher")) != (self.body_touch is not None):
            self.body_touch = BodyTouch(self.reglages) if alive.get("toucher") else None
        self.proprio = (self.proprio or Proprio()) if alive.get("toucher") == "mesure" else None
        if self.eyes is not None:
            self.eyes.every = self.frame_every()
            self.eyes.names_on = bool(self.reglage("reconnaitre"))
            self.eyes.hands_on = self.gestes_actifs()
            self.eyes.preuves = GESTES_PREUVES if self.reglage("mains_observer") else None
            self.eyes.cameras = self.alive.get("cameras") if self.reglage("cams_robot") else None
            self.eyes.animaux = self.alive.get("cameras") if self.reglage("cams_robot") and self.reglage("cams_animaux") else None
        self.forget_touch()
        self.on_note("réglages appliqués sans redémarrer : " + ", ".join(changed)
                     + (f" (ignorés, hors bornes : {', '.join(self.reglages.rejetes)})" if self.reglages.rejetes else ""))
        return changed

    def update(self, state):
        if state == "incompris" and self.reglage("mimique_incompris") == "aucune":
            state = "speaking"                    # pas de mimique : il parle comme d'habitude, en hochant la tête
        self.inbox.put(("state", state))

    def level(self, value):
        try:
            self.voice = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self.voice = 0.0

    def decision(self, behavior):
        if behavior in DECISION:
            self.inbox.put(("decision", behavior))

    def mimer(self, emotion):
        """Une émotion de la bibliothèque Pollen jouée à la demande (bouton « Voir » de la page), par la boucle."""
        self.inbox.put(("mimique", emotion))

    def set_muted(self, muted):
        """Le micro est coupé (ou rétabli) ailleurs : les antennes le montrent."""
        self.inbox.put(("muted", bool(muted)))

    def set_eco(self, eco):
        """Mode éco (nuit, pas de production solaire) : vue et gestes ralentis, dodo plus tôt."""
        self.inbox.put(("eco", bool(eco)))

    def room_presence(self, source="la pièce"):
        """18/10 (constat en test : « il se met à dormir même s'il y a du monde ») : la maison signale
        quelqu'un dans la pièce. Endormi, il a la tête posée : ses yeux ne voient plus la pièce, donc seuls
        une voix ou un toucher pouvaient encore le réveiller. Appelé depuis un autre fil : le travail se
        fait dans la boucle du corps. Alison (bureau) ne l'appelle pas, rien ne change pour elle."""
        self.inbox.put(("presence", str(source)))

    def on_tv(self, c):
        """Un visage vu dans le secteur ignoré (la télé) ne compte pas."""
        import reachy_vue
        return self.attention.ignored(math.degrees(self.facing + reachy_vue.angles(c)[0]))

    def antenna_degrees(self):
        """Témoin du micro : dressées quand elle écoute, baissées s'il est coupé, au repos sinon."""
        if self.state == "listening":
            return ANTENNA_LISTEN
        return self.reglage("antenna_mute") if self.muted else self.reglage("antenna_rest")

    def antennas(self, extra=0.0):
        degrees = math.radians(self.antenna_degrees() + extra)
        return (-degrees, degrees)

    def frame_every(self):
        if self.asleep:
            return DOZE_EVERY
        if self.eco:
            return ECO_EVERY
        return 1.0 / self.reglage("fps")             # reachy_vue.FRAME_EVERY sans réglage

    def dodo_after(self):
        """Secondes sans présence avant de dormir, ou None (dodo coupé)."""
        minutes = self.alive.get("eco") if self.eco and self.alive.get("eco") else self.alive.get("dodo")
        try:
            return float(minutes) * 60 if minutes and float(minutes) > 0 else None
        except (TypeError, ValueError):
            return None

    def close(self):
        self.running = False
        if self.page is not None:
            self.page.close()
        if self.eyes:
            self.eyes.close()
        self.inbox.put(("stop", None))

    def attempt(self, action, *args, force=False):
        if not force and time.monotonic() < self.waking_until:
            return bool(self.reachable)        # le réveil de Pollen se joue : on ne l'interrompt pas
        try:
            if not self.enabled:
                self.robot.enable()
                self.enabled = True
            action(*args)
            ok = True
        except Exception:
            self.enabled = False
            ok = False
        if ok != self.reachable:
            self.reachable = ok
            self.on_reach(ok)
        return ok

    def show(self, gesture):
        rest = self.antennas()
        if gesture == "@neutre":
            self.attempt(lambda: (self.robot.stop(), self.robot.pose(antennas=rest, duration=1.0)))
        elif gesture == "@parole":
            # Retour au neutre en douceur : un `set_target` direct depuis la fin d'une émotion faisait
            # sauter la tête (pic mesuré à 1178, le seuil de coupure de parole est 1200). Le neutre
            # garde la direction de celui qui parle.
            self.attempt(lambda: (self.robot.stop(), self.robot.pose(yaw=self.facing, antennas=rest, duration=BLEND)))
        elif gesture == "@incompris":                # la mimique « pas compris » choisie dans la page
            self.attempt(self.robot.emotion, self.reglage("mimique_incompris"))
        elif gesture:
            self.attempt(self.robot.emotion, gesture)

    def streaming(self, now):
        """Faut-il envoyer des poses en continu ? Pendant la parole, et la respiration du repos."""
        return self.state == "speaking" and now - self.since >= BLEND

    def resting(self, now):
        """Au repos depuis moins de BREATH_SECONDS : le lent hochement continue — sauf pendant un
        geste, ou quand elle regarde quelqu'un (le regard prend la tête)."""
        return (self.state == "idle" and now - self.since < self.reglage("breath_seconds") and not self.steps
                and not self.attending(now) and not self.asleep and not self.in_measure_mode(now))

    def living(self):
        return (self.state == "idle" and self.reachable is not False and not self.in_measure_mode()
                and bool(self.alive.get("gestes") or self.alive.get("voix") or self.eyes or self.dodo_after()))

    def attending(self, now):
        return now - self.voice_at < VOICE_HOLD or now - self.seen_at < self.reglage("track_lost")

    def look(self, pitch, yaw, roll=0.0, antennas=0.0, duration=None, now=None):
        """Un `goto` borné vers (tangage, lacet) en radians ; la durée suit l'amplitude (≤ 60°/s)."""
        limit = math.radians(self.reglage("face_limit"))
        yaw = max(-limit, min(limit, yaw))
        pitch = max(math.radians(TRACK_PITCH[0]), min(math.radians(TRACK_PITCH[1]), pitch))
        if duration is None:
            duration = max(0.5, min(1.5, math.degrees(max(abs(yaw - self.facing), abs(pitch - self.pitch))) / 60.0))
        now = time.monotonic() if now is None else now
        self.settled = now + duration + SETTLE
        # Les antennes vont bouger : l'ancienne référence du toucher ne vaut plus. Sans ça, au démarrage
        # (référence prise antennes REPLIÉES, robot couché), le premier regard qui les déplie était lu
        # comme une antenne tenue → faux « appui long », micro coupé (10/10, 14:52 ; déjà vu le 10/10 à 01:03).
        self.forget_touch()
        if not self.steps and not (roll or antennas):
            self.facing, self.pitch = yaw, pitch      # un regard, pas l'étape d'un geste
        return self.attempt(self.robot.pose, pitch, yaw, math.radians(roll), self.antennas(antennas), duration)

    def live(self, now):
        """Un tour du comportement vivant, au repos. Priorités : le sommeil, le geste en cours, une voix,
        une personne vue, le retour au centre, l'endormissement, un nouveau geste."""
        if self.asleep:
            self.doze(now)
            return
        if self.steps:
            at, step = self.steps[0]
            if now >= at:
                self.steps.pop(0)
                pitch, yaw, roll, antennas, duration = step
                self.look(self.pitch + math.radians(pitch), self.facing + math.radians(yaw), roll, antennas, duration, now)
                if self.steps:
                    self.steps[0] = (now + duration, self.steps[0][1])
                else:
                    self.forget_touch()             # les antennes ont bougé : nouvelle référence
            return
        if now < self.settled:
            return
        if self.alive.get("voix") and self.ears is not None and self.ears.device is not None and now >= self.next_ears:
            self.next_ears = now + EARS_EVERY
            heard = self.ears.read()
            if heard and heard[1]:
                yaw = facing_for(heard[0], self.facing, self.reglage("face_limit"))
                self.heard = (now, math.degrees(yaw))          # pour la page (repère du socle)
                if not self.attention.ignored(math.degrees(yaw)):
                    self.presence_at = now
                target = self.attention.hear(math.degrees(yaw), now)
                if target is not None:
                    speaker = self.speaker(target, now)
                    if speaker is not None:
                        c, face_yaw, face_pitch = speaker
                        self.on_note(f"voix à {target:+.0f}° : c'est la personne à "
                                     f"{math.degrees(self.facing + face_yaw):+.0f}° qui parle, je la regarde")
                        self.prefer(c, now, now + VOICE_HOLD)
                        self.seen_at = now
                        self.look(self.pitch + face_pitch, self.facing + face_yaw, now=now)
                        return
                    self.on_note(f"voix à {target:+.0f}° : je regarde")
                    self.sense("voix", now)
                    self.voice_at = now
                    self.look(self.pitch, math.radians(target), now=now)
                    if self.eyes is not None:          # une fois tournée : le visage au centre est celui qui parle
                        self.prefer((0.0, 0.0), self.settled, self.settled + VOICE_HOLD + 2.0)
                    return
        if self.eyes is not None:
            seen = self.eyes.latest()
            if seen and len(seen) > 3 and seen[3] and now - seen[0] <= self.fresh():
                self.presence_at = now
            self.recognize()
            self.voir_autres(now)
            self.voir_animal(now)
            self.gestures(now)
        # « Suivre une personne du regard » coupé (11/10) : la vue sert encore (présence, noms, gestes),
        # seule la tête ne la suit plus.
        if self.eyes is not None and now - self.voice_at >= VOICE_HOLD and self.reglage("suivre"):
            seen = self.eyes.latest()
            if seen and seen[1] is not None and seen[0] >= self.settled and now - seen[0] <= self.fresh():
                import reachy_vue
                if now - self.seen_at >= self.reglage("track_lost"):
                    self.on_note("quelqu'un est là : je le suis du regard")
                self.seen_at = now
                yaw, pitch = reachy_vue.angles(seen[1])
                if max(abs(math.degrees(yaw)), abs(math.degrees(pitch))) >= self.reglage("track_dead"):
                    gain = self.reglage("track_gain")
                    self.look(self.pitch + gain * pitch, self.facing + gain * yaw, now=now)
                    return
        # Retour au centre : seulement après TRACK_LOST secondes tête IMMOBILE sans voir personne — à
        # la fin d'un geste, les yeux n'ont pas encore eu d'image stable (recette du 09/10 : la tête
        # revenait au centre après chaque geste, puis retrouvait la personne).
        if (not self.attending(now) and now - self.settled >= self.reglage("track_lost")
                and (abs(self.facing) > 1e-3 or abs(self.pitch) > 1e-3)):
            self.attention.forget()
            self.look(0.0, 0.0, now=now)
            self.facing = self.pitch = 0.0
            return
        delay = self.dodo_after()
        if delay and now - self.presence_at >= delay:
            self.fall_asleep(now, delay)
            return
        if self.alive.get("gestes"):
            gesture = self.life.due(now, self.mood)
            if gesture and self.eco and self.life.chance.random() > 1.0 / self.reglage("eco_life"):
                gesture = None                     # éco : un geste sur ECO_LIFE
            if gesture:
                name, steps = gesture
                humeur = "" if self.mood is None or self.mood.neutral(now) else f" (humeur : {self.mood.label(now)})"
                self.on_note(f"petit geste : {name}{humeur}")
                self.steps = [(now, step) for step in steps]

    def prefer(self, c, not_before, until):
        prefer = getattr(self.eyes, "prefer", None)
        if prefer is not None:
            prefer(c, not_before, until)

    def fresh(self):
        """Âge maximal d'une image qu'on croit encore (la vue peut être ralentie)."""
        return max(TRACK_FRESH, 1.5 * getattr(self.eyes, "every", 0.0))

    def speaker(self, target, now):
        """Le visage vu dans la direction de la voix `target` (degrés, repère du socle) : (centre,
        lacet, tangage) relatifs à la caméra, ou None. Seulement une image prise tête immobile."""
        if self.eyes is None:
            return None
        seen = self.eyes.latest()
        if not seen or len(seen) < 4 or seen[0] < self.settled or now - seen[0] > self.fresh():
            return None
        import reachy_vue
        best = None
        for c in seen[3]:
            yaw, pitch = reachy_vue.angles(c)
            gap = abs(math.degrees(self.facing + yaw) - target)
            if gap <= SPEAKER_MATCH and (best is None or gap < best[0]):
                best = (gap, c, yaw, pitch)
        return best[1:] if best else None

    def sense(self, event, now):
        """Un événement pousse l'humeur (`MOOD_EVENTS`) ; rien sans humeur."""
        if self.mood is not None:
            self.mood.feel(event, now)

    def awareness(self, now, mood=None):
        """Ce qu'elle fait, regarde, ressent — tous ses sens réunis en une phrase (10/10, besoin initial : « il a la vue,
        l'ouïe, le suivi, l'empreinte visage et voix, donc il saura ce qu'il fait, regarde ou entend »).
        `mood` : une copie de l'humeur (`Mood.peek`) quand la phrase est lue par la page, dans un autre fil."""
        mood = self.mood if mood is None else mood
        lost = 2 * self.reglage("track_lost")
        parts = []
        if self.asleep:
            parts.append("Je dors.")
        else:
            parts.append({"listening": "J'écoute.", "thinking": "Je réfléchis.",
                          "speaking": "Je parle.", "incompris": "Je n'ai pas compris."}.get(self.state, ""))
            if self.person not in (None, "inconnu") and now - self.seen_at < lost:
                parts.append(f"Je regarde {self.person.capitalize()}.")
            elif self.person == "inconnu":
                parts.append("Je regarde quelqu'un que je ne connais pas.")
            elif now - self.seen_at < lost:
                parts.append("Je vois quelqu'un et je le suis du regard.")
            elif now - self.voice_at < 10.0:
                parts.append("J'ai entendu une voix et je me suis tourné vers elle.")
            if self.steps:
                parts.append("Je fais un petit geste.")
        if mood is not None and not mood.neutral(now):
            parts.append(f"Je me sens {mood.label(now)}.")
        if self.last_gesture is not None and now - self.last_gesture[0] < 300:
            minutes = int((now - self.last_gesture[0]) // 60)
            parts.append(self.last_gesture[1] + (" à l'instant." if minutes < 1 else
                                                 f" il y a {minutes} minute{'s' if minutes > 1 else ''}."))
        if self.last_felt is not None and now - self.last_felt[0] < 600:
            minutes = int((now - self.last_felt[0]) // 60)
            parts.append(self.last_felt[1] + (" à l'instant." if minutes < 1 else
                                              f" il y a {minutes} minute{'s' if minutes > 1 else ''}."))
        return " ".join(p for p in parts if p)[:250]

    def tell(self, now):
        """Publie la conscience quand elle change, au plus une fois toutes les AWARE_EVERY secondes."""
        if self.on_aware is None or now - self.aware_at < AWARE_EVERY:
            return
        text = self.awareness(now)
        if text != self.aware:
            self.aware, self.aware_at = text, now
            try:
                self.on_aware(text)
            except Exception as trouble:
                self.on_note(f"on_aware : {str(trouble)[:120]}")

    def gestures(self, now):
        """Un geste vu par la vue (`mains`) : coucou → content (geste silencieux) ; main levée → `on_gesture`
        (machine du robot : il écoute). Une fois par geste."""
        g = getattr(self.eyes, "gesture", None)
        if g is None or g is self.gesture_seen:
            return
        self.gesture_seen = g
        kind, side = g[0], g[1]
        delai = f", vu en {g[3]:.1f} s" if len(g) > 3 and isinstance(g[3], (int, float)) else ""
        if self.reglage("mains_observer"):
            # Observation (11/10) : le geste est noté et gardé par la vue, le robot ne réagit pas.
            self.on_note(f"geste observé, sans réaction : {'coucou' if kind == 'coucou' else 'main levée'} (main {side}{delai})")
            return
        who = self.person if self.person not in (None, "inconnu") else None
        self.presence_at = now
        if kind == "coucou":
            self.on_note(f"on me fait coucou (main {side}{delai})")
            self.sense("coucou", now)
            self.last_gesture = (now, f"{who.capitalize() if who else 'Quelqu’un'} m'a fait coucou")
            if self.state == "idle" and not self.asleep and not self.steps:
                self.steps = [(now, step) for step in GREETING]
        else:
            self.on_note(f"main levée (main {side}{delai}) : on veut me parler")
            self.last_gesture = (now, f"{who.capitalize() if who else 'Quelqu’un'} a levé la main")
        if self.on_gesture:
            try:
                self.on_gesture(kind, who)
            except Exception as trouble:
                self.on_note(f"on_gesture : {str(trouble)[:120]}")

    def voir_autres(self, now=None):
        """11/10 : les AUTRES personnes reconnues en même temps que celle qu'il suit : une ligne de journal par
        personne, une fois par « person_again » (la même mémoire que `recognize`). Pas d'accueil de plus,
        sauf `on_other(nom)` s'il est donné (14/10, machine du robot : accueil par HA, règle des 4 h)."""
        now = time.monotonic() if now is None else now
        for nom in sorted(getattr(self.eyes, "presents", None) or {}):
            if nom == self.person or now - self.announced.get(nom, -1e9) < self.reglage("person_again"):
                continue
            self.announced[nom] = now
            self.on_note(f"je reconnais aussi {nom}")
            if getattr(self, "on_other", None):
                try:
                    self.on_other(nom)
                except Exception as trouble:
                    self.on_note(f"on_other : {str(trouble)[:120]}")

    def voir_animal(self, now=None):
        """11/10 (test local) : la vue a mis un nom sur un animal (étiquette de la rubrique Caméras) : une ligne
        de journal, une fois par « person_again » et par animal, comme pour les personnes."""
        vu = getattr(self.eyes, "animal", None)
        if not vu:
            return
        now = time.monotonic() if now is None else now
        cle = "animal:" + vu[0]
        if now - self.announced.get(cle, -1e9) < self.reglage("person_again"):
            return
        self.announced[cle] = now
        self.on_note(f"je vois {vu[0].replace('-', ' ').capitalize()}")

    def recognize(self, now=None):
        """La vue a mis un nom sur la personne suivie (`visages` dans `alive`) : une ligne de journal et
        `on_person(nom)`. À 3 m le visage clignote (vu, perdu, revu) : une même personne n'est annoncée
        qu'une fois par PERSON_AGAIN secondes."""
        person = getattr(self.eyes, "person", None)
        if person == self.person:
            return
        self.person = person
        if person is None:
            return
        now = time.monotonic() if now is None else now
        if now - self.announced.get(person, -1e9) < self.reglage("person_again"):
            return
        self.announced[person] = now
        known = person != "inconnu"
        if known:
            self.sense("reconnu", now)
        best = getattr(self.eyes, "who_best", None)
        self.on_note(f"je reconnais {person}" if known else "un visage que je ne connais pas"
                     + (f" (meilleure ressemblance {best:.2f})" if isinstance(best, float) else ""))
        if known and self.state == "idle" and not self.asleep and not self.steps:
            self.steps = [(now, step) for step in GREETING]          # content de te voir (silencieux)
        if self.on_person:
            try:
                self.on_person(person)
            except Exception as trouble:
                self.on_note(f"on_person : {str(trouble)[:120]}")

    def fall_asleep(self, now, delay):
        self.on_note(f"personne depuis {delay / 60:.0f} min : je m'endors")
        self.sense("seul", now)
        self.asleep = True
        self.steps = []
        self.attention.forget()
        self.attempt(self.robot.sleep)
        self.enabled = False                 # goto_sleep coupe les moteurs : les rallumer au prochain geste
        self.facing = self.pitch = 0.0
        self.settled = now + 4.0
        self.forget_touch()
        if self.eyes is not None:
            self.eyes.every = self.frame_every()

    def room_seen(self, source, now):
        """Une présence vue par la MAISON (capteur de la pièce), pas par ses yeux : elle repousse le dodo,
        et le réveille s'il dort. → True s'il dormait. La garde horaire est à l'appelant."""
        self.presence_at = now
        if not self.asleep:
            return False
        self.wake(source, now)
        return True

    def wake(self, reason, now=None):
        now = time.monotonic() if now is None else now
        self.on_note(f"{reason} : je me réveille")
        self.asleep = False
        self.attempt(self.robot.wake, force=True)
        self.waking_until = now + WAKE_SETTLE
        self.settled = now + WAKE_SETTLE
        self.presence_at = now
        self.facing = self.pitch = 0.0
        self.attention.forget()
        self.life.postpone(now)
        self.forget_touch()
        if self.eyes is not None:
            self.eyes.every = self.frame_every()

    def doze(self, now):
        """Elle dort : seulement guetter une voix (hors télé) ou un visage."""
        if now < self.settled:
            return
        if self.alive.get("voix") and self.ears is not None and self.ears.device is not None and now >= self.next_ears:
            self.next_ears = now + EARS_EVERY
            heard = self.ears.read()
            if heard and heard[1] and self.attention.hear(math.degrees(facing_for(heard[0], 0.0, self.reglage("face_limit"))), now) is not None:
                self.wake("une voix", now)
                return
        if self.eyes is not None:
            seen = self.eyes.latest()
            if seen and len(seen) > 3 and seen[3] and seen[0] >= self.settled and now - seen[0] <= self.fresh():
                self.wake("quelqu'un", now)

    def turn_to_voice(self):
        """Pendant qu'elle écoute : si la carte entend une parole, tourner la tête vers elle."""
        heard = self.ears.read()
        if not heard or not heard[1]:
            return
        target = facing_for(heard[0], self.facing, self.reglage("face_limit"))
        self.heard = (time.monotonic(), math.degrees(target))
        if abs(math.degrees(target - self.facing)) >= FACE_STEP:
            self.facing = target
            self.attempt(self.robot.pose, 0.0, target, 0.0, self.antennas(), 0.5)

    def self_moving(self, now):
        """Un mouvement qu'ELLE a commandé est en cours ou pas encore stabilisé : tout `goto` (regard, geste,
        hochement) jusqu'à sa fin + SETTLE + BODY_SETTLE, et tout mouvement enregistré (émotion, réveil)."""
        goto = getattr(self.robot, "last_goto", None)
        if goto is not None and now < goto[0] + goto[2] + SETTLE + BODY_SETTLE:
            return True
        return now < getattr(self.robot, "busy_until", 0.0)

    def etat(self, now=None):
        """L'instantané du corps pour la page (11/10, lot 2), en JSON simple. Lu dans le fil de la page : rien
        n'est modifié (humeur par `Mood.peek`), rien n'est demandé au robot ni à la caméra — seulement ce que
        le corps a déjà en mémoire."""
        now = time.monotonic() if now is None else now
        mood = self.mood.peek(now) if self.mood is not None else None

        def age(at):
            return round(now - at, 1)

        seen = self.eyes.latest() if self.eyes is not None else None
        view = None
        if self.eyes is not None:
            view = {"erreur": getattr(self.eyes, "error", ""), "image": getattr(self.eyes, "jpeg", None) is not None,
                    "personne": self.person, "every": round(getattr(self.eyes, "every", 0.0), 2),
                    "presents": sorted(getattr(self.eyes, "presents", None) or {}),
                    "animal": (getattr(self.eyes, "animal", None) or [None])[0]}
            if seen:
                view.update({"age": age(seen[0]), "suivi": list(seen[1]) if seen[1] is not None else None,
                             "visages": [list(c) for c in (seen[3] if len(seen) > 3 else [])]})
        motors = None
        if self.motors_seen is not None:
            at, joints, antennas = self.motors_seen
            motors = {"age": age(at),
                      "corps": round(math.degrees(joints[0]), 1) if joints else None,
                      "tete": [round(math.degrees(v), 1) for v in joints[1:]] if joints else [],
                      "antennes": [round(math.degrees(v), 1) for v in antennas] if isinstance(antennas, list) else []}
        return {
            "joignable": self.reachable, "etat": self.state, "dort": self.asleep, "muet": self.muted, "eco": self.eco,
            "conscience": self.awareness(now, mood),
            "humeur": {"jauges": {k: round(v, 3) for k, v in mood.gauges.items()}, "mot": mood.label(now)} if mood else None,
            "regard": {"lacet": round(math.degrees(self.facing), 1), "tangage": round(math.degrees(self.pitch), 1)},
            "voix": {"angle": round(self.heard[1], 1), "age": age(self.heard[0])} if self.heard else None,
            "toucher": {"texte": self.last_felt[1], "age": age(self.last_felt[0])} if self.last_felt else None,
            "touchers": [list(t) for t in (self.touches or [])],
            "geste": {"texte": self.last_gesture[1], "age": age(self.last_gesture[0])} if self.last_gesture else None,
            "vue": view, "moteurs": motors,
            "journal": [list(line) for line in list(self.journal or [])[:30]],
            "limite": self.reglage("face_limit"),
            "ignorer": [list(r) for r in self.attention.ignore],
        }

    def felt(self, last):
        """Le dernier toucher (heure, phrase) : pour la conscience, et la liste « Derniers touchers » de la page."""
        self.last_felt = last
        if self.touches is not None:
            self.touches.appendleft((time.strftime("%H:%M:%S"), last[1]))

    def forget_touch(self):
        """Les positions ont changé (geste, regard, réveil) : les deux touchers reprennent une référence."""
        self.touch.reset()
        if self.body_touch is not None:
            self.body_touch.reset()

    # --- Le mode mesure (lot 4) : le corps se fige pour qu'un assistant puisse mesurer -----------------------
    def in_measure_mode(self, now=None):
        """Un assistant mesure-t-il ? Vrai jusqu'à `MEASURE_MAX` secondes après l'entrée."""
        now = time.monotonic() if now is None else now
        return bool(self.measure_name) and now < self.measure_until

    def enter_measure_mode(self, name, now=None):
        """Fige le corps pour la mesure `name`. → (True, "") ou (False, la raison du refus en français).
        Refusé si une mesure est déjà en cours, si quelqu'un parle à l’assistant vocal (état ≠ idle), s'il dort ou s'il
        est injoignable. Le corps continue de tourner : seuls les mouvements et les réactions s'arrêtent."""
        now = time.monotonic() if now is None else now
        with self.measure_lock:
            if self.in_measure_mode(now):
                return False, f"une mesure est déjà en cours ({self.measure_name})"
            if self.state != "idle":
                return False, "quelqu'un parle au robot : réessayer quand il est au repos"
            if self.asleep:
                return False, "le robot dort : le réveiller d'abord"
            if self.reachable is False:
                return False, "le robot est injoignable"
            self.measure_name, self.measure_until, self.measure_reason = name, now + MEASURE_MAX, ""
        self.on_note(f"mode mesure : {name}")
        self.inbox.put(("measure", "start"))        # le fil du corps efface le geste en cours
        return True, ""

    def leave_measure_mode(self, reason="terminé"):
        """Lève le mode mesure (sans effet s'il n'y en a pas). → vrai s'il y en avait un."""
        with self.measure_lock:
            name = self.measure_name
            if not name:
                return False
            self.measure_name, self.measure_until, self.measure_reason = "", 0.0, reason
        self.on_note(f"mode mesure levé ({name}) : {reason}")
        self.inbox.put(("measure", "end"))          # le fil du corps reprend ses repères, sans geste immédiat
        return True

    def measure_ready(self, now=None):
        """Le corps est-il vraiment immobile ? (le geste ou le regard commencé avant l'entrée est fini)"""
        now = time.monotonic() if now is None else now
        return self.in_measure_mode(now) and not self.steps and now >= self.settled and not self.self_moving(now)

    def check_measure(self, now):
        """Dans la boucle du corps : le temps est écoulé, ou le robot ne répond plus → on lève le mode."""
        if not self.measure_name:
            return
        if now >= self.measure_until:
            self.leave_measure_mode(f"{MEASURE_MAX / 60:.0f} minutes écoulées")
        elif self.reachable is False or self.asleep:
            self.leave_measure_mode("le robot ne répond plus" if self.reachable is False else "le robot s'est endormi")

    def measure_mode_changed(self, kind, now):
        """Le fil du corps prend acte de l'entrée (`start`) ou de la sortie (`end`) du mode mesure."""
        if kind == "start":
            self.steps = []
            self.attention.forget()
        else:
            self.presence_at = now              # une mesure se fait devant quelqu'un : pas de dodo juste après
            self.life.postpone(now)
            self.gesture_seen = getattr(self.eyes, "gesture", None)   # un geste fait PENDANT la mesure ne déclenche rien
        self.forget_touch()
        if kind == "end" and self.alive and self.state == "idle" and not self.asleep:
            self.look(self.pitch, self.facing, now=now)      # les antennes reprennent leur place

    def foreign_move(self, present, now):
        """15/10 : un mouvement lancé SUR LE DÉMON par un autre que le corps (Home Assistant : geste d'accueil, émotion
        quand l’aspirateur part ou revient) bouge les antennes sans passer par `busy_until` → faux « appui long », micro
        coupé (15/10 08:53, 20:01, 20:55 ; personne n'avait touché le robot). Au premier signe d'appui, on demande au
        démon s'il exécute un mouvement ; si oui, ce n'est pas une main (et FOREIGN_GRACE s de plus, le temps que
        les antennes reviennent). → True si le toucher ne doit pas être jugé maintenant."""
        t = self.touch
        if t.press is None and (t.reference is None or max(abs(math.degrees(p - r)) for p, r in zip(present, t.reference))
                                < self.reglage("touch_press")):
            return False                   # rien qui ressemble à un appui : pas de question au démon
        demander = getattr(self.robot, "moving", None)       # un robot simulé sans `moving` : jamais « en mouvement »
        if demander is None or not demander():
            return False
        try:
            self.robot.busy_until = max(getattr(self.robot, "busy_until", 0.0), now + FOREIGN_GRACE)
        except AttributeError:
            pass
        t.reset()
        return True

    def feel(self, now):
        """Au repos : une antenne poussée du doigt réveille Alison ; avec `toucher`, tout le corps sent."""
        try:
            if self.body_touch is None:
                present = self.robot.call("/api/state/present_antenna_joint_positions")
                self.motors_seen = (now, None, present)          # pour la page : rien de plus n'est lu
            else:
                full = self.robot.call(FULL_STATE) or {}
                present = full.get("antennas_position")
                joints, pose = full.get("head_joints"), full.get("head_pose") or {}
                self.motors_seen = (now, joints, present)
                if self.self_moving(now):
                    self.body_touch.reset()      # son PROPRE mouvement n'est pas une main (fausse alerte du 10/10 23:18)
                elif (isinstance(joints, list) and len(joints) == 7 and not self.resting(now)
                        and all(k in pose for k in ("yaw", "pitch", "roll"))):
                    felt = self.body_touch.update(joints, (pose["yaw"], pose["pitch"], pose["roll"]), now)
                    if felt:
                        self.body_felt(felt, now)
                        return
        except Exception:
            return
        if now < getattr(self.robot, "busy_until", 0.0):
            # Une émotion enregistrée bouge SES antennes : ce n'est pas une main. Sans ça, la mimique jouée
            # au repos depuis la page coupait le micro (« appui long », 11/10 17:55).
            self.touch.reset()
            return
        if not (isinstance(present, list) and len(present) == 2):
            return
        if self.foreign_move(present, now):
            return
        if self.touch.reference is None and not self.asleep and max(abs(math.degrees(p - c)) for p, c in
                                                 zip(present, self.antennas())) > self.reglage("touch_press"):
            return        # éveillée, antennes pas encore où on les a mises : rien à juger (faux appui long, 10/10)
        kind = self.touch.update(present, now)
        if not kind:
            return
        if kind != "long" and not self.reglage("antennes"):
            return                         # « Réagir quand on touche une antenne » coupé (11/10)
        self.presence_at = now
        if kind in ("doux", "brusque"):
            self.sense("caresse" if kind == "doux" else "tape", now)
            self.felt((now, "On m'a caressé une antenne" if kind == "doux" else "On m'a tapé une antenne"))
        if self.asleep:                    # endormie, TOUT mouvement d'antenne la réveille, jamais le micro :
            self.wake("on me touche", now)  # un réveil par Home Assistant (bouton Wake up, 10/10 17:55) bouge
            if kind != "long":             # aussi les antennes, et coupait le micro en douce
                self.on_touch(kind)
            return
        if kind == "long":                 # le bouton : micro coupé / rétabli (éveillée seulement)
            self.muted = not self.muted
            self.on_note("appui long : micro " + ("coupé" if self.muted else "rétabli"))
            if not self.asleep:
                self.look(self.pitch, self.facing, now=now)
            self.forget_touch()
            self.on_mute(self.muted)
            return
        if self.reglage("toucher_son"):    # l'ancien comportement, à la demande : émotion enregistrée (sonore)
            self.show(TOUCH_REACTION[kind])
        elif not self.steps:               # 11/10 toucher silencieux : un geste de la bibliothèque, sans son
            self.steps = [(now, step) for step in TOUCH_GESTE[kind]]
        self.on_touch(kind)

    def measure(self, now):
        """Mesure (10/10) : l'écart entre la tête réelle et celle attendue, même en mouvement, pour régler le
        toucher. Une ligne JSON par mesure dans PROPRIO_LOG (tmpfs, tronqué à PROPRIO_LINES)."""
        try:
            full = self.robot.call(FULL_STATE) or {}
            pose = full.get("head_pose") or {}
            present = (pose["yaw"], pose["pitch"], pose["roll"])
        except Exception:
            return
        goto = getattr(self.robot, "last_goto", None)
        expected = self.proprio.expected(goto, now)
        self.proprio.present = present
        if expected is None:
            return
        line = {"t": round(now, 2), "bouge": self.proprio.moving(goto, now),
                "occupe": now < getattr(self.robot, "busy_until", 0.0), "pas": bool(self.steps),
                "ecart": [round(math.degrees(a - b), 2) for a, b in zip(present, expected)],
                "corps": round(math.degrees(full.get("body_yaw") or 0.0), 2),
                "moteurs": [round(math.degrees(v), 2) for v in (full.get("head_joints") or [])]}
        try:
            if PROPRIO_LOG.exists() and PROPRIO_LOG.stat().st_size > PROPRIO_LINES * 200:
                PROPRIO_LOG.unlink()
            with PROPRIO_LOG.open("a") as f:
                f.write(json.dumps(line) + "\n")
        except OSError:
            pass

    def body_felt(self, felt, now):
        """Une main sur la tête ou le corps. Endormie : elle se réveille. Une caresse : content (sans son).
        Poussée ou tournée : elle le note, puis reprend sa posture (la tête reste où on l'a mise)."""
        part, how = felt
        self.presence_at = now
        self.felt((now, "On m'a caressé la tête" if how == "caresse" else
                   "On m'a tourné le corps" if part == "corps" else f"On m'a poussé la tête ({how})"))
        if self.asleep:
            self.wake("on me touche", now)
            return
        if how == "caresse":
            self.on_note("on me caresse la tête")
            self.sense("caresse", now)
            if not self.steps:
                self.steps = [(now, step) for step in GREETING]
            return
        self.on_note("on me tourne le corps" if part == "corps" else f"on me pousse la tête : {how}")
        self.sense("contact", now)
        self.look(self.pitch, self.facing, now=now)          # reprendre sa posture

    def nod_at(self, now):
        """Le demi-cycle de hochement à lancer maintenant : (tangage en radians, durée)."""
        half = int((now - self.since) // NOD_HALF)
        nod = self.reglage("nod_pitch")
        return math.radians(nod if half % 2 == 0 else -nod), NOD_HALF

    def pose_at(self, now):
        """La pose de parole du moment : le balancement de Pollen. Pure, testable sans robot."""
        t = now - self.since
        target = self.voice if self.voice > 0.05 else 0.0
        step = TICK / (ATTACK if target > self.envelope else RELEASE)
        self.envelope += (target - self.envelope) * min(1.0, step)
        g = self.envelope * self.reglage("sway_master")
        wave = {axis: amp * g * math.sin(2 * math.pi * freq * t + self.phase[axis])
                for axis, (freq, amp) in SWAY.items()}
        head = {"x": wave["x"], "y": wave["y"], "z": wave["z"], "roll": math.radians(wave["roll"]),
                "pitch": math.radians(wave["pitch"]), "yaw": self.facing + math.radians(wave["yaw"])}
        return head, self.antennas()

    def worker(self):
        next_nod = 0.0
        while self.running:
            now = time.monotonic()
            if self.reachable is False:
                wait = RETRY if self.alive and self.state == "idle" else None
            elif self.streaming(now):
                wait = TICK
            elif self.state == "speaking":
                # Le retour en douceur avant le balancement : se réveiller à sa fin. Sans minuterie, la
                # boucle dormait jusqu'au message suivant et la tête restait figée toute la phrase
                # (recette du 09/10 : le volume de la voix ne passe pas par la file).
                wait = max(0.01, self.since + BLEND - now)
            elif self.state == "listening" and self.ears and self.ears.device is not None:
                wait = EARS_EVERY
            elif self.resting(now):
                wait = max(0.05, next_nod - now)
            else:
                wait = None
            if self.measure_name:                      # le mode mesure se lève à l'heure, même au calme
                left = max(0.05, self.measure_until - now)
                wait = left if wait is None else min(wait, left)
            if self.on_touch and self.state == "idle" and self.reachable is not False:
                wait = TOUCH_EVERY if wait is None else min(wait, TOUCH_EVERY)
            if self.living():
                wait = ALIVE_EVERY if wait is None else min(wait, ALIVE_EVERY)
            try:
                kind, value = self.inbox.get(timeout=wait)
            except queue.Empty:
                kind, value = None, None
            if kind == "stop":
                break
            if kind == "muted" and value != self.muted:
                self.muted = value
                if self.state == "idle" and not self.asleep and not self.in_measure_mode(now):
                    self.look(self.pitch, self.facing)
                    self.forget_touch()
            elif kind == "eco" and value != self.eco:
                self.eco = value
                self.on_note("mode éco " + ("activé" if value else "terminé"))
                if self.eyes is not None:
                    self.eyes.every = self.frame_every()
            elif kind == "state" and value != self.state:
                previous = self.state
                if value != "idle" and self.measure_name:
                    self.leave_measure_mode("quelqu'un parle au robot")
                if value == "listening" and previous not in QUIET_AFTER:
                    self.sense("conversation", time.monotonic())
                if value != "idle":
                    self.presence_at = time.monotonic()
                    if self.asleep:
                        self.wake("on me parle")
                self.state, self.since, self.envelope = value, time.monotonic(), 0.0
                self.phase = {axis: random.uniform(0, 2 * math.pi) for axis in SWAY}
                if value == "idle":
                    self.facing = self.pitch = 0.0
                if self.alive:                     # un geste ou un regard de repos s'arrête là
                    self.steps = []
                    self.attention.forget()
                    self.life.postpone(time.monotonic())
                self.forget_touch()
                listens = value == "listening" and self.ears is not None and self.ears.device is not None
                # Avec des oreilles, écouter = se tourner vers la voix : pas d'émotion qui fige la tête.
                if not (value == "listening" and (previous in QUIET_AFTER or listens)):
                    self.show(REFLECT.get(value, ""))
                elif listens:                      # pas d'émotion : les antennes se dressent (micro ouvert)
                    self.attempt(self.robot.pose, 0.0, self.facing, 0.0, self.antennas(), 0.3)
                next_nod = time.monotonic() + 1.0          # le neutre d'abord, puis le hochement
            elif kind == "decision":
                self.show(DECISION[value])
            elif kind == "mimique":
                if value != "@neutre":
                    self.show(value)
                    # Jouée au repos (page) : rien d'autre ne la ramène au neutre, antennes comprises.
                    retour = threading.Timer(RECORDED_MOVE, self.inbox.put, args=(("mimique", "@neutre"),))
                    retour.daemon = True
                    retour.start()
                elif self.state == "idle" and not self.asleep:
                    self.show("@neutre")
            elif kind == "reglages":
                self.apply_settings(value)
            elif kind == "presence":
                self.room_seen(value, time.monotonic())
            elif kind == "measure":
                self.measure_mode_changed(value, time.monotonic())
            now = time.monotonic()
            self.check_measure(now)
            if kind is None and self.state == "listening" and self.ears is not None and self.reglage("tourner_ecoute"):
                self.turn_to_voice()
            if (kind is None and self.on_touch and self.state == "idle" and now - self.since >= TOUCH_GRACE
                    and not self.steps and now >= self.settled + TOUCH_GRACE and not self.in_measure_mode(now)):
                self.feel(now)
            if kind is None and self.streaming(now):
                head, antennas = self.pose_at(now)
                self.attempt(self.robot.target, head, antennas)
            elif kind is None and self.resting(now) and now >= next_nod:
                pitch, duration = self.nod_at(now)
                self.attempt(self.robot.pose, self.pitch + pitch, self.facing, 0.0, self.antennas(), duration)
                next_nod = now + duration
            if kind is None:
                self.tell(now)
            if kind is None and self.proprio is not None and self.state == "idle" and now >= self.next_proprio:
                self.next_proprio = now + TOUCH_EVERY
                self.measure(now)
            if kind is None and self.living():
                self.live(time.monotonic())
            elif kind is None and self.reachable is False and self.alive and self.state == "idle":
                self.attempt(lambda: None)        # réactive les moteurs : `on_reach(True)` s'il répond


def cmd_tester():
    url = load_url()
    if not url:
        print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.reachy.0"))
        return 1
    try:
        status = Robot(url).status() or {}
    except Exception as trouble:
        print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.6", url=url, reason=str(trouble)[:120]))
        return 1
    backend = status.get("backend_status") or {}
    motors = backend.get("motor_control_mode", "?")
    if status.get("state") != "running" or not backend.get("ready"):
        print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.7", state=status.get("state", "?")))
        return 1
    print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.8", name=status.get("robot_name", "robot"), version=status.get("version", ""), motors=motors).strip())
    return 0


def camera():
    """Le /dev/videoN de la caméra du robot, s'il est branché SUR CETTE machine (le numéro change
    selon les branchements). Le nœud d'index 0 est celui qui donne les images."""
    for node in sorted(Path("/sys/class/video4linux").glob("video*")):
        try:
            if "Reachy Mini" in (node / "name").read_text() and (node / "index").read_text().strip() == "0":
                return "/dev/" + node.name
        except OSError:
            continue
    return ""


def cmd_regarder():
    """Une photo 1280×720 MJPEG. Jamais la pleine résolution YUYV : elle fige la caméra (09/10)."""
    device = camera()
    if not device:
        print("caméra du robot introuvable ici (robot débranché, ou branché sur une autre machine)")
        return 1
    VIEW.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    VIEW.parent.chmod(0o700)
    temporary = VIEW.with_suffix(".tmp.jpg")
    try:
        done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2",
                               "-input_format", "mjpeg", "-video_size", "1280x720", "-i", device,
                               "-frames:v", "1", "-update", "1", "-y", str(temporary)],
                              capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        temporary.unlink(missing_ok=True)
        print("la caméra du robot ne répond pas (débrancher et rebrancher le robot)")
        return 1
    if done.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        print("photo ratée : " + (done.stderr or b"").decode(errors="replace").strip()[:160])
        return 1
    temporary.chmod(0o600)
    temporary.replace(VIEW)
    print(VIEW)
    return 0


def library(robot, dataset):
    """Les noms d'une bibliothèque de Pollen, lus sur le service du robot : la liste fermée."""
    names = robot.call(f"/api/move/recorded-move-datasets/list/{dataset}") or []
    return [str(name) for name in names if isinstance(name, str)]


def cmd_gestes():
    url = load_url()
    if not url:
        print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.reachy.0"))
        return 1
    try:
        robot = Robot(url)
        print("émotions : " + ", ".join(library(robot, EMOTIONS)))
        print("danses : " + ", ".join(library(robot, DANCES)))
    except Exception as trouble:
        print(f"robot injoignable : {str(trouble)[:120]}")
        return 1
    return 0


def cmd_jouer(dataset, name):
    """Joue un mouvement de la liste FERMÉE, puis attend qu'il soit fini : sinon le reflet (elle se
    met à parler) l'interromprait au milieu."""
    url = load_url()
    if not url:
        print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.reachy.0"))
        return 1
    try:
        robot = Robot(url)
        names = library(robot, dataset)
        if not name:
            name = random.choice(names) if names else ""
        if name not in names:
            print(f"« {name} » n'existe pas. Choix : " + ", ".join(names))
            return 1
        robot.enable()
        robot.play(dataset, name)
        end = time.monotonic() + GESTURE_MAX
        time.sleep(0.5)
        while time.monotonic() < end and robot.call("/api/move/running"):
            time.sleep(0.3)
    except Exception as trouble:
        print(f"robot injoignable : {str(trouble)[:120]}")
        return 1
    print(f"fait : {name}")
    return 0


def main(argv):
    verb = argv[0] if argv else ""
    if verb in ("", "-h", "--help", "aide"):
        print(__doc__)
        return 0
    if verb not in VERBS:
        print("verbe inconnu : %s (%s)" % (verb, ", ".join(VERBS)), file=sys.stderr)
        return 2
    rest = [a for a in argv[1:] if a]
    if verb == "regarder":
        return cmd_regarder()
    if verb == "gestes":
        return cmd_gestes()
    if verb == "emotion":
        return cmd_jouer(EMOTIONS, rest[0] if rest else "-")
    if verb == "danse":
        return cmd_jouer(DANCES, rest[0] if rest else "")
    return cmd_tester()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
