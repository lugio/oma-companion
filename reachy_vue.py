#!/usr/bin/env python3
"""La vue du robot : qui est là, et où — pour que la tête suive une personne au repos.

Repris du SDK de Pollen (`reachy_mini/vision/face_detector.py` et `face_tracking.py`, v1.11.0,
licence Apache-2.0, © Pollen Robotics) : le même détecteur YuNet, le même modèle publié par Pollen
(révision figée), le même suivi (la plus grande face d'abord, puis la plus proche, abandon après 20
images manquées) et le même lissage du centre. Seules différences : le modèle est téléchargé par
`urllib` (pas de `huggingface_hub`) et vérifié par son empreinte, et les images viennent d'un
`ffmpeg` qui lit la caméra du robot — directement, ou par le flux go2rtc quand un autre programme
(Frigate) la tient déjà.

Pourquoi pas le suivi intégré au service du robot (`/api/media/tracking/enable`) : il exige le
service AVEC la caméra, et sur la machine de test elle est tenue par go2rtc pour Frigate (`--no-media`).

Rien ici ne bouge le robot : `Eyes.latest()` rend une observation, `reachy.Body` décide.
Dépendances : numpy, onnxruntime, ffmpeg. Absentes = pas de vue, le reste du corps marche.
"""
import hashlib
import json
import math
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from reachy_reglages import Reglages

MODEL_URL = ("https://huggingface.co/pollen-robotics/face_detection_yunet_2026may/resolve/"
             "2b8e922362946a0db67e861bae0f77826980effd/face_detection_yunet_2026may.onnx")
MODEL_SHA256 = "ebafce4e3c118d65"            # début de l'empreinte, mesurée le 09/10/2026
MODEL = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "reachy-vue" / "yunet.onnx"
STRIDES, MAX_STRIDE = (8, 16, 32), 32
WIDTH, HEIGHT = 640, 360                     # Pollen détecte en 320 ; 640 pour voir à 3 m (canapé)
FPS = 3                                      # images analysées par seconde
# Champ de la caméra (Pollen, `camera_constants.py`, 1280×720 : fx 550, cx 638 ; fy 549, cy 365) :
# un point au bord de l'image est à atan(1,16) ≈ 49° de l'axe, en haut à atan(0,66) ≈ 34°.
TAN_HALF_X, TAN_HALF_Y = 638.0 / 550.4, 364.6 / 549.2


def _nms(boxes, scores, iou):
    import numpy as np
    if not boxes:
        return []
    b = np.array(boxes, dtype=np.float32)
    x1, y1, x2, y2 = b[:, 0], b[:, 1], b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    area = b[:, 2] * b[:, 3]
    order = np.array(scores, dtype=np.float32).argsort()[::-1]
    keep = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        w = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        h = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = w * h
        order = rest[inter / (area[i] + area[rest] - inter) <= iou]
    return keep


def model_path():
    """Le modèle YuNet de Pollen, téléchargé une fois, vérifié par son empreinte."""
    if not MODEL.is_file():
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        temporary = MODEL.with_suffix(".tmp")
        with urllib.request.urlopen(MODEL_URL, timeout=30) as answer:
            temporary.write_bytes(answer.read())
        temporary.replace(MODEL)
    if not hashlib.sha256(MODEL.read_bytes()).hexdigest().startswith(MODEL_SHA256):
        MODEL.unlink(missing_ok=True)
        raise RuntimeError("modèle YuNet altéré : effacé, il sera retéléchargé")
    return str(MODEL)



def stop(process):
    """Tue ffmpeg ET l'attend (sinon il reste en zombie), puis ferme son flux."""
    process.kill()
    try:
        process.wait(timeout=2)
    except Exception:  # noqa: BLE001 - un arrêt ne doit jamais lever
        pass
    if process.stdout is not None:
        try:
            process.stdout.close()
        except OSError:
            pass

class FaceDetector:
    """YuNet sur ONNX Runtime, UN fil de calcul (Pollen : « so it can't starve the loop »)."""

    def __init__(self, score=0.6, nms=0.3):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(model_path(), options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.outputs = [o.name for o in self.session.get_outputs()]
        self.score, self.nms = score, nms

    def detect(self, frame):
        """Les visages d'une image BGR : liste de (boîte x, y, l, h ; nez x, y ; score)."""
        import numpy as np
        h, w = frame.shape[:2]
        ph, pw = math.ceil(h / MAX_STRIDE) * MAX_STRIDE, math.ceil(w / MAX_STRIDE) * MAX_STRIDE
        if (ph, pw) != (h, w):
            padded = np.zeros((ph, pw, 3), dtype=frame.dtype)
            padded[:h, :w] = frame
            frame = padded
        out = dict(zip(self.outputs, self.session.run(None, {self.input: frame.astype(np.float32).transpose(2, 0, 1)[np.newaxis]})))
        boxes, scores, faces = [], [], []
        for stride in STRIDES:
            cls, obj = out[f"cls_{stride}"][0, :, 0], out[f"obj_{stride}"][0, :, 0]
            score = np.sqrt(np.clip(cls, 0, 1) * np.clip(obj, 0, 1))
            idx = np.nonzero(score >= self.score)[0]
            if not idx.size:
                continue
            bbox, kps = out[f"bbox_{stride}"][0][idx], out[f"kps_{stride}"][0][idx]
            cols = pw // stride
            col, row = (idx % cols).astype(np.float32), (idx // cols).astype(np.float32)
            cx, cy = (col + bbox[:, 0]) * stride, (row + bbox[:, 1]) * stride
            bw, bh = np.exp(bbox[:, 2]) * stride, np.exp(bbox[:, 3]) * stride
            for k in range(idx.size):
                box = (float(cx[k] - bw[k] / 2), float(cy[k] - bh[k] / 2), float(bw[k]), float(bh[k]))
                boxes.append(box)
                scores.append(float(score[idx[k]]))
                faces.append((box, (float((col[k] + kps[k, 4]) * stride), float((row[k] + kps[k, 5]) * stride)), float(score[idx[k]])))
        return [faces[i] for i in _nms(boxes, scores, self.nms)]


# --- Qui est là (10/10/2026) -------------------------------------------------------------------------
# FACULTATIF : seulement si un dossier d'empreintes est donné (`Eyes(…, faces=dossier)`). Sans lui, rien ne
# change. Outils OFFICIELS d'OpenCV (≥ 4.5.4) : `FaceDetectorYN` (repère les yeux, le nez, la bouche pour
# redresser le visage) et `FaceRecognizerSF` (SFace, empreinte de 128 nombres), modèles du dépôt
# opencv_zoo (licence Apache-2.0), vérifiés par leur empreinte SHA-256.
# À 3 m un visage fait ~50 px sur l'image 1920×1080 et ~17 px sur celle que la vue analyse (640×360) :
# la reconnaissance relit donc l'image PLEINE TAILLE, une seule fois quand un nouveau visage apparaît.
# Mesuré le 10/10 (test sur canapé, caméra floue) : même personne 0,63-0,85 (cosinus) ; OpenCV conseille 0,363.
FACE_MODELS = {
    "yunet_cv.onnx": ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
                      "face_detection_yunet_2023mar.onnx",
                      "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "sface.onnx": ("https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
                   "face_recognition_sface_2021dec.onnx",
                   "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}
FACE_SURE = 0.85            # score de détection minimal pour reconnaître (en dessous : profil, flou, faux visage)
WHO_MIN = 0.45              # ressemblance minimale (cosinus SFace)
WHO_GAP = 0.10              # et d'avance sur la personne suivante
WHO_EVERY = 2.0             # secondes entre deux essais sur un même visage pas encore reconnu
WHO_TRIES = 5               # essais avant de le dire « inconnu »
INCONNUS_MAX = 12          # 11/10 : vues d'un visage inconnu gardées par passage devant le robot (les meilleures)
INCONNU_TAILLE = 60        # 12/10 : px ; un visage plus petit (loin, flou) n'apprend rien : pas gardé
INCONNUS_PAUSE = 600.0     # 12/10 : s sans nouvel inconnu → le passage est rangé (avant : à chaque perte de vue,
INCONNUS_DUREE = 1800.0    # 658 passages d'1,6 vue le 12/10) ; et au plus toutes les INCONNUS_DUREE s
AUTRES_EVERY = 3.0         # 11/10 : secondes entre deux essais sur les AUTRES visages (pas celui qu'il suit)
AUTRES_MAX = 4             # autres visages essayés au plus par tour (~0,02 s chacun)
PRESENT = 20.0             # s : une personne reconnue reste « là » ce temps-là sans être revue
ANIMAL_EVERY = 2.0         # 11/10 : secondes entre deux recherches d'animal (YOLOX, ~0,1 s)
ANIMAL_MIN = 60            # px : largeur minimale d'un animal cherché
ANIMAL_ACCORD = 2          # vues d'accord (en ANIMAL_OUBLI s) avant de mettre un nom sur l'animal


def animal_reconnu(extras):
    """15/10 : le nom d'étiquette reconnu sur la majorité des vues d'une visite (au moins ANIMAL_ACCORD vues),
    sinon None. Une visite reconnue n'est pas mise à trier (280 passages « le chien » en 3 jours). Pur."""
    noms = [e.get("reconnu") for e in extras if isinstance(e, dict)]
    if not noms:
        return None
    meilleur = max(set(noms), key=noms.count)
    return meilleur if meilleur and noms.count(meilleur) >= ANIMAL_ACCORD and noms.count(meilleur) * 2 > len(noms) else None
ANIMAL_OUBLI = 30.0        # s sans le voir : il est parti (ses vues sont rangées pour le tri)
WHO_RETRY = 10.0            # 11/10 : un visage dit « inconnu » est réessayé toutes les WHO_RETRY secondes (lumière
                            # du matin, visage de biais : le premier essai rate, le suivant reconnaît)


def face_model(name, models=None):
    """Un modèle d'opencv_zoo, téléchargé une fois, vérifié par son empreinte complète. `models` : un autre
    catalogue {nom: (adresse, empreinte)} (11/10 : les objets, `reachy_objets.MODELES`)."""
    url, digest = (models or FACE_MODELS)[name]
    path = MODEL.parent / name
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with urllib.request.urlopen(url, timeout=60) as answer:
            temporary.write_bytes(answer.read())
        temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"modèle {name} altéré : effacé, il sera retéléchargé")
    return str(path)


def decide(scores, least=None, gap=None):
    """`scores` = {nom: ressemblance} → (nom ou "inconnu", meilleure ressemblance). Pure, testable.
    Sans `least` ni `gap` : WHO_MIN et WHO_GAP."""
    least = WHO_MIN if least is None else least
    gap = WHO_GAP if gap is None else gap
    if not scores:
        return "inconnu", 0.0
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    name, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return (name if best >= least and best - second >= gap else "inconnu"), best


def load_prints(folder):
    """Les empreintes enrôlées : {nom: vecteur normé}. Fichiers `<nom>.json` = {"nom", "empreinte": [...]}."""
    import json
    import numpy as np
    prints = {}
    for path in sorted(Path(folder).glob("*.json")):
        try:
            data = json.loads(path.read_text())
            v = np.asarray(data["empreinte"], np.float32)
            prints[str(data.get("nom") or path.stem)] = v / np.linalg.norm(v)
        except (OSError, ValueError, KeyError):
            continue
    return prints


def load_print_sets(folder):
    """Les empreintes enrôlées PAR SÉANCE (11/10, `reachy_apprendre`) : {nom: [vecteurs normés]}. Un ancien
    fichier (une seule empreinte) compte pour une séance."""
    import json
    import numpy as np
    import reachy_apprendre
    sets = {}
    for path in sorted(Path(folder).glob("*.json")):
        vectors = []
        for seance in reachy_apprendre.lire_seances(path, "vues"):
            try:
                v = np.asarray(seance["empreinte"], np.float32)
                vectors.append(v / np.linalg.norm(v))
            except (ValueError, TypeError):
                continue
        if vectors:
            try:
                name = str(json.loads(path.read_text()).get("nom") or path.stem)
            except (OSError, ValueError):
                name = path.stem
            sets[name] = vectors
    return sets


def best_scores(v, sets):
    """{nom: la MEILLEURE ressemblance de `v` avec ses séances}. Pur, testable."""
    return {name: max(float(v @ p) for p in vectors) for name, vectors in sets.items() if vectors}


class FaceNames:
    """Qui est ce visage : redresse le visage sur l'image pleine taille, calcule son empreinte SFace et la
    compare aux empreintes enrôlées. Un seul fil de calcul, comme la détection."""

    def __init__(self, folder, reglages=None):
        import cv2
        cv2.setNumThreads(1)
        self.cv2 = cv2
        self.folder = folder
        self.r = reglages if reglages is not None else Reglages()   # seuils : constantes, ou le fichier (11/10)
        self.detector = cv2.FaceDetectorYN.create(face_model("yunet_cv.onnx"), "", (320, 320), 0.6, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(face_model("sface.onnx"), "")

    def feature(self, image, near=None):
        """L'empreinte normée du visage le plus net de `image` (BGR), près de `near` (x, y) s'il est donné ;
        None si aucun visage assez sûr (profil, flou)."""
        import numpy as np
        self.detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = self.detector.detect(image)
        if faces is None:
            return None
        faces = [f for f in faces if f[-1] >= self.r("face_sure")]
        if not faces:
            return None
        if near is not None:
            face = min(faces, key=lambda f: (f[0] + f[2] / 2 - near[0]) ** 2 + (f[1] + f[3] / 2 - near[1]) ** 2)
        else:
            face = max(faces, key=lambda f: f[2] * f[3])
        v = np.asarray(self.recognizer.feature(self.recognizer.alignCrop(image, face)), np.float32).ravel()
        return v / np.linalg.norm(v)

    def gros_plan(self, jpeg, box, cote=192):
        """11/10 : (gros plan jpeg, empreinte normée, netteté, taille px) du visage `box` (vu en WIDTH×HEIGHT),
        ou None s'il n'est pas assez net. Pour la rubrique « Caméras » (`reachy_cams`)."""
        import numpy as np
        image = self.cv2.imdecode(np.frombuffer(jpeg, np.uint8), self.cv2.IMREAD_COLOR)
        if image is None:
            return None
        sx, sy = image.shape[1] / WIDTH, image.shape[0] / HEIGHT
        x, y, w, h = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
        m = max(w, h)
        x0, y0 = int(max(0, x - m)), int(max(0, y - m))
        x1, y1 = int(min(image.shape[1], x + w + m)), int(min(image.shape[0], y + h + m))
        coupe = image[y0:y1, x0:x1]
        self.detector.setInputSize((coupe.shape[1], coupe.shape[0]))
        _, faces = self.detector.detect(coupe)
        faces = [f for f in (faces if faces is not None else []) if f[-1] >= self.r("face_sure")]
        if not faces:
            return None
        face = min(faces, key=lambda f: (f[0] + f[2] / 2 - (x + w / 2 - x0)) ** 2 + (f[1] + f[3] / 2 - (y + h / 2 - y0)) ** 2)
        v = np.asarray(self.recognizer.feature(self.recognizer.alignCrop(coupe, face)), np.float32).ravel()
        fx, fy, fw, fh = (int(a) for a in face[:4])
        k = int(0.4 * max(fw, fh))
        gros = coupe[max(0, fy - k):fy + fh + k, max(0, fx - k):fx + fw + k]
        r = cote / max(gros.shape[:2])
        if r < 1:
            gros = self.cv2.resize(gros, None, fx=r, fy=r, interpolation=self.cv2.INTER_AREA)
        ok, octets = self.cv2.imencode(".jpg", gros, [self.cv2.IMWRITE_JPEG_QUALITY, 85])
        return (octets.tobytes(), (v / np.linalg.norm(v)).tolist(), float(face[-1]), int(fw)) if ok else None

    def who(self, jpeg, box):
        """`jpeg` = l'image d'origine ; `box` = le visage vu en WIDTH×HEIGHT. → (nom ou "inconnu", score),
        ou None si le visage n'est pas assez net pour juger."""
        import numpy as np
        image = self.cv2.imdecode(np.frombuffer(jpeg, np.uint8), self.cv2.IMREAD_COLOR)
        if image is None:
            return None
        sx, sy = image.shape[1] / WIDTH, image.shape[0] / HEIGHT
        x, y, w, h = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
        m = max(w, h)                                 # une marge d'un visage autour : le détecteur voit le contexte
        x0, y0 = int(max(0, x - m)), int(max(0, y - m))
        x1, y1 = int(min(image.shape[1], x + w + m)), int(min(image.shape[0], y + h + m))
        v = self.feature(image[y0:y1, x0:x1], near=(x + w / 2 - x0, y + h / 2 - y0))
        if v is None:
            return None
        return decide(best_scores(v, load_print_sets(self.folder)), self.r("who_min"), self.r("who_gap"))


# --- Les gestes de la main (11/10/2026) -------------------------------------------------------------
# FACULTATIF : `Eyes(…, hands=True)`. MediaPipe Pose Lite (Google, Apache-2.0, 0.10.35) sur un CARRÉ découpé
# dans l'image pleine taille autour de la personne suivie : à 3 m une main n'est jamais vue sur l'image
# entière. Calibré pas à pas sur la machine de test le 11/10 sur la machine de test (pose ~80 ms, visage ~18 ms) :
# mains baissées → rien ; coucou → « coucou » ; main levée immobile → « main ».
# MediaPipe s'installe SANS sa copie d'OpenCV (`pip install --no-deps mediapipe absl-py` + matplotlib,
# sounddevice) : le `cv2` des visages (opencv-python-headless) lui suffit ; « pip check » le signale, c'est voulu.
FACE_MODELS["pose_lite.task"] = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/"
    "pose_landmarker_lite.task", "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a")
# « Main levée » = un BRAS levé, pas une main posée : calibré pas à pas le 11/10 (00 h 30-00 h 40, 1 600
# images). L'ancienne règle (poignet au-dessus de l'épaule) voyait 42 fausses mains dans la posture naturelle
# de test et 9 dans les postures pièges (main sur la tête, menton dans la main, téléphone, bras sur le
# dossier) ; celle-ci : 0, et toutes les vraies mains levées. Mesures (en largeurs d'épaules) : postures
# pièges coude ≤ 0,27 et poignet/nez ≤ 0,29 ; bras levés coude 0,42-0,78 et poignet/nez 0,76-1,29.
ELBOW_UP = 0.35             # coude au-dessus de l'épaule
WRIST_OVER_NOSE = 0.6       # poignet au-dessus du nez
HAND_VISIBLE = 0.5          # confiance minimale du poignet
ELBOW_VISIBLE = 0.6         # confiance minimale du coude
HAND_WINDOW, HAND_NEEDED = 4, 3   # la même main levée sur 3 des 4 dernières images
WAVE_BURST = 1.5            # secondes de rafale une fois la main levée
BURST_EVERY = 0.12          # secondes entre deux images pendant la rafale
WAVE_STEP = 0.12            # déplacement minimal du poignet (en largeurs d'épaules) pour compter un sens
WAVE_TURNS = 2              # changements de sens pour un coucou
WAVE_SPAN = 0.25            # ampleur minimale du va-et-vient (largeurs d'épaules)
FACE_HOLD = 2.0             # secondes : une main levée cache souvent le visage, on garde sa dernière place
GESTURE_COOLDOWN = 3.0      # secondes entre deux gestes annoncés
HOLD_SHARE = 0.8            # « main » : levée sur au moins 80 % de la rafale (elle déclenche l'écoute : sûre)
WAVE_SHARE = 0.5            # « coucou » : levée sur au moins la moitié de la rafale (fausses mains gauches, 11/10)
WAVE_EARLY_MIN = 4          # images de rafale au moins avant de conclure « coucou » sans attendre la fin (11/10)
PREUVES_MAX = 100           # gestes gardés au plus par « Observer les gestes sans réagir » (les plus anciens partent)
TRACE = 24                  # images gardées en mémoire pour la preuve d'un geste (fenêtre + rafale)


def mesures(points, size):
    """Ce que la règle « bras levé » regarde, par côté : coude au-dessus de l'épaule et poignet au-dessus du nez (en
    largeurs d'épaules), et la confiance du détecteur pour le poignet et le coude. Pure."""
    width = max(abs(points[11][0] - points[12][0]) * size, 1.0)
    return {name: {"coude": round((points[shoulder][1] - points[elbow][1]) * size / width, 3),
                   "nez": round((points[0][1] - points[wrist][1]) * size / width, 3),
                   "vis_poignet": round(points[wrist][2], 2), "vis_coude": round(points[elbow][2], 2)}
            for name, wrist, elbow, shoulder in (("gauche", 15, 13, 11), ("droite", 16, 14, 12))}


def raised(points, size, elbow_up=None, wrist_over_nose=None):
    """Les côtés dont le BRAS est levé. `points` = repères MediaPipe normalisés (x, y, visibilité) du carré de
    côté `size` px (0 nez, 11/12 épaules, 13/14 coudes, 15/16 poignets). Pure, testable.
    NB : la gauche et la droite de MediaPipe peuvent être inversées par la caméra (vu le 11/10).
    `elbow_up` / `wrist_over_nose` : les seuils (réglages, lot 4) ; sans eux, les constantes ci-dessus."""
    elbow_up = ELBOW_UP if elbow_up is None else elbow_up
    wrist_over_nose = WRIST_OVER_NOSE if wrist_over_nose is None else wrist_over_nose
    width = max(abs(points[11][0] - points[12][0]) * size, 1.0)
    nose_y = points[0][1]
    sides = set()
    for name, wrist, elbow, shoulder in (("gauche", 15, 13, 11), ("droite", 16, 14, 12)):
        if ((points[shoulder][1] - points[elbow][1]) * size >= elbow_up * width
                and (nose_y - points[wrist][1]) * size >= wrist_over_nose * width
                and points[wrist][2] >= HAND_VISIBLE and points[elbow][2] >= ELBOW_VISIBLE):
            sides.add(name)
    return sides


def waving(xs):
    """Le poignet va-t-il et vient-il ? `xs` = positions (largeurs d'épaules) pendant la rafale. Pure."""
    turns, way = 0, 0
    for a, b in zip(xs, xs[1:]):
        if abs(b - a) >= WAVE_STEP:
            new = 1 if b > a else -1
            if way and new != way:
                turns += 1
            way = new
    return turns >= WAVE_TURNS and bool(xs) and max(xs) - min(xs) >= WAVE_SPAN


class Hands:
    """MediaPipe Pose Lite sur le buste découpé autour d'un visage. `look` → (côtés levés, {côté: x du poignet
    en largeurs d'épaules par rapport à l'épaule}) ou None (pas de corps, ou le corps n'est pas ce visage)."""

    dernier = None          # (repères, côté du carré en px) de la dernière image : pour l'assistant « Gestes » (lot 4)

    def __init__(self, reglages=None):
        self.r = reglages if reglages is not None else Reglages()      # seuils « bras levé » : constantes ou fichier
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        import mediapipe
        self.mp = mediapipe
        self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=face_model("pose_lite.task")), num_poses=1))

    def look(self, image, box):
        import numpy as np
        x, y, w, h = box
        side = max(320, int(10 * max(w, h)))          # assez grand et assez haut pour un bras levé (calibrage)
        cx, cy = x + w / 2, y + h / 2 + h
        x0 = int(max(0, min(image.shape[1] - side, cx - side / 2)))
        y0 = int(max(0, min(image.shape[0] - side, cy - side / 2)))
        crop = np.ascontiguousarray(image[y0:y0 + side, x0:x0 + side, ::-1])
        result = self.pose.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=crop))
        if not result.pose_landmarks:
            return None
        points = [(p.x, p.y, p.visibility) for p in result.pose_landmarks[0]]
        self.dernier = (points, side)
        nose = (x0 + points[0][0] * side, y0 + points[0][1] * side)
        if not (x - w / 2 <= nose[0] <= x + 1.5 * w and y - h / 2 <= nose[1] <= y + 1.5 * h):
            return None                                # le corps trouvé n'est pas cette personne (un coussin…)
        width = max(abs(points[11][0] - points[12][0]) * side, 1.0)
        up = raised(points, side, self.r("main_coude"), self.r("main_poignet"))
        return up, {name: (points[wrist][0] - points[shoulder][0]) * side / width
                    for name, wrist, shoulder in (("gauche", 15, 11), ("droite", 16, 12))}


HINT_REACH = 0.6                             # distance normalisée max entre la place désignée et le visage


def center(face, width=WIDTH, height=HEIGHT):
    """Centre visé, normalisé dans [-1, 1] : le NEZ (Pollen : viser les yeux fait regarder trop haut)."""
    nose = face[1]
    return nose[0] / max(width - 1, 1) * 2 - 1, nose[1] / max(height - 1, 1) * 2 - 1


class Tracker:
    """Pollen `Tracker` : acquérir la plus grande face, puis associer la plus proche, oublier après
    `max_misses` images sans elle. Pur, testable."""

    def __init__(self, min_area_frac=0.0008, max_jump=0.5, max_misses=6):
        # min_area 0,003 chez Pollen (en 320 px, à un mètre) ; au canapé (2-3 m, 640 px) un visage
        # couvre ~0,1 % de l'image. max_misses 20 à 25 i/s chez Pollen ≈ 0,8 s ; ici 6 à 3 i/s = 2 s.
        self.min_area, self.max_jump, self.max_misses = min_area_frac, max_jump, max_misses
        self.center, self.misses = None, 0
        self.hint = None           # (centre visé, pas avant, jusqu'à) : la personne qui PARLE

    def prefer(self, c, not_before, until):
        """Accrocher le visage le plus proche de `c` (centre normalisé) dans les images prises entre
        `not_before` et `until` (horloge monotone) : c'est ainsi que le corps désigne qui parle."""
        self.hint = (tuple(c), not_before, until)

    def select(self, faces, width=WIDTH, height=HEIGHT, now=None):
        if not faces:
            return self._miss()
        if self.hint is not None and now is not None:
            c, not_before, until = self.hint
            if now > until:
                self.hint = None
            elif now >= not_before:
                face = min(faces, key=lambda f: math.dist(center(f, width, height), c))
                if math.dist(center(face, width, height), c) <= HINT_REACH:
                    self.hint = None
                    self.center, self.misses = center(face, width, height), 0
                    return face
        if self.center is None:
            face = max(faces, key=lambda f: f[0][2] * f[0][3])
            if face[0][2] * face[0][3] < self.min_area * width * height:
                return self._miss()
        else:
            here = self.center
            face = min(faces, key=lambda f: (center(f, width, height)[0] - here[0]) ** 2 + (center(f, width, height)[1] - here[1]) ** 2)
            c = center(face, width, height)
            if (c[0] - here[0]) ** 2 + (c[1] - here[1]) ** 2 > self.max_jump ** 2:
                return self._miss()
        self.center, self.misses = center(face, width, height), 0
        return face

    def _miss(self):
        self.misses += 1
        if self.misses > self.max_misses:
            self.center = None
        return None


class Filter:
    """Pollen `_AdaptiveCenterFilter` : lissage du centre, plus vif quand la personne bouge."""
    ALPHA, FAST_ALPHA, MOVEMENT, DEAD_ZONE = 0.3, 0.6, 0.15, 0.02

    def __init__(self):
        self.value = self.previous = None

    def update(self, c):
        if self.value is None:
            self.value = self.previous = c
            return c
        movement = math.dist(c, self.previous)
        self.previous = c
        if math.dist(c, self.value) < self.DEAD_ZONE:
            return self.value
        a = self.FAST_ALPHA if movement > self.MOVEMENT else self.ALPHA
        self.value = (self.value[0] + a * (c[0] - self.value[0]), self.value[1] + a * (c[1] - self.value[1]))
        return self.value

    def reset(self):
        self.value = self.previous = None


def angles(c):
    """(lacet, tangage) en radians de la cible vue au centre `c`, par rapport à l'axe de la caméra.
    Lacet positif = vers SA gauche (image : x négatif = à gauche) ; tangage positif = vers le bas."""
    return math.atan(-c[0] * TAN_HALF_X), math.atan(c[1] * TAN_HALF_Y)


def place(yaw):
    """L'inverse horizontal d'`angles` : où (x normalisé) apparaît une direction `yaw` (radians, relatif à
    la caméra) ; None si elle est hors du champ."""
    x = -math.tan(yaw) / TAN_HALF_X if abs(yaw) < math.pi / 2 else 9.0
    return x if abs(x) <= 1.0 else None


FRAME_EVERY = 1.0 / FPS                      # secondes entre deux images analysées (réveillé)


class Eyes:
    """Un fil qui lit la caméra (`source` : flux go2rtc, autre flux réseau ou /dev/videoN) et garde la
    dernière observation : (heure, centre lissé ou None, nombre de visages, centres de TOUS les visages).

    Flux go2rtc (`…/api/stream.mjpeg?src=X`) + Pillow présent : on demande UNE image à la fois
    (`/api/frame.jpeg?src=X`), décodée en demi-taille (`draft`). Mesuré le 10/10 sur la machine de test : décoder le
    flux continu (10 i/s en 1280×720) coûte ~65 % d'un cœur pour n'en garder que 3, l'image par image
    ~15 %. Sinon : ffmpeg en continu, comme avant.

    `every` (secondes entre deux analyses) se change à chaud : dodo, mode éco. `exclude(centre)` écarte un
    visage (la télé). `tracker.prefer()` désigne la personne qui parle.

    `faces` (facultatif, 10/10/2026) : dossier d'empreintes de visages → `person` = le nom de la personne
    suivie (ou "inconnu"), None tant qu'on ne sait pas. Seulement en image par image (il faut l'image pleine
    taille) ; OpenCV absent = pas de noms, le suivi marche comme avant.

    `reglages` (11/10/2026, `reachy_reglages`) : les seuils de la reconnaissance ; `names_on` = « Reconnaître les
    visages » (coupé : plus aucun nom, sans arrêter la vue)."""

    names_on = True                          # valeurs de classe : aussi pour une vue créée sans __init__ (tests)
    hands_on = True                          # « Répondre à un coucou » ; se change à chaud (11/10)
    preuves, trace, nfaces = None, (), 0     # « Observer les gestes sans réagir » (11/10) : voir garder_preuve
    cameras, inconnus = None, ()             # 11/10 : les visages inconnus vont à trier dans la page (`reachy_cams`)
    animaux, animal = None, None             # 11/10 : dossier des caméras (étiquettes) ; (nom, vu à) de l'animal vu
    _objets, next_animal, animal_vues, animal_votes = None, 0.0, (), ()
    presents, next_autres = {}, 0.0          # 11/10 : {nom: vu à} de TOUTES les personnes reconnues (pas que la suivie)
    hands_tried = False

    def __init__(self, source, every=FRAME_EVERY, faces=None, hands=False, reglages=None):
        self.source = source
        self.reglages = reglages
        self.every = every
        self.faces = faces
        self.hands_on, self.hands = bool(hands), None
        self.gesture = None                  # (« coucou » | « main », côté, heure, délai) : le dernier geste vu ;
        # délai = secondes depuis la première image où le bras était levé (mesure de réactivité, 11/10)
        self.raised_seen, self.burst, self.face_full, self.gesture_ok = [], None, None, 0.0
        self.preuves = None                  # dossier : « Observer les gestes sans réagir » garde chaque geste vu (11/10)
        self.trace, self.nfaces = [], 0
        self.names = None
        self.person = None
        self.jpeg = None
        self.who_tries, self.next_who = 0, 0.0
        self.who_best = 0.0                  # 11/10 : meilleure ressemblance des essais, dite au journal si « inconnu »
        self.exclude = None
        self.running = True
        self.observation = None
        self.error = ""
        self.process = None
        self.tracker = Tracker()
        threading.Thread(target=self.loop, daemon=True).start()

    def prefer(self, c, not_before, until):
        self.tracker.prefer(c, not_before, until)

    def frame_url(self):
        """L'adresse d'une image seule, si la source est un flux MJPEG de go2rtc et Pillow présent."""
        if "/api/stream.mjpeg" not in self.source:
            return None
        try:
            import PIL.Image  # noqa: F401
        except ImportError:
            return None
        return self.source.replace("/api/stream.mjpeg", "/api/frame.jpeg")

    def latest(self):
        return self.observation

    def close(self):
        self.running = False
        if self.process:
            stop(self.process)

    def command(self):
        rate = ["-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        if self.source.startswith("/dev/"):
            return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2", "-input_format", "mjpeg",
                    "-video_size", "1280x720", "-i", self.source] + rate
        if self.source.startswith("http"):
            # MJPEG en HTTP (go2rtc /api/stream.mjpeg) : 5 % de go2rtc, quand le RTSP d'un flux MJPEG le fait
            # tourner à vide à 1,5-2 cœurs, même après la déconnexion (mesuré le 10/10, go2rtc 1.9.14).
            # -lowres 1 : le décodeur JPEG sort directement la moitié de la taille (~4 fois moins de calcul).
            return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-lowres", "1", "-f", "mjpeg", "-i", self.source] + rate
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", self.source] + rate

    def see(self, frame, detector, smooth, now):
        """Une image BGR (HEIGHT×WIDTH) → l'observation."""
        faces = detector.detect(frame)
        if self.exclude is not None:
            faces = [f for f in faces if not self.exclude(center(f))]
        face = self.tracker.select(faces, now=now)
        everyone = [center(f) for f in faces]
        self.nfaces = len(faces)
        self.identify(face, now)
        self.identifier_autres([f for f in faces if f is not face], now)
        self.watch_hands(face, now)
        if face is None:
            if self.tracker.center is None:
                smooth.reset()
            self.observation = (now, None, len(faces), everyone)
        else:
            self.observation = (now, smooth.update(center(face)), len(faces), everyone)

    def watch_hands(self, face, now):
        """Main levée sur 3 images sur 4 → rafale de WAVE_BURST s : le poignet va et vient → « coucou », sinon
        « main ». Rien sans `hands` (option coupée, MediaPipe absent, flux continu)."""
        if self.hands is None or self.jpeg is None or not self.hands_on:
            self.raised_seen, self.burst = [], None
            return
        image = self.full_image()
        if image is None:
            return
        sx, sy = image.shape[1] / WIDTH, image.shape[0] / HEIGHT
        if face is not None:
            b = face[0]
            self.face_full = ((b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy), now)
        if self.face_full is None or now - self.face_full[1] > FACE_HOLD:
            self.raised_seen, self.burst = [], None
            return
        seen = self.hands.look(image, self.face_full[0])
        if seen is None:
            return                                     # personne de fiable : ni pour, ni contre
        sides, wrists = seen
        if self.preuves is not None and self.hands.dernier is not None:
            self.trace = (list(self.trace) + [{"t": round(now, 2), "leves": sorted(sides), "visages": self.nfaces,
                                         "mesures": mesures(*self.hands.dernier)}])[-TRACE:]
        if self.burst is not None:
            side = self.burst["side"]
            self.burst["n"] += 1
            if side in sides:
                self.burst["up"] += 1
                self.burst["xs"].append(wrists[side])
            share = self.burst["up"] / self.burst["n"]
            # Le va-et-vient est déjà vu : « coucou » tout de suite, sans attendre la fin de la rafale (réponse
            # ~1 s plus tôt, mesuré sur la machine de test le 11/10). « Main » attend toujours la fin : elle ouvre le micro.
            tot = (self.burst["n"] >= WAVE_EARLY_MIN and share >= WAVE_SHARE and waving(self.burst["xs"]))
            if tot or now >= self.burst["until"]:
                kind = ("coucou" if share >= WAVE_SHARE and waving(self.burst["xs"]) else
                        "main" if share >= HOLD_SHARE else None)
                self.burst, self.raised_seen = None, []
                if kind and self.preuves is not None:
                    self.garder_preuve(kind, side, now)
                if kind and now >= self.gesture_ok:
                    delai = round(now - self.burst_from, 2) if getattr(self, "burst_from", None) is not None else None
                    self.gesture, self.gesture_ok = (kind, side, now, delai), now + GESTURE_COOLDOWN
            return
        self.raised_seen = (self.raised_seen + [sides])[-HAND_WINDOW:]
        self.raised_times = (getattr(self, "raised_times", []) + [now])[-HAND_WINDOW:]
        for side in ("droite", "gauche"):
            if sum(side in s for s in self.raised_seen) >= HAND_NEEDED:
                self.burst = {"side": side, "until": now + WAVE_BURST, "xs": [wrists[side]], "n": 1, "up": 1}
                # la première image de la fenêtre où ce bras était levé : le départ de la mesure du délai
                self.burst_from = next((t for t, s in zip(self.raised_times, self.raised_seen) if side in s), now)
                break

    def garder_preuve(self, kind, side, now):
        """Un geste vu, gardé pour l'analyse : l'image entière et les mesures des dernières images (JSON), dans un
        dossier 700, fichiers 600 ; les plus anciens partent au-delà de PREUVES_MAX. Un échec ne gêne jamais la vue."""
        try:
            dossier = Path(self.preuves)
            dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(dossier, 0o700)
            nom = time.strftime("%Y%m%d-%H%M%S") + f"-{kind}-{side}"
            nettete = None                     # variance du laplacien autour de la personne : bas = image floue
            try:
                import cv2
                import numpy as np
                image = cv2.imdecode(np.frombuffer(self.jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
                if image is not None and self.face_full is not None:
                    x, y, w, h = (int(v) for v in self.face_full[0])
                    m = max(w, h) * 3
                    zone = image[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
                    nettete = round(float(cv2.Laplacian(zone, cv2.CV_64F).var()), 1) if zone.size else None
            except ImportError:
                pass                           # sans OpenCV : la preuve, sans la netteté
            fiche = {"geste": kind, "cote": side, "heure": time.strftime("%H:%M:%S"), "nettete": nettete,
                     "visage": [round(v) for v in self.face_full[0]] if self.face_full else None,
                     "seuils": {"coude": (self.reglages or Reglages())("main_coude"),
                                "nez": (self.reglages or Reglages())("main_poignet")}, "images": self.trace}
            for suffixe, contenu in ((".jpg", self.jpeg), (".json", json.dumps(fiche, ensure_ascii=False, indent=1).encode())):
                chemin = dossier / (nom + suffixe)
                chemin.write_bytes(contenu)
                os.chmod(chemin, 0o600)
            for vieux in sorted(dossier.glob("*.json"))[:-PREUVES_MAX]:
                vieux.unlink(missing_ok=True)
                vieux.with_suffix(".jpg").unlink(missing_ok=True)
        except Exception as trouble:
            self.error = f"preuve de geste : {str(trouble)[:120]}"

    def full_image(self):
        """L'image d'origine (pleine taille, BGR), décodée depuis le dernier JPEG reçu."""
        import numpy as np
        import cv2
        return cv2.imdecode(np.frombuffer(self.jpeg, np.uint8), cv2.IMREAD_COLOR)

    def identify(self, face, now):
        """Le nom de la personne suivie : quelques essais quand un visage apparaît, puis on le garde tant
        que le suivi la garde. Rien sans `names` (dossier absent, OpenCV absent, flux continu)."""
        if self.names is None:
            return
        if getattr(self, "inconnus", ()):
            self.ranger_inconnus_si_calme(now)
        if face is None or self.tracker.center is None or not self.names_on:
            self.person, self.who_tries, self.next_who, self.who_best = None, 0, 0.0, 0.0
            return
        if (self.person is not None and self.person != "inconnu") or now < self.next_who or self.jpeg is None:
            return
        self.next_who = now + (WHO_RETRY if self.person == "inconnu" else WHO_EVERY)
        try:
            result = self.names.who(self.jpeg, face[0])
        except Exception as trouble:
            self.error = f"qui est là : {str(trouble)[:120]}"
            return
        self.who_tries += 1
        if result is not None:
            self.who_best = max(getattr(self, "who_best", 0.0), result[1])
        if result is not None and result[0] != "inconnu":
            self.person = result[0]
        elif self.who_tries >= WHO_TRIES:
            self.person = "inconnu"
        if result is not None and result[0] == "inconnu" and getattr(self, "cameras", None):
            self.garder_inconnu(face[0], now)

    def garder_inconnu(self, box, now):
        """11/10 (test local) : un visage net que le robot ne reconnaît pas est gardé (gros plan + empreinte) pour être
        trié dans la page, rubrique « Caméras », comme ceux des caméras de la maison. 12/10 : seulement un visage
        d'au moins INCONNU_TAILLE px ; les INCONNUS_MAX meilleures vues sont gardées, rangées en UN passage après
        INCONNUS_PAUSE s sans nouvel inconnu (`ranger_inconnus_si_calme`)."""
        try:
            vue = self.names.gros_plan(self.jpeg, box)
        except Exception as trouble:
            self.error = f"inconnu : {str(trouble)[:120]}"
            return
        if vue is not None and vue[3] >= INCONNU_TAILLE:
            if not self.inconnus:
                self.inconnus_debut = now
            self.inconnus_dernier = now
            vues = list(self.inconnus) + [(*vue, time.time())]
            self.inconnus = sorted(vues, key=lambda v: (v[2], v[3]), reverse=True)[:INCONNUS_MAX]

    def ranger_inconnus_si_calme(self, now):
        if getattr(self, "inconnus", ()) and (now - getattr(self, "inconnus_dernier", now) >= INCONNUS_PAUSE
                                             or now - getattr(self, "inconnus_debut", now) >= INCONNUS_DUREE):
            self.ranger_inconnus()

    def identifier_autres(self, faces, now):
        """11/10 (besoin initial : « le robot peut reconnaître plusieurs personnes en même temps ? ») : la personne suivie
        est nommée par `identify` ; les AUTRES visages sont essayés toutes les AUTRES_EVERY s (AUTRES_MAX au plus).
        `presents` = {nom: dernière fois vu} de toutes les personnes reconnues, suivie comprise."""
        presents = {n: t for n, t in dict(getattr(self, "presents", {})).items() if now - t <= PRESENT}
        if getattr(self, "person", None) not in (None, "inconnu"):
            presents[self.person] = now
        if (faces and getattr(self, "names", None) is not None and getattr(self, "names_on", False)
                and self.jpeg is not None and now >= getattr(self, "next_autres", 0.0)):
            self.next_autres = now + AUTRES_EVERY
            for f in faces[:AUTRES_MAX]:
                try:
                    resultat = self.names.who(self.jpeg, f[0])
                except Exception:
                    continue
                if resultat is not None and resultat[0] != "inconnu":
                    presents[resultat[0]] = now
        self.presents = presents

    def chercher_animal(self, now):
        """11/10 (besoin initial : « faire reconnaître le chien par le robot ») : toutes les ANIMAL_EVERY s, YOLOX cherche un
        animal dans la dernière image ; son empreinte est comparée aux étiquettes de la rubrique Caméras (vote,
        `reachy_cams.proposer_objet`). Un nom n'est mis qu'après ANIMAL_ACCORD vues d'accord. Les vues vont à
        trier (passage « robot », genre animal) quand il est parti : le chien vu au salon s'apprend aussi."""
        if not getattr(self, "animaux", None) or now < self.next_animal or self.jpeg is None:
            return
        self.next_animal = now + ANIMAL_EVERY
        try:
            import cv2
            import numpy as np
            import reachy_cams
            import reachy_objets
            if self._objets is None:
                self._objets = reachy_objets.Objets()
            image = cv2.imdecode(np.frombuffer(self.jpeg, np.uint8), cv2.IMREAD_COLOR)
            trouves = [d for d in self._objets.detecter(image, ("animal",)) if d[3][2] >= ANIMAL_MIN] if image is not None else []
            if not trouves:
                if self.animal_vues and now - self.animal_vues[-1][4 + 1] >= ANIMAL_OUBLI:
                    self.ranger_animal()
                return
            _, classe, conf, (x, y, w, h) = max(trouves, key=lambda d: d[2])
            m = int(0.1 * max(w, h))
            decoupe = image[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
            app, coul = self._objets.empreinte(decoupe)
            avis = reachy_cams.proposer_objet([{"empreinte": app, "couleur": coul}],
                                              reachy_cams.lire_etiquettes(self.animaux).get("animal", {}))
            nom = avis["nom"] or classe
            votes = [v for v in self.animal_votes if now - v[1] < ANIMAL_OUBLI] + [(nom, now)]
            self.animal_votes = votes[-5:]
            if sum(1 for v in self.animal_votes if v[0] == nom) >= ANIMAL_ACCORD:
                self.animal = (nom, now)
            k = 256 / max(decoupe.shape[:2])
            if k < 1:
                decoupe = cv2.resize(decoupe, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
            ok, jpeg = cv2.imencode(".jpg", decoupe, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                self.animal_vues = list(self.animal_vues) + [(jpeg.tobytes(), app, conf, int(w), time.time(), now,
                                                              {"couleur": coul, "classe": classe, "reconnu": avis["nom"]})]
                if len(self.animal_vues) >= INCONNUS_MAX:
                    self.ranger_animal()
        except Exception as trouble:
            self.error = f"animal : {str(trouble)[:120]}"

    def ranger_animal(self):
        vues, self.animal_vues = [v[:5] + v[6:] for v in self.animal_vues], ()
        if animal_reconnu([v[5] for v in vues if len(v) > 5]):
            return                      # 15/10 (choix initial) : un animal reconnu n'est plus mis à trier
        vues = [v[:5] + ({k: x for k, x in v[5].items() if k != "reconnu"},) if len(v) > 5 else v for v in vues]
        if vues and getattr(self, "animaux", None):
            try:
                import reachy_cams
                reachy_cams.ecrire_passage(self.animaux, "robot", vues, genre="animal")
            except Exception as trouble:
                self.error = f"animal non rangé : {str(trouble)[:120]}"

    def ranger_inconnus(self):
        if not getattr(self, "inconnus", ()) or not getattr(self, "cameras", None):
            self.inconnus = ()
            return
        vues, self.inconnus = list(self.inconnus), ()
        try:
            import reachy_cams
            reachy_cams.ecrire_passage(self.cameras, "robot", vues)
        except Exception as trouble:
            self.error = f"inconnus non rangés : {str(trouble)[:120]}"

    def snapshot(self, url):
        """Une image de go2rtc, décodée directement en 640×360 (Pillow `draft` : réduction dans le JPEG)."""
        import io
        import numpy as np
        from PIL import Image
        with urllib.request.urlopen(url, timeout=5) as answer:
            data = answer.read()
        self.jpeg = data                          # l'image d'origine, pour reconnaître un visage (`identify`)
        image = Image.open(io.BytesIO(data))
        image.draft("RGB", (WIDTH, HEIGHT))
        image = image.convert("RGB")
        if image.size != (WIDTH, HEIGHT):
            image = image.resize((WIDTH, HEIGHT))
        return np.ascontiguousarray(np.asarray(image)[:, :, ::-1])

    def loop(self):
        try:
            import numpy as np
            detector = FaceDetector()
        except Exception as trouble:          # numpy, onnxruntime ou le modèle absents : pas de vue
            self.error = f"vue indisponible : {str(trouble)[:120]}"
            return
        smooth = Filter()
        size = WIDTH * HEIGHT * 3
        url = self.frame_url()
        if self.faces and url:
            try:
                self.names = FaceNames(self.faces, self.reglages)
            except Exception as trouble:      # OpenCV ou ses modèles absents : le suivi seul, comme avant
                self.error = f"noms indisponibles : {str(trouble)[:120]}"
        while self.running:
            if self.hands_on and url and not self.hands_tried:
                # Ici, pas avant la boucle (11/10) : « Répondre à un coucou » peut s'allumer à chaud.
                self.hands_tried = True
                try:
                    self.hands = Hands(self.reglages)
                except Exception as trouble:  # MediaPipe ou son modèle absents : pas de gestes, le reste marche
                    self.error = f"gestes indisponibles : {str(trouble)[:120]}"
            if url:
                start = time.monotonic()
                try:
                    frame = self.snapshot(url)
                    self.see(frame, detector, smooth, time.monotonic())
                    self.chercher_animal(time.monotonic())
                    self.error = ""
                except Exception as trouble:
                    self.error = f"image : {str(trouble)[:120]}"
                    self.observation = None
                    time.sleep(5)
                pause = BURST_EVERY if self.burst is not None else self.every   # rafale : coucou ?
                time.sleep(max(0.0, pause - (time.monotonic() - start)))
                continue
            try:
                self.process = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                last = 0.0
                while self.running:
                    data = self.process.stdout.read(size)
                    if len(data) < size:
                        break
                    now = time.monotonic()
                    if now - last < self.every - 0.05:   # ralenti (dodo, éco) : on lit sans analyser
                        continue
                    last = now
                    self.see(np.frombuffer(data, np.uint8).reshape(HEIGHT, WIDTH, 3), detector, smooth, now)
                stop(self.process)
                self.error = "caméra muette, nouvel essai dans 10 s"
            except OSError as trouble:
                self.error = f"ffmpeg : {trouble}"
            self.observation = None
            for _ in range(100):
                if not self.running:
                    return
                time.sleep(0.1)


def enroll(source, folder, name, images=20, every=1.0, need=5, progress=None):
    """Enrôle un visage : `images` vues de `source` (flux go2rtc), le visage le plus net de chacune, la
    MOYENNE de leurs empreintes dans `<folder>/<name>.json` (600). Aucune image n'est gardée.
    Une seule personne face au robot pendant l'enrôlement. → nombre de vues retenues.
    # lot 5 (11/10) : `progress(images_faites, vues_retenues)`, facultatif, appelé après chaque image (la page)."""
    import json
    import cv2
    import numpy as np
    url = source.replace("/api/stream.mjpeg", "/api/frame.jpeg")
    names = FaceNames(folder)
    kept = []
    for index in range(images):
        with urllib.request.urlopen(url, timeout=5) as answer:
            image = cv2.imdecode(np.frombuffer(answer.read(), np.uint8), cv2.IMREAD_COLOR)
        v = names.feature(image) if image is not None else None
        if v is not None:
            kept.append(v)
        if progress is not None:           # lot 5 : la page montre l'avancement
            progress(index + 1, len(kept))
        time.sleep(every)
    if len(kept) < need:
        raise RuntimeError(f"seulement {len(kept)} vue(s) nette(s) sur {images} : visage trop petit, flou ou de profil")
    mean = np.mean(kept, axis=0)
    mean /= np.linalg.norm(mean)
    Path(folder).mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = Path(folder) / f"{name}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"nom": name, "modele": "sface_2021dec", "vues": len(kept),
                                     "empreinte": [round(float(x), 6) for x in mean]}))
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return len(kept)


if __name__ == "__main__":
    import sys
    # python3 reachy_vue.py enroler <flux go2rtc> <dossier d'empreintes> <nom>
    if len(sys.argv) == 5 and sys.argv[1] == "enroler":
        print(f"{sys.argv[4]} : {enroll(sys.argv[2], sys.argv[3], sys.argv[4])} vues retenues")
    else:
        print("usage : reachy_vue.py enroler <flux go2rtc> <dossier d'empreintes> <nom>")
        sys.exit(2)
