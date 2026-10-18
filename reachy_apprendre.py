#!/usr/bin/env python3
"""L'apprentissage : apprendre au robot un visage et une voix, depuis la page (11/10/2026).

Besoin initial (11/10, après une reconnaissance manquée le matin) : « une page dédiée à l'apprentissage,
visage et vocal, l'UI full local ». Tout se passe dans le robot : aucune photo, aucun son n'est gardé, seulement
des empreintes (des nombres), et la page ne reçoit que des noms, des dates, des compteurs et des scores.

- PLUSIEURS SÉANCES par personne : `<nom>.json` = {"nom", "modele", <compteur>, "empreinte", "seances": [{"id",
  "le", "moment", <compteur>, "empreinte"}]}. `empreinte` (la moyenne des séances, pondérée par leur compteur)
  reste là pour ce qui ne lit qu'elle (le pont de la voix) ; la vue, elle, garde la MEILLEURE ressemblance des
  séances (`reachy_vue.load_print_sets`) : une séance du soir et une du matin couvrent les deux lumières.
  Un ancien fichier sans `seances` compte pour une séance « d'origine ».
- Visage : une séance GUIDÉE (`POSES`, quelques images par pose), puis la vérification (le robot reconnaît-il
  la personne ?). En direct, `vue()` analyse la DERNIÈRE image déjà reçue par la vue (aucun appel de plus à la
  caméra) : cadre, netteté, taille, lumière, conseil, ressemblances.
- Voix : `PHRASES` lues une par une devant le micro du robot (`alive["micro"]`), le corps FIGÉ (mode mesure :
  le bruit des moteurs ne se mêle pas à la voix). Chaque phrase est découpée par l'énergie (bruit de fond mesuré
  d'abord), refusée si trop courte, trop faible ou saturée, puis réduite à son empreinte CAM++ (le modèle du
  pont, `campplus.onnx` à côté du dossier des empreintes). Même préparation que le pont (`amplifier`).
- L'accord daté reste obligatoire (celui de `reachy_personnes`, la même fiche) ; une séance ratée ou annulée
  ne garde rien, pas même l'accord qu'elle venait de noter.

Facultatif : sans caméra, sans micro ou sans modèle de voix, la partie concernée est grisée, le reste marche.
"""
import json
import os
import struct
import subprocess
import threading
import time
import uuid
from pathlib import Path

import reachy_personnes
from reachy_personnes import Refus, nom_sur

PREFIXE = "/api/apprendre"
RATE = 16000
POSES = [("face", "Regardez le robot, de face."),
         ("gauche", "Tournez un peu la tête vers votre gauche."),
         ("droite", "Tournez un peu la tête vers votre droite."),
         ("haut", "Levez un peu le menton."),
         ("bas", "Baissez un peu le menton, en regardant le robot.")]
IMAGES_PAR_POSE = 4
PAUSE_POSE = 3.0            # secondes pour lire la consigne avant chaque pose
ENTRE_IMAGES = 0.6
VUES_MIN = 8                # vues nettes au moins sur toute la séance
# Pas de « Alison » dans les phrases : le mot d'éveil réveillerait l'assistant pendant l'apprentissage.
PHRASES = ["Allume la lumière du salon, s'il te plaît.",
           "Ouvre les volets du salon.",
           "Quel temps fera-t-il demain matin ?",
           "Mets un peu de musique douce dans le salon.",
           "Éteins la télé et ferme les volets de la chambre.",
           "Bonjour, comment ça va ce matin ?",
           "Rappelle-moi de sortir le chien à dix-huit heures.",
           "Baisse un peu le chauffage du bureau."]
PHRASES_MIN = 5             # phrases réussies pour enregistrer une séance de voix
SEANCES_MAX = 8             # au-delà, la plus ancienne est retirée
VOIX_SEUIL, VOIX_ECART = 0.62, 0.15      # la règle du pont (10/10 21 h), pour l'essai « Qui parle ? »
# Découpage d'une phrase (trames de 30 ms) : parole = énergie au-dessus de PAROLE × le bruit de fond.
TRAME = 480
PAROLE, PAROLE_MIN_RMS = 3.0, 250.0
FIN_SILENCE = 0.9           # secondes de silence qui terminent la phrase
VOIX_MIN, VOIX_MAX = 1.2, 9.0            # secondes de parole
ATTENTE_MAX = 20.0          # secondes sans parole : « pas entendu »
PIC_MIN, SATURE = 1500, 32000
ABANDON = 900.0             # secondes : une séance laissée en plan ne bloque plus les suivantes


def moment(heure=None):
    """Le moment de la journée d'une séance (la lumière n'est pas la même)."""
    h = time.localtime().tm_hour if heure is None else heure
    return "nuit" if h < 6 or h >= 22 else "matin" if h < 12 else "après-midi" if h < 18 else "soir"


def _horodatage(secondes=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(secondes))


# --- les fichiers d'empreintes à séances -----------------------------------------------------------------
def lire_seances(chemin, compteur):
    """Les séances d'un fichier d'empreintes ; un ancien fichier (une seule empreinte) = une séance « origine »."""
    chemin = Path(chemin)
    if not chemin.is_file():
        return []
    try:
        donnees = json.loads(chemin.read_text())
    except (OSError, ValueError):
        return []
    seances = donnees.get("seances")
    if isinstance(seances, list) and seances:
        return [s for s in seances if isinstance(s, dict) and isinstance(s.get("empreinte"), list)]
    if isinstance(donnees.get("empreinte"), list):
        return [{"id": "origine", "le": _horodatage(chemin.stat().st_mtime), "moment": "",
                 compteur: donnees.get(compteur) if isinstance(donnees.get(compteur), int) else 0,
                 "empreinte": donnees["empreinte"]}]
    return []


def ecrire_seances(chemin, nom, modele, compteur, seances):
    """Réécrit le fichier : les séances (les SEANCES_MAX plus récentes) et leur moyenne pondérée. Rien = effacé."""
    chemin = Path(chemin)
    seances = seances[-SEANCES_MAX:]
    if not seances:
        chemin.unlink(missing_ok=True)
        return
    taille = len(seances[0]["empreinte"])
    somme, poids = [0.0] * taille, 0
    for s in seances:
        w = max(1, int(s.get(compteur) or 1))
        somme = [a + w * float(b) for a, b in zip(somme, s["empreinte"])]
        poids += w
    norme = sum(x * x for x in somme) ** 0.5 or 1.0
    donnees = {"nom": nom, "modele": modele, compteur: sum(int(s.get(compteur) or 0) for s in seances),
               "empreinte": [round(x / norme, 6) for x in somme], "seances": seances}
    reachy_personnes._ecrire(chemin, json.dumps(donnees))


def nouvelle_seance(compteur, nombre, vecteur, heure=None):
    return {"id": uuid.uuid4().hex[:8], "le": _horodatage(), "moment": moment(heure), compteur: int(nombre),
            "empreinte": [round(float(x), 6) for x in vecteur]}


def _publique(seance, compteur):
    """Ce que la page voit d'une séance : jamais les nombres de l'empreinte."""
    return {"id": seance.get("id"), "le": seance.get("le"), "moment": seance.get("moment", ""),
            "nombre": seance.get(compteur)}


# --- le son : découpage d'une phrase, préparation comme le pont ---------------------------------------------
def rms(trame):
    n = len(trame) // 2
    if not n:
        return 0.0
    valeurs = struct.unpack(f"<{n}h", trame[:2 * n])
    return (sum(v * v for v in valeurs) / n) ** 0.5


def pic(buf):
    n = len(buf) // 2
    return max((abs(v) for v in struct.unpack(f"<{n}h", buf[:2 * n])), default=0)


def amplifier(buf, cible=20000, gain_max=8.0):
    """La préparation du pont (`wyoming-whispercpp-bridge.py`, même règle) : le pic amené vers `cible`."""
    p = pic(buf)
    if p <= 0:
        return buf
    g = min(gain_max, cible / p)
    n = len(buf) // 2
    return struct.pack(f"<{n}h", *(max(-32768, min(32767, int(v * g))) for v in struct.unpack(f"<{n}h", buf[:2 * n])))


class Decoupeur:
    """Reçoit des trames de 30 ms et dit où en est la phrase. Pur, testable.
    `etat` : "bruit" (mesure du fond), "attente", "parole", "fini" ; `niveau` 0-1 pour la jauge."""

    def __init__(self):
        self.fond, self.mesures = None, []
        self.etat, self.niveau = "bruit", 0.0
        self.parole, self.silence, self.attente = bytearray(), 0.0, 0.0
        self.duree, self.debut_fort = 0.0, 0

    def ajouter(self, trame):
        dt = len(trame) / 2 / RATE
        e = rms(trame)
        self.niveau = min(1.0, e / 6000.0)
        if self.etat == "bruit":
            self.mesures.append(e)
            if len(self.mesures) * dt >= 0.6:
                self.fond = sorted(self.mesures)[len(self.mesures) // 2]
                self.etat = "attente"
            return self.etat
        seuil = max(PAROLE * (self.fond or 0.0), PAROLE_MIN_RMS)
        if self.etat == "attente":
            self.attente += dt
            if e >= seuil:
                self.debut_fort += 1
                self.parole.extend(trame)
                if self.debut_fort >= 3:
                    self.etat = "parole"
            else:
                self.debut_fort, self.parole = 0, bytearray()
            return self.etat
        if self.etat == "parole":
            self.parole.extend(trame)
            self.duree += dt
            self.silence = self.silence + dt if e < seuil else 0.0
            if self.silence >= FIN_SILENCE or self.duree >= VOIX_MAX:
                self.etat = "fini"
        return self.etat

    def verdict(self):
        """→ (audio de la phrase, None) ou (None, la raison du refus en français)."""
        voix = self.duree - self.silence
        if voix < VOIX_MIN:
            return None, "phrase trop courte : lire toute la phrase, d'une traite"
        p = pic(bytes(self.parole))
        if p < PIC_MIN:
            return None, "voix trop faible : se rapprocher du robot"
        n = len(self.parole) // 2
        satures = sum(1 for v in struct.unpack(f"<{n}h", bytes(self.parole[:2 * n])) if abs(v) >= SATURE)
        if satures > n * 0.01:
            return None, "son saturé : parler un peu moins fort ou reculer"
        return bytes(self.parole), None


def micro_parecord(appareil):
    """Une source de trames : `parecord` 16 kHz mono sur le micro du robot. → (lire(), fermer())."""
    proc = subprocess.Popen(["parecord", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le",
                             f"--device={appareil}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return (lambda: proc.stdout.read(TRAME * 2)), proc.kill


class Apprendre:
    """L'apprentissage, une tâche à la fois. Tout ce qui touche au matériel est injectable (essais)."""

    def __init__(self, body, personnes, images=None, empreinte_visage=None, ecouter=None, empreinte_voix=None,
                 analyser=None, pause=time.sleep):
        alive = body.alive
        self.body, self.personnes, self.pause = body, personnes, pause
        self.visages, self.voix = personnes.visages, personnes.voix
        self.source = str(alive.get("regard") or "")
        self.micro = str(alive.get("micro") or "")
        self.modele_voix = Path(alive.get("voix_modele") or (self.voix.parent / "campplus.onnx" if self.voix else ""))
        self.images = images or self._image
        self.empreinte_visage = empreinte_visage or self._empreinte_visage
        self.ecouter = ecouter or (lambda: micro_parecord(self.micro))
        self.empreinte_voix = empreinte_voix or self._empreinte_voix
        self.analyser = analyser or self._analyser
        self.lock = threading.RLock()
        self.tache = None
        self.arret = threading.Event()
        self._noms = None                     # FaceNames (OpenCV) chargé à la première demande
        self._extracteur = None
        self._vue_cache = (None, None)        # (identité de l'image analysée, résultat)

    # --- ce que la page voit -----------------------------------------------------------------------------
    def capacites(self):
        return {"camera": bool(self.source) and self.visages is not None,
                "micro": bool(self.micro) and self.voix is not None and self.modele_voix.is_file(),
                "ecriture": self.personnes.accords_fichier is not None}

    def etat(self):
        accords = self.personnes._accords()
        gens = []
        for nom in self.personnes.noms():
            accord = accords.get(nom) if isinstance(accords.get(nom), dict) else {}
            gens.append({"nom": nom, "affiche": nom.capitalize(),
                         "visage": [_publique(s, "vues") for s in self._seances("visage", nom)],
                         "voix": [_publique(s, "phrases") for s in self._seances("voix", nom)],
                         "accord": {g: accord.get(g) for g in reachy_personnes.GENRES if isinstance(accord.get(g), dict)}})
        capacites = self.capacites()
        manque = {"camera": "" if capacites["camera"] else "pas de caméra ou de dossier de visages dans les réglages du corps",
                  "micro": "" if capacites["micro"] else ("pas de micro dans les réglages du corps (« micro »)" if not self.micro
                                                         else "pas de dossier de voix ou de modèle de voix (campplus.onnx)")}
        return {"personnes": gens, "capacites": capacites, "manque": manque, "poses": [p[1] for p in POSES],
                "phrases": PHRASES, "phrases_min": PHRASES_MIN, "vues_min": VUES_MIN, "tache": self.etat_tache()}

    def etat_tache(self):
        with self.lock:
            if not self.tache:
                return None
            return {k: v for k, v in self.tache.items() if not k.startswith("_")}

    def _chemin(self, genre, nom):
        dossier = self.visages if genre == "visage" else self.voix
        return dossier / f"{nom}.json" if dossier else None

    def _seances(self, genre, nom):
        chemin = self._chemin(genre, nom)
        return lire_seances(chemin, "vues" if genre == "visage" else "phrases") if chemin else []

    # --- commun aux séances ------------------------------------------------------------------------------
    def _commencer(self, genre, nom, par, accord, **champs):
        if not self.capacites()["ecriture"]:
            raise Refus(409, "aucun dossier d'empreintes configuré")
        existant = (self.personnes._accords().get(nom) or {}).get(genre)
        if accord is not True and not existant and reachy_personnes.accord_requis(self.body):
            raise Refus(400, f"l'accord de la personne est obligatoire avant d'enregistrer {'son visage' if genre == 'visage' else 'sa voix'}")
        with self.lock:
            if self._occupe():
                raise Refus(409, "un apprentissage est déjà en cours")
            if getattr(self.personnes, "tache", None) and self.personnes.tache.get("etat") == "en cours":
                raise Refus(409, "un enregistrement est en cours dans Personnes")
            avant = self.personnes.noter_accord(nom, genre, par) if accord is True and str(par or "").strip() else existant
            self.arret.clear()
            self.tache = {"genre": genre, "nom": nom, "etat": "en cours", "debut": _horodatage(), "_depuis": time.monotonic(),
                          "_accord_avant": avant, "_accord_note": accord is True, **champs}
        return self.etat_tache()

    def _occupe(self):
        """Une tâche en cours ; une séance laissée en plan (page fermée) plus de ABANDON secondes est annulée."""
        t = self.tache
        if not t or t["etat"] != "en cours":
            return False
        if time.monotonic() - t.get("_depuis", 0.0) < ABANDON:
            return True
        self.annuler()
        return False

    def _maj(self, **champs):
        with self.lock:
            if self.tache:
                self.tache.update(champs)

    def _echouer(self, message, etat="erreur"):
        with self.lock:
            t = self.tache or {}
            if t.get("_accord_note"):
                try:
                    self.personnes._rendre_accord(t["nom"], t["genre"], t.get("_accord_avant"))
                except Refus:
                    pass
            if t:
                t.update(etat=etat, message=message, _accord_note=False)

    def annuler(self):
        with self.lock:
            if not self.tache or self.tache["etat"] in ("fini", "erreur", "annule"):
                return self.etat_tache()
            self.arret.set()
            genre = self.tache["genre"]
        self._echouer("annulé : rien n'a été enregistré", etat="annule")
        if genre == "voix":
            self._lever_mesure("apprentissage annulé")
        return self.etat_tache()

    def oublier_seance(self, nom, genre, ident):
        if genre not in reachy_personnes.GENRES:
            raise Refus(400, "visage ou voix")
        compteur = "vues" if genre == "visage" else "phrases"
        with self.lock:
            seances = self._seances(genre, nom)
            restantes = [s for s in seances if s.get("id") != ident]
            if len(restantes) == len(seances):
                raise Refus(404, "séance introuvable")
            ecrire_seances(self._chemin(genre, nom), nom, self._modele(genre), compteur, restantes)
        self.body.on_note(f"séance de {genre} oubliée : {nom} ({len(restantes)} restante(s))")
        return self.etat()

    @staticmethod
    def _modele(genre):
        return "sface_2021dec" if genre == "visage" else "campplus_sv_zh_en_16k-common_advanced"

    # --- visage ---------------------------------------------------------------------------------------------
    def lancer_visage(self, nom, par, accord):
        if not self.capacites()["camera"]:
            raise Refus(409, "il faut une caméra et un dossier de visages dans les réglages du corps")
        etat = self._commencer("visage", nom, par, accord, pose=0, poses=len(POSES), consigne=POSES[0][1],
                               fait=0, total=len(POSES) * IMAGES_PAR_POSE, retenues=0, compte=PAUSE_POSE)
        threading.Thread(target=self._courir_visage, args=(nom,), daemon=True).start()
        return etat

    def _courir_visage(self, nom):
        try:
            gardees, fait = [], 0
            for i, (_, consigne) in enumerate(POSES):
                self._maj(pose=i, consigne=consigne, phase="consigne", compte=PAUSE_POSE)
                if self.arret.wait(0) or self._attendre(PAUSE_POSE):
                    return
                self._maj(phase="images")
                for _ in range(IMAGES_PAR_POSE):
                    if self.arret.is_set():
                        return
                    v = self.empreinte_visage(self.images())
                    fait += 1
                    if v is not None:
                        gardees.append(v)
                    self._maj(fait=fait, retenues=len(gardees))
                    self.pause(ENTRE_IMAGES)
            if len(gardees) < VUES_MIN:
                raise RuntimeError(f"seulement {len(gardees)} vue(s) nette(s) : visage trop petit, flou ou mal éclairé")
            moyenne = _normer([sum(c) / len(gardees) for c in zip(*gardees)])
            with self.lock:
                if self.arret.is_set():
                    return
                seances = self._seances("visage", nom) + [nouvelle_seance("vues", len(gardees), moyenne)]
                ecrire_seances(self._chemin("visage", nom), nom, self._modele("visage"), "vues", seances)
                self.tache["_accord_note"] = False           # gardé : la séance est écrite
            self._maj(phase="verification", retenues=len(gardees))
            self.body.on_note(f"séance de visage apprise : {nom} ({len(gardees)} vues)")
            self._maj(etat="fini", verification=self._verifier_visage(nom))
        except Exception as erreur:                          # noqa: BLE001 — rien ne doit tuer le fil
            self._echouer(str(erreur)[:200])

    def _attendre(self, secondes):
        """Compte à rebours de la consigne (la page l'affiche). → vrai si annulé."""
        fin = time.monotonic() + secondes
        while True:
            reste = fin - time.monotonic()
            if reste <= 0:
                return False
            self._maj(compte=round(reste, 1))
            if self.arret.wait(min(0.25, reste)):
                return True

    def _verifier_visage(self, nom):
        votes, meilleur = [], 0.0
        for _ in range(3):
            v = self.empreinte_visage(self.images())
            if v is not None:
                scores = self._scores_visage(v)
                meilleur = max(meilleur, scores.get(nom, 0.0))
                votes.append(self._decider_visage(scores)[0])
            self.pause(0.5)
        return {"reconnu": nom if votes.count(nom) >= 2 else "inconnu", "ressemblance": round(meilleur, 2)}

    def _scores_visage(self, v):
        """La meilleure ressemblance de chaque personne sur ses séances (128 nombres : sans numpy)."""
        v = _normer(v)
        scores = {}
        for chemin in sorted(self.visages.glob("*.json")) if self.visages and self.visages.is_dir() else []:
            meilleure = [sum(a * b for a, b in zip(v, _normer(s["empreinte"]))) for s in lire_seances(chemin, "vues")
                         if len(s["empreinte"]) == len(v)]
            if meilleure:
                scores[chemin.stem] = round(max(meilleure), 3)
        return scores

    def _decider_visage(self, scores):
        import reachy_vue
        r = getattr(self.body, "reglages", None)
        return reachy_vue.decide(scores, r("who_min") if r else None, r("who_gap") if r else None)

    def _image(self):
        import cv2
        import numpy as np
        import urllib.request
        url = self.source.replace("/api/stream.mjpeg", "/api/frame.jpeg")
        with urllib.request.urlopen(url, timeout=5) as reponse:
            return cv2.imdecode(np.frombuffer(reponse.read(), np.uint8), cv2.IMREAD_COLOR)

    def _face_names(self):
        if self._noms is None:
            import reachy_vue
            self._noms = reachy_vue.FaceNames(str(self.visages), getattr(self.body, "reglages", None))
        return self._noms

    def _empreinte_visage(self, image):
        if image is None:
            return None
        with self.lock:
            return self._face_names().feature(image)

    def vue(self):
        """Analyse de la DERNIÈRE image reçue par la vue (aucun appel de plus à la caméra) : pour la page."""
        eyes = getattr(self.body, "eyes", None)
        jpeg = getattr(eyes, "jpeg", None) if eyes is not None else None
        if not jpeg or self.visages is None:
            return {"image": False, "visages": []}
        if self._vue_cache[0] is jpeg:
            return self._vue_cache[1]
        resultat = {"image": True, "visages": self.analyser(jpeg)}
        self._vue_cache = (jpeg, resultat)
        return resultat

    def _analyser(self, jpeg):
        import cv2
        import numpy as np
        import reachy_vue
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return []
        with self.lock:
            noms = self._face_names()
            noms.detector.setInputSize((image.shape[1], image.shape[0]))
            _, faces = noms.detector.detect(image)
            if faces is None:
                return []
            sets = reachy_vue.load_print_sets(self.visages)
            sure = noms.r("face_sure")
            sortie = []
            for f in sorted(faces, key=lambda f: -f[2] * f[3])[:3]:
                x, y, w, h = (float(f[0]), float(f[1]), float(f[2]), float(f[3]))
                x0, y0 = max(0, int(x)), max(0, int(y))
                gris = cv2.cvtColor(image[y0:y0 + int(h), x0:x0 + int(w)], cv2.COLOR_BGR2GRAY)
                lumiere = float(gris.mean()) / 255.0 if gris.size else 0.0
                net = float(f[-1])
                scores = {}
                if net >= sure:
                    v = np.asarray(noms.recognizer.feature(noms.recognizer.alignCrop(image, f)), np.float32).ravel()
                    scores = {n: round(s, 3) for n, s in reachy_vue.best_scores(v / np.linalg.norm(v), sets).items()}
                qui, _ = self._decider_visage(scores) if scores else ("", 0.0)
                sortie.append({"boite": [round(x / image.shape[1], 4), round(y / image.shape[0], 4),
                                         round(w / image.shape[1], 4), round(h / image.shape[0], 4)],
                               "taille": int(w), "net": round(net, 2), "lumiere": round(lumiere, 2),
                               "conseil": conseil_visage(int(w), net, lumiere, sure), "scores": scores, "qui": qui})
            return sortie

    # --- voix ---------------------------------------------------------------------------------------------
    def lancer_voix(self, nom, par, accord):
        if not self.capacites()["micro"]:
            raise Refus(409, "il faut un micro, un dossier de voix et le modèle de voix dans les réglages du corps")
        if hasattr(self.body, "enter_measure_mode"):
            ok, raison = self.body.enter_measure_mode("apprentissage de la voix")
            if not ok:
                raise Refus(409, raison)
        try:
            etat = self._commencer("voix", nom, par, accord, phrase=0, total=len(PHRASES), phrases=[None] * len(PHRASES),
                                   ecoute="", niveau=0.0, message="")
        except Refus:
            self._lever_mesure("apprentissage refusé")
            raise
        self._ecouter_phrase()
        return etat

    def _lever_mesure(self, raison):
        if hasattr(self.body, "leave_measure_mode"):
            self.body.leave_measure_mode(raison)

    def phrase(self, action):
        """Les boutons d'une séance de voix : « refaire », « passer », « terminer »."""
        with self.lock:
            t = self.tache
            if not t or t["genre"] != "voix" or t["etat"] != "en cours":
                raise Refus(409, "aucune séance de voix en cours")
            if action == "terminer":
                return self._terminer_voix()
            if t.get("ecoute") in ("bruit", "attente", "parole", "analyse"):
                raise Refus(409, "le robot écoute déjà : lire la phrase affichée")
            if action == "passer":
                t["phrase"] = min(t["phrase"] + 1, len(PHRASES))
            elif action != "refaire":
                raise Refus(400, "refaire, passer ou terminer")
            if t["phrase"] >= len(PHRASES):
                t["ecoute"] = "fin"
                return self.etat_tache()
        self._ecouter_phrase()
        return self.etat_tache()

    def _ecouter_phrase(self, essai=False):
        self._maj(ecoute="bruit", niveau=0.0, message="")
        threading.Thread(target=self._courir_phrase, args=(essai,), daemon=True).start()

    def _courir_phrase(self, essai):
        lire = fermer = None
        try:
            lire, fermer = self.ecouter()
            d, attente = Decoupeur(), 0.0
            while not self.arret.is_set():
                trame = lire()
                if not trame:
                    raise RuntimeError("le micro ne répond pas")
                etat = d.ajouter(trame)
                self._maj(ecoute=etat if etat != "fini" else "analyse", niveau=round(d.niveau, 2))
                if etat == "attente":
                    attente += len(trame) / 2 / RATE
                    if attente >= ATTENTE_MAX:
                        self._refus_phrase(essai, "rien", "rien entendu : appuyer sur « Refaire » puis lire la phrase")
                        return
                if etat == "fini":
                    break
            if self.arret.is_set():
                return
            fermer()
            fermer = None
            audio, refus = d.verdict()
            if refus:
                self._refus_phrase(essai, "refus", refus)
                return
            v = self.empreinte_voix(amplifier(audio))
            scores = self._scores_voix(v)
            if essai:
                self._maj(etat="fini", ecoute="fini", niveau=0.0, resultat=self._decider_voix(scores))
                return
            with self.lock:
                t = self.tache
                if not t or t["etat"] != "en cours":
                    return
                i = t["phrase"]
                autre = self._decider_voix({n: s for n, s in scores.items()})
                alerte = autre["nom"] not in ("inconnu", t["nom"])
                t["phrases"][i] = {"ok": True, "duree": round(d.duree - d.silence, 1),
                                   "ressemblance": round(scores.get(t["nom"], 0.0), 2) if t["nom"] in scores else None,
                                   "alerte": f"on dirait la voix de {autre['nom'].capitalize()}" if alerte else ""}
                t.setdefault("_vecteurs", {})[i] = v
                t["phrase"] = i + 1
                t["ecoute"] = "fin" if t["phrase"] >= len(PHRASES) else "entre"
                t["niveau"] = 0.0
                continuer = t["phrase"] < len(PHRASES)
            if continuer:
                self.pause(0.8)                  # le temps de lire la phrase suivante
                if not self.arret.is_set():
                    self._courir_phrase(False)
        except Exception as erreur:                  # noqa: BLE001 — rien ne doit tuer le fil
            self._refus_phrase(essai, "refus", f"écoute impossible : {str(erreur)[:120]}")
        finally:
            if fermer:
                fermer()

    def _refus_phrase(self, essai, ecoute, message):
        """Une phrase refusée : la séance attend « Refaire » ; un essai, lui, se termine (rien n'est écrit)."""
        self._maj(ecoute=ecoute, niveau=0.0, message=message, **({"etat": "erreur"} if essai else {}))

    def _terminer_voix(self):
        t = self.tache
        vecteurs = list((t.get("_vecteurs") or {}).values())
        if len(vecteurs) < PHRASES_MIN:
            raise Refus(409, f"il faut au moins {PHRASES_MIN} phrases réussies ({len(vecteurs)} pour l'instant)")
        self.arret.set()
        moyenne = _normer([sum(c) / len(vecteurs) for c in zip(*vecteurs)])
        seances = self._seances("voix", t["nom"]) + [nouvelle_seance("phrases", len(vecteurs), moyenne)]
        ecrire_seances(self._chemin("voix", t["nom"]), t["nom"], self._modele("voix"), "phrases", seances)
        t.update(etat="fini", ecoute="fini", niveau=0.0, retenues=len(vecteurs), _accord_note=False)
        t.pop("_vecteurs", None)
        self._lever_mesure("apprentissage de la voix terminé")
        self.body.on_note(f"séance de voix apprise : {t['nom']} ({len(vecteurs)} phrases)")
        return self.etat_tache()

    def essai_voix(self):
        """« Qui parle ? » : une phrase, les ressemblances, la décision du pont. Rien n'est écrit."""
        if not self.capacites()["micro"]:
            raise Refus(409, "il faut un micro et le modèle de voix dans les réglages du corps")
        with self.lock:
            if self._occupe():
                raise Refus(409, "un apprentissage est déjà en cours")
            self.arret.clear()
            self.tache = {"genre": "essai", "_depuis": time.monotonic(), "nom": "", "etat": "en cours", "ecoute": "bruit", "niveau": 0.0,
                          "message": "", "debut": _horodatage()}
        self._ecouter_phrase(essai=True)
        return self.etat_tache()

    def _scores_voix(self, v):
        scores = {}
        if self.voix and self.voix.is_dir():
            for chemin in sorted(self.voix.glob("*.json")):
                try:
                    d = json.loads(chemin.read_text())
                    e = _normer([float(x) for x in d["empreinte"]])
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                if len(e) == len(v):
                    scores[str(d.get("nom") or chemin.stem)] = round(sum(a * b for a, b in zip(v, e)), 3)
        return scores

    @staticmethod
    def _decider_voix(scores):
        if not scores:
            return {"nom": "inconnu", "scores": {}}
        rang = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        nom, best = rang[0]
        second = rang[1][1] if len(rang) > 1 else 0.0
        return {"nom": nom if best >= VOIX_SEUIL and best - second >= VOIX_ECART else "inconnu", "scores": scores,
                "seuil": VOIX_SEUIL, "ecart": VOIX_ECART}

    def _empreinte_voix(self, audio):
        import numpy as np
        if self._extracteur is None:
            import sherpa_onnx
            self._extracteur = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.modele_voix), num_threads=1))
        x = np.frombuffer(audio, np.int16).astype(np.float32) / 32768.0
        st = self._extracteur.create_stream()
        st.accept_waveform(RATE, x)
        st.input_finished()
        e = np.asarray(self._extracteur.compute(st), np.float32)
        return [float(a) for a in e / np.linalg.norm(e)]

    # --- le routeur ---------------------------------------------------------------------------------------
    def route(self, methode, chemin, demande):
        try:
            if methode == "GET":
                if chemin == PREFIXE:
                    return 200, self.etat()
                if chemin == PREFIXE + "/tache":
                    return 200, {"tache": self.etat_tache()}
                if chemin == PREFIXE + "/vue":
                    return 200, self.vue()
                raise Refus(404, "inconnu")
            if not isinstance(demande, dict):
                raise Refus(400, "un objet JSON est attendu")
            action = chemin[len(PREFIXE) + 1:]
            if action not in ("annuler", "voix/phrase", "voix/essai", "visage", "voix", "oublier-seance"):
                raise Refus(404, "inconnu")
            if action == "annuler":
                return 200, {"tache": self.annuler()}
            if action == "voix/phrase":
                return 200, {"tache": self.phrase(str(demande.get("action", "")))}
            if action == "voix/essai":
                return 202, {"tache": self.essai_voix()}
            nom = nom_sur(demande.get("nom"))
            if action == "visage":
                return 202, {"tache": self.lancer_visage(nom, demande.get("par"), demande.get("accord"))}
            if action == "voix":
                return 202, {"tache": self.lancer_voix(nom, demande.get("par"), demande.get("accord"))}
            return 200, self.oublier_seance(nom, demande.get("genre"), str(demande.get("id", "")))
        except Refus as refus:
            return refus.status, {"erreur": refus.message}
        except OSError as trouble:
            return 500, {"erreur": f"écriture impossible : {str(trouble)[:120]}"}


def conseil_visage(taille, net, lumiere, sure):
    """Le conseil affiché sous l'image, du plus utile au moins utile. Pur, testable."""
    if lumiere < 0.18:
        return "trop sombre : allumer ou se tourner vers la lumière"
    if taille < 40:
        return "trop loin : se rapprocher du robot"
    if net < sure:
        return "de profil ou flou : regarder le robot"
    if lumiere > 0.85:
        return "trop de lumière : éviter le contre-jour"
    return "bien"


def _normer(v):
    n = sum(float(x) * float(x) for x in v) ** 0.5 or 1.0
    return [float(x) / n for x in v]
