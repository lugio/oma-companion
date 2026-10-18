#!/usr/bin/env python3
"""Les animaux et les véhicules vus par les caméras de la maison (11/10/2026).

besoin initial : reconnaître un chien, sa voiture, la voiture du facteur… Deux modèles d'opencv_zoo
(même source officielle que les visages, téléchargés une fois, vérifiés par leur empreinte complète) :
- YOLOX-S (Apache-2.0, classes COCO) repère les chiens, chats et véhicules dans l'image HD ;
- MobileNetV2 (Apache-2.0) donne une empreinte d'APPARENCE de la découpe (1000 sorties ImageNet, normées),
  complétée par un histogramme de couleur HSV (la voiture jaune du facteur).
La ressemblance de deux découpes = 0,7 × apparence + 0,3 × couleur (`ressemblance`, pure, testable).

Mesuré le 11/10 sur la machine de test : YOLOX 95 ms par image HD, un chien vu dans les 5 passages « animal » de la
terrasse, une voiture dans les 6 passages « véhicule » de la sonnette ; les 5 passages de chien se ressemblent
(apparence 0,65-0,88), chien contre voiture 0,26. L'apparence seule ne distingue pas deux voitures : ce sont
les étiquettes saisies (et plus tard les plaques) qui le feront.
"""
import numpy as np

MODELES = {
    "yolox.onnx": ("https://github.com/opencv/opencv_zoo/raw/main/models/object_detection_yolox/"
                   "object_detection_yolox_2022nov.onnx",
                   "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"),
    "mobilenetv2.onnx": ("https://github.com/opencv/opencv_zoo/raw/main/models/image_classification_mobilenet/"
                         "image_classification_mobilenetv2_2022apr.onnx",
                         "c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5"),
    # 12/10 : les plaques (projets fast-alpr d'ankandrew, MIT) : détecteur YOLOv9-t 384 (open-image-models) et
    # lecture cct-s-v2-global (fast-plate-ocr, 65 pays dont la France).
    "plaques_detecteur.onnx": ("https://github.com/ankandrew/open-image-models/releases/download/assets/"
                               "yolo-v9-t-384-license-plates-end2end.onnx",
                               "888397b96d761c89db40bc9c305838e8652660f5e282c2cadebbe8d2951a77a8"),
    "plaques_lecture.onnx": ("https://github.com/ankandrew/cnn-ocr-lp/releases/download/arg-plates/cct_s_v2_global.onnx",
                             "384bbbd2cea3ef54761d3df70822ef3a349ee1a112aeafddbe0e3ba06bc6e47b"),
}
# Classes COCO gardées → (genre, nom affiché).
CLASSES = {15: ("animal", "chat"), 16: ("animal", "chien"),
           2: ("vehicule", "voiture"), 3: ("vehicule", "moto"), 5: ("vehicule", "bus"), 7: ("vehicule", "camion")}
COTE = 640                  # entrée de YOLOX
SEUIL = 0.5                 # confiance minimale d'un objet
APPARENCE, COULEUR = 0.7, 0.3


def ressemblance(a_app, a_coul, b_app, b_coul):
    """Ressemblance de deux découpes (empreintes déjà normées). Pure."""
    app = sum(float(x) * float(y) for x, y in zip(a_app, b_app))
    coul = sum(float(x) * float(y) for x, y in zip(a_coul, b_coul)) if a_coul and b_coul else app
    return APPARENCE * app + COULEUR * coul


class Objets:
    """YOLOX + MobileNetV2 sur OpenCV DNN. Un objet par fil (OpenCV ne se partage pas entre fils)."""

    def __init__(self):
        import cv2
        import reachy_vue
        self.cv2 = cv2
        self.yolox = cv2.dnn.readNet(reachy_vue.face_model("yolox.onnx", MODELES))
        self.mobilenet = cv2.dnn.readNet(reachy_vue.face_model("mobilenetv2.onnx", MODELES))
        grilles, pas = [], []
        for st in (8, 16, 32):
            n = COTE // st
            gy, gx = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
            grilles.append(np.stack((gx, gy), 2).reshape(-1, 2))
            pas.append(np.full((n * n, 1), st))
        self.grilles, self.pas = np.concatenate(grilles), np.concatenate(pas)

    def detecter(self, image, genres=("animal", "vehicule")):
        """[(genre, classe, confiance, (x, y, l, h))] dans `image` (BGR, pleine taille)."""
        cv2 = self.cv2
        h, w = image.shape[:2]
        r = min(COTE / h, COTE / w)
        cadre = np.full((COTE, COTE, 3), 114, np.uint8)
        cadre[:int(h * r), :int(w * r)] = cv2.resize(image, (int(w * r), int(h * r)))
        self.yolox.setInput(cv2.dnn.blobFromImage(cadre))
        sortie = self.yolox.forward()[0]
        xy = (sortie[:, :2] + self.grilles) * self.pas
        lh = np.exp(sortie[:, 2:4]) * self.pas
        scores = sortie[:, 4:5] * sortie[:, 5:]
        classes, conf = scores.argmax(1), scores.max(1)
        gardes = [i for i in np.where(conf > SEUIL)[0] if classes[i] in CLASSES and CLASSES[classes[i]][0] in genres]
        boites = [[float((xy[i, 0] - lh[i, 0] / 2) / r), float((xy[i, 1] - lh[i, 1] / 2) / r),
                   float(lh[i, 0] / r), float(lh[i, 1] / r)] for i in gardes]
        if not gardes:
            return []
        retenus = np.array(cv2.dnn.NMSBoxes(boites, [float(conf[i]) for i in gardes], SEUIL, 0.45)).ravel()
        return [(*CLASSES[classes[gardes[j]]], float(conf[gardes[j]]), tuple(int(v) for v in boites[j])) for j in retenus]

    def empreinte(self, decoupe):
        """(apparence normée, couleur normée) d'une découpe BGR."""
        cv2 = self.cv2
        blob = cv2.dnn.blobFromImage(cv2.cvtColor(decoupe, cv2.COLOR_BGR2RGB), 1 / 255.0, (224, 224))
        blob = (blob - np.array([0.485, 0.456, 0.406]).reshape(1, 3, 1, 1)) / np.array([0.229, 0.224, 0.225]).reshape(1, 3, 1, 1)
        self.mobilenet.setInput(blob.astype(np.float32))
        app = self.mobilenet.forward().ravel()
        hsv = cv2.cvtColor(decoupe, cv2.COLOR_BGR2HSV)
        coul = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256]).ravel()
        return ((app / (np.linalg.norm(app) or 1)).round(6).tolist(),
                (coul / (np.linalg.norm(coul) or 1)).round(6).tolist())


# --- Les plaques (12/10/2026) ----------------------------------------------------------------------------
# Besoin initial (« avance sur les plaques »). Mesuré le 12/10 sur 12 passages de la sonnette (fast-alpr 0.4.0,
# même modèles) : 5 plaques sûres (même texte sur 80-92 % des images, confiance 0,96-0,99), toutes ≥ 60 px de
# large ; en dessous de 40 px, rien de fiable. Le modèle « européen » lit moins bien (0,75-0,80). Les deux
# modèles tournent ici avec onnxruntime (déjà là pour les visages), sans la bibliothèque fast-alpr :
# pré- et post-traitement repris de son code (letterbox 114, RGB/255 ; lecture RGB 128×64, 10 cases).
PLAQUE_DETECTION = 0.4      # confiance minimale du détecteur (défaut de fast-alpr)
PLAQUE_LARGEUR = 60         # px : plaque plus étroite = pas lue
PLAQUE_CONFIANCE = 0.9      # confiance moyenne des caractères pour retenir une lecture
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
CASES = 10


def lire_sortie(sortie):
    """Sortie brute du lecteur (CASES × len(ALPHABET) probabilités) → (texte, confiance moyenne). Pure."""
    p = np.asarray(sortie, np.float32).reshape(CASES, len(ALPHABET))
    texte = "".join(ALPHABET[i] for i in p.argmax(1))
    garde = len(texte.rstrip("_"))
    conf = float(p.max(1)[:garde].mean()) if garde else 0.0
    return texte.rstrip("_"), conf


class Plaques:
    """Détecteur + lecteur de plaques, sur onnxruntime. Un objet par fil."""

    def __init__(self):
        import cv2
        import onnxruntime as ort
        import reachy_vue
        self.cv2 = cv2
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2                 # la machine de test sert aussi la voix
        self.detecteur = ort.InferenceSession(reachy_vue.face_model("plaques_detecteur.onnx", MODELES), options,
                                              providers=["CPUExecutionProvider"])
        self.lecteur = ort.InferenceSession(reachy_vue.face_model("plaques_lecture.onnx", MODELES), options,
                                            providers=["CPUExecutionProvider"])
        entree = self.detecteur.get_inputs()[0]
        self.cote = int(entree.shape[2]) if isinstance(entree.shape[2], int) else 384
        self.sortie_lecteur = next((o.name for o in self.lecteur.get_outputs() if o.name != "region"),
                                   self.lecteur.get_outputs()[0].name)

    def trouver(self, image):
        """[(x1, y1, x2, y2, confiance)] des plaques dans `image` (BGR)."""
        cv2 = self.cv2
        h, w = image.shape[:2]
        r = min(self.cote / h, self.cote / w)
        nw, nh = int(round(w * r)), int(round(h * r))
        dw, dh = (self.cote - nw) / 2, (self.cote - nh) / 2
        cadre = cv2.copyMakeBorder(cv2.resize(image, (nw, nh)), int(round(dh - 0.1)), int(round(dh + 0.1)),
                                   int(round(dw - 0.1)), int(round(dw + 0.1)), cv2.BORDER_CONSTANT, value=(114, 114, 114))
        x = (cadre.transpose(2, 0, 1)[::-1] / 255.0).astype(np.float32)[None]
        sortie = np.asarray(self.detecteur.run(None, {self.detecteur.get_inputs()[0].name: x})[0]).reshape(-1, 7)
        return [((b[1] - dw) / r, (b[2] - dh) / r, (b[3] - dw) / r, (b[4] - dh) / r, float(b[6]))
                for b in sortie if b[6] >= PLAQUE_DETECTION]

    def lire(self, decoupe):
        """La plaque la plus sûre d'une découpe de véhicule (BGR) → (texte, confiance, largeur px) ou None."""
        cv2 = self.cv2
        meilleure = None
        for x1, y1, x2, y2, _ in self.trouver(decoupe):
            largeur = x2 - x1
            if largeur < PLAQUE_LARGEUR:
                continue
            coupe = decoupe[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]
            if not coupe.size:
                continue
            entree = cv2.resize(cv2.cvtColor(coupe, cv2.COLOR_BGR2RGB), (128, 64), interpolation=cv2.INTER_LINEAR)
            texte, conf = lire_sortie(self.lecteur.run([self.sortie_lecteur], {self.lecteur.get_inputs()[0].name:
                                                                               entree[None].astype(np.uint8)})[0])
            if len(texte) >= 4 and conf >= PLAQUE_CONFIANCE and (meilleure is None or conf > meilleure[1]):
                meilleure = (texte, round(conf, 3), int(largeur))
        return meilleure
