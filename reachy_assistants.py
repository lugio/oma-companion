#!/usr/bin/env python3
"""Les assistants de calibrage de la page de réglages, pas à pas (11/10/2026, lot 4).

Spec `docs/superpowers/specs/2026-10-11-reachy-page-reglages.md` § 4 bis. Un MOTEUR commun, trois assistants :

- **Toucher** : la position réelle des 7 moteurs, 10 fois par seconde (la méthode de `mesure_toucher.sh`, 10/10).
  Écrit `body_press` et `body_push`.
- **Pièce** : la direction de la parole par les micros de la tête, tête immobile (la méthode de `mesure_son.sh`,
  10/10). Écrit `ignorer`, `repere_canape` et `repere_tele`.
- **Gestes** : la pose du buste vue par la caméra (la méthode de `calib_mains.py` et `calib_regle.py`, 11/10).
  Écrit `main_coude` et `main_poignet`.

Les mesures se font DANS le corps, pendant son « mode mesure » (`reachy.Body.enter_measure_mode` : il ne bouge
plus et ne réagit plus, mais la page continue de tourner) — jamais par un script externe, et le corps n'est plus
arrêté. Chaque assistant a trois pièces :

- une `Mesure` PURE (aucune entrée-sortie, testable avec des échantillons inventés) : elle range les
  échantillons étape par étape, dit si la mesure est « suffisante », et propose le résultat (Actuel / Proposé) ;
- un `Capteur` : lit le robot, les micros ou la caméra, et rend des échantillons ;
- une `Definition` : titre, consignes, ce qui est mesuré, ce qui est écrit.

Le `Moteur` (un par corps) tient UNE session à la fois : préparation (le corps finit son geste), étapes
(mesure en direct, « C'est fait » seulement une fois la mesure suffisante), résultat, puis « Appliquer »
(écriture par le schéma `reachy_reglages` : validation, sauvegarde de `vivant.json`, écriture atomique, appliquée
à chaud) ou « Annuler » (rien n'est changé). Le mode mesure se lève à la fin des mesures, à l'annulation, au bout
de `reachy.MEASURE_MAX` secondes, ou si quelqu'un parle au robot.

Aucune dépendance : bibliothèque standard.
"""
import math
import threading
import time
import weakref
from dataclasses import dataclass

import reachy
import reachy_reglages
import reachy_vue

PERIODE = 0.1                 # secondes entre deux lectures du capteur (les capteurs lents fixent la leur)
PREPARATION_MAX = 20.0        # secondes laissées au corps pour finir son geste avant la mesure
RESULTAT_VIE = 1800.0         # un résultat plus vieux que ça n'est plus appliqué : mesurer de nouveau
ERREURS_MAX = 30              # lectures ratées de suite avant d'abandonner (3 s à 10 lectures par seconde)


class Refus(Exception):
    """L'assistant ne peut pas faire ce qu'on lui demande maintenant (message en français, pour la page)."""


# --- Petits outils d'affichage (virgule française, vrai signe moins) ----------------------------------------
def fr(x, decimales=1):
    texte = f"{abs(x):.{decimales}f}".replace(".", ",")
    return ("−" if x < 0 and float(f"{abs(x):.{decimales}f}") != 0 else "") + texte


def deg(x):
    return ("−" if x < 0 else "+" if x > 0 else "") + f"{abs(round(x))}°"


def mediane(valeurs):
    ordre = sorted(valeurs)
    n = len(ordre)
    return ordre[n // 2] if n % 2 else (ordre[n // 2 - 1] + ordre[n // 2]) / 2


def ecart_median(valeurs):
    """L'écart absolu médian : une dispersion qui ignore les valeurs aberrantes (la télé « parle » à −90° de temps en temps)."""
    m = mediane(valeurs)
    return mediane([abs(v - m) for v in valeurs])


def decimales_de(cle):
    pas = float(reachy_reglages.PAR_CLE[cle].get("pas", 1))
    return 0 if pas.is_integer() else len(repr(pas).split(".")[1])


def affiche(cle, valeur):
    """Une valeur d'un réglage, comme la page la montre."""
    entree = reachy_reglages.PAR_CLE[cle]
    if entree["type"] == "secteurs":
        return " ; ".join(f"{deg(a)} à {deg(b)}" for a, b in valeur) if valeur else "aucune"
    unite = entree.get("unite", "")
    nombre = fr(valeur, decimales_de(cle))
    return nombre if not unite else nombre + unite if unite.startswith("°") else f"{nombre} {unite}"


def arrondi(cle, valeur):
    """Dans les bornes du schéma et au pas du réglage."""
    entree = reachy_reglages.PAR_CLE[cle]
    valeur = max(entree["min"], min(entree["max"], valeur))
    return reachy_reglages._arrondi(valeur, entree)


def ligne(cle, actuel, propose):
    return {"cle": cle, "libelle": reachy_reglages.PAR_CLE[cle]["intitule"], "actuel": affiche(cle, actuel),
            "propose": affiche(cle, propose), "change": actuel != propose}


# --- La mesure : pure --------------------------------------------------------------------------------------
class Mesure:
    """Range les échantillons, étape par étape. Aucune entrée-sortie : testable avec des échantillons inventés.

    `actuel(cle)` → la valeur du réglage dans l'unité de la page. Une étape a un état (`etat`) : mesure
    suffisante ou non, une phrase de mesure en direct, un avancement de 0 à 1, une alerte éventuelle.
    `resultat()` n'est appelé qu'une fois toutes les étapes validées."""

    ETAPES = ()               # (clé, consigne) par étape

    def __init__(self, actuel):
        self.actuel = actuel
        self.d = {}

    def commencer(self, i, now):
        """(Re)commence l'étape `i` : tout ce qu'elle avait mesuré est oublié."""
        raise NotImplementedError

    def ajouter(self, i, echantillon, now):
        raise NotImplementedError

    def etat(self, i, now):
        raise NotImplementedError

    def resultat(self):
        raise NotImplementedError

    @staticmethod
    def etat_de(suffisante, texte, progres, alerte=""):
        return {"suffisante": bool(suffisante), "texte": texte, "progres": round(max(0.0, min(1.0, progres)), 2),
                "alerte": alerte}


# =========================================================================================================
# Toucher
# =========================================================================================================
class MesureToucher(Mesure):
    """Où sont les 7 moteurs (corps, puis les 6 de la tête), en degrés, 10 fois par seconde. Repères du 10/10 :
    bruit 0,09° ; main posée 0,8-1° ; tête poussée 2-8° (et elle reste où on l'a mise) ; corps tourné 3,7°."""

    ETAPES = (
        ("repos", "Ne touche pas le robot pendant 5 secondes."),
        ("posee", "Pose doucement la main sur sa tête, 3 secondes, puis retire-la."),
        ("poussee", "Pousse doucement sa tête sur le côté, puis lâche."),
        ("corps", "Tourne doucement son corps de quelques degrés, puis lâche."),
    )
    REPOS_S = 5.0             # secondes d'immobilité pour mesurer le bruit
    BRUIT_MAX = 0.4           # degrés : au-delà, le robot n'est pas au calme (on le touche, la table bouge)
    REPERE_S = 0.5            # secondes au début d'une étape pour prendre la position de départ
    POSEE_S = 3.0             # secondes de main posée
    CONTACT_MIN = 0.25        # degrés : en dessous, ce n'est pas un contact même si le bruit est minuscule
    POUSSEE_MIN = 1.2         # degrés : une poussée dépasse au moins ça (et 1,5 fois la main posée)
    CORPS_MIN = 1.0           # degrés : un corps tourné
    IMMOBILE = 0.2            # degrés (BODY_STILL) : « ça ne bouge plus »
    IMMOBILE_S = 0.5          # secondes (BODY_SETTLE)

    def commencer(self, i, now):
        self.d[i] = {"debut": now, "vus": [], "ref": None, "ok": False, "valeur": None, "pic": 0.0,
                     "course": None, "ecart": 0.0}

    @staticmethod
    def _ecarts(joints, ref):
        return abs(joints[0] - ref[0]), max(abs(a - b) for a, b in zip(joints[1:], ref[1:]))

    def _repere(self, d, joints, now):
        """La position de départ : la médiane des relevés du premier demi-seconde. → vrai quand elle est prise."""
        if d["ref"] is not None:
            return True
        d["vus"].append((now, joints))
        if now - d["debut"] < self.REPERE_S:
            return False
        d["ref"] = [mediane([v[1][k] for v in d["vus"]]) for k in range(7)]
        d["vus"] = []
        return True

    def _immobile(self, d, joints, now):
        d["vus"] = [v for v in d["vus"] if now - v[0] <= self.IMMOBILE_S + 0.1] + [(now, joints)]
        premier = d["vus"][0][0]
        return now - premier >= self.IMMOBILE_S - 0.05 and all(
            max(v[1][k] for v in d["vus"]) - min(v[1][k] for v in d["vus"]) <= self.IMMOBILE for k in range(7))

    def ajouter(self, i, echantillon, now):
        d, joints = self.d[i], echantillon["moteurs"]
        if i == 0:                                     # le bruit : les 5 dernières secondes, médiane comme repère
            if d["ok"]:
                return
            d["vus"] = [v for v in d["vus"] if now - v[0] <= self.REPOS_S] + [(now, joints)]
            fenetre = d["vus"]
            if now - fenetre[0][0] < self.REPOS_S - 0.15:
                return
            milieu = [mediane([v[1][k] for v in fenetre]) for k in range(7)]
            bruit = max(max(abs(a - b) for a, b in zip(v[1], milieu)) for v in fenetre)
            d["ecart"] = bruit
            if bruit <= self.BRUIT_MAX:
                d["ok"], d["valeur"], d["ref"] = True, bruit, milieu
            return
        if d["ok"] or not self._repere(d, joints, now):
            return
        corps, tete = self._ecarts(joints, d["ref"])
        bruit = self.d[0]["valeur"]
        if i == 1:                                     # une main posée : un écart tenu 3 s, ni bruit ni poussée
            d["ecart"] = tete
            d["pic"] = max(d["pic"], tete)
            seuil = max(2 * bruit, self.CONTACT_MIN)
            if tete < seuil:
                d["course"] = None
                return
            if d["course"] is None:
                d["course"] = {"debut": now, "ecarts": []}
            d["course"]["ecarts"].append(tete)
            if now - d["course"]["debut"] >= self.POSEE_S:
                d["ok"], d["valeur"] = True, mediane(d["course"]["ecarts"])
            return
        grandeur = tete if i == 2 else corps
        d["ecart"] = grandeur
        d["pic"] = max(d["pic"], grandeur)
        minimum = (max(self.POUSSEE_MIN, 1.5 * self.d[1]["valeur"]) if i == 2 else self.CORPS_MIN)
        if d["pic"] >= minimum and self._immobile(d, joints, now):
            d["ok"], d["valeur"] = True, d["pic"]

    def etat(self, i, now):
        d = self.d[i]
        if i == 0:
            if d["ok"]:
                return self.etat_de(True, f"{len(d['vus'])} relevés · bruit des moteurs : {fr(d['valeur'], 2)}° au plus", 1.0)
            if not d["vus"]:
                return self.etat_de(False, "j'attends les premiers relevés…", 0.0)
            reste = d["ecart"] > self.BRUIT_MAX
            duree = d["vus"][-1][0] - d["vus"][0][0]
            if reste:
                return self.etat_de(False, f"le robot bouge ({fr(d['ecart'], 2)}°)", 0.0,
                                    "Le robot n'est pas au calme : ne le touche pas, et évite les secousses sur la table.")
            return self.etat_de(False, f"{len(d['vus'])} relevés · immobile depuis {fr(duree)} s sur {fr(self.REPOS_S, 0)}",
                                duree / self.REPOS_S)
        if d["ref"] is None:
            return self.etat_de(False, "je prends mes repères… ne touche pas encore le robot", 0.0)
        if i == 1:
            if d["ok"]:
                return self.etat_de(True, f"main posée : écart {fr(d['valeur'], 2)}° tenu {fr(self.POSEE_S, 0)} s", 1.0,
                                    "Ça ressemble plutôt à une poussée : pose juste la main, sans appuyer." if d["valeur"] >= 2.0 else "")
            tenu = 0.0 if d["course"] is None else now - d["course"]["debut"]
            return self.etat_de(False, f"écart {fr(d['ecart'], 2)}° · tenu {fr(tenu)} s sur {fr(self.POSEE_S, 0)}",
                                tenu / self.POSEE_S)
        unite = "tête" if i == 2 else "corps"
        if d["ok"]:
            return self.etat_de(True, f"{unite} : écart de {fr(d['valeur'], 1)}° au plus, puis immobile", 1.0)
        return self.etat_de(False, f"{unite} : écart {fr(d['ecart'], 1)}° (pic {fr(d['pic'], 1)}°)",
                            0.5 if d["pic"] >= 0.5 else 0.0)

    def resultat(self):
        bruit, posee, poussee, corps = (self.d[k]["valeur"] for k in range(4))
        press, push = self.actuel("body_press"), self.actuel("body_push")
        # Un seuil convient quand il tombe nettement entre ce qu'il doit séparer : on n'y touche pas.
        press_ok = 3 * bruit <= press <= 0.8 * posee
        push_ok = 1.2 * posee <= push <= 0.8 * poussee
        # Les étapes garantissent déjà bruit ≤ 0,4° < main posée (≥ 2 fois le bruit) < poussée (≥ 1,5 fois la main posée).
        propose_press = press if press_ok else arrondi("body_press", (bruit + posee) / 2)
        propose_push = push if push_ok else arrondi("body_push", (posee + poussee) / 2)
        if propose_push <= propose_press:
            propose_push = arrondi("body_push", propose_press + 0.5)
        corps_ok = corps >= propose_push
        valeurs = f"Bruit {fr(bruit, 2)}° < main posée {fr(posee, 1)}° < poussée {fr(poussee, 1)}°"
        if not corps_ok:
            ton, titre = "warn", "Le corps tourné serait lu comme une caresse."
            texte = (f"{valeurs}. Le corps tourné n'a bougé que de {fr(corps, 1)}°, sous la poussée proposée "
                     f"({fr(propose_push, 1)}°) : il ne serait pas reconnu. Tourne-le un peu plus franchement.")
        elif propose_press == press and propose_push == push:
            ton, titre = "ok", "Les réglages actuels conviennent."
            texte = f"{valeurs} : les deux seuils tombent bien entre."
        else:
            ton, titre = "ok", "Des seuils mieux placés sont proposés."
            texte = f"{valeurs} : les seuils sont placés entre ces mesures."
        changements = {k: v for k, v in (("body_press", propose_press), ("body_push", propose_push))
                       if v != self.actuel(k)}
        return {"ton": ton, "titre": titre, "texte": texte,
                "lignes": [ligne("body_press", press, propose_press), ligne("body_push", push, propose_push)],
                "ecrit": ["vivant.json — main posée, poussée"], "changements": changements}


# =========================================================================================================
# Pièce
# =========================================================================================================
class MesurePiece(Mesure):
    """La direction de la parole (degrés, repère du socle), tête immobile : la médiane de toutes les mesures où la
    carte entend une parole. Cas réel du 10/10 : télé −35°, canapé −25° (à 10° : dans le même axe)."""

    ETAPES = (
        ("tele", "Allume la télé sur une émission où l'on parle. Personne ne parle dans la pièce, pendant 20 secondes."),
        ("canape", "Éteins la télé. Parle normalement depuis le canapé, pendant 10 secondes."),
    )
    DUREES = (20.0, 10.0)
    MINIMUM = (8, 6)              # mesures de parole nécessaires (une toutes les 0,2 s quand on parle)
    MARGE = (10, 20)              # degrés de part et d'autre de la médiane d'un secteur ignoré : au moins, au plus
    SEPARATION = 2 * reachy.SPEAKER_MATCH     # en dessous, ignorer la télé ferait ignorer le canapé
    MARGE_CANAPE = 10             # degrés de part et d'autre du repère « canapé »

    def commencer(self, i, now):
        self.d[i] = {"debut": now, "yaws": []}

    def ajouter(self, i, echantillon, now):
        self.d[i]["yaws"].append(echantillon["yaw"])

    def etat(self, i, now):
        d = self.d[i]
        n, duree, minimum = len(d["yaws"]), self.DUREES[i], self.MINIMUM[i]
        ecoule = now - d["debut"]
        suffisante = ecoule >= duree and n >= minimum
        if not n:
            texte, alerte = "aucune parole entendue pour l'instant", ""
        else:
            texte = f"{n} mesure{'s' if n > 1 else ''} de parole · vers {deg(mediane(d['yaws']))}"
            alerte = ""
        if ecoule >= duree and n < minimum:
            alerte = "Pas assez de parole entendue : parle plus fort ou plus près du robot (ou monte le son de la télé)."
        return self.etat_de(suffisante, texte + (" (médiane)" if suffisante else ""),
                            min(ecoule / duree, n / minimum), alerte)

    def _marge(self, yaws):
        ecart = 2 * 1.4826 * ecart_median(yaws)
        return int(max(self.MARGE[0], min(self.MARGE[1], round(ecart))))

    @staticmethod
    def _fusion(secteurs):
        """Les secteurs qui se touchent ne font plus qu'un."""
        sortie = []
        for a, b in sorted(secteurs):
            if sortie and a <= sortie[-1][1]:
                sortie[-1][1] = max(sortie[-1][1], b)
            else:
                sortie.append([a, b])
        return sortie

    def resultat(self):
        tele_yaws, canape_yaws = self.d[0]["yaws"], self.d[1]["yaws"]
        tele, canape = mediane(tele_yaws), mediane(canape_yaws)
        distance = abs(tele - canape)
        borne = lambda x: int(max(-180, min(180, round(x))))
        marge_tele, marge_canape = self._marge(tele_yaws), self.MARGE_CANAPE
        repere_tele = [[borne(tele - marge_tele), borne(tele + marge_tele)]]
        repere_canape = [[borne(canape - marge_canape), borne(canape + marge_canape)]]
        actuel = [list(s) for s in self.actuel("ignorer")]
        # Un secteur déjà ignoré qui contient le canapé le ferait ignorer lui aussi : il disparaît toujours.
        garde = [s for s in actuel if not (s[0] <= canape <= s[1])]
        collision = distance < self.SEPARATION
        propose = garde if collision else self._fusion(garde + repere_tele)
        if len(propose) > reachy_reglages.SECTEURS_MAX:
            propose = garde
        if collision:
            ton, titre = "warn", "La télé et le canapé sont dans le même axe."
            texte = (f"Télé à {deg(tele)}, canapé à {deg(canape)} : {round(distance)}° d'écart seulement. Ignorer la télé "
                     "ferait aussi ignorer le canapé. Proposé : ne pas ignorer cette direction. Pour pouvoir ignorer la "
                     "télé, il faudrait déplacer le robot.")
        else:
            ton, titre = "ok", "La télé et le canapé sont bien séparés."
            texte = (f"Télé à {deg(tele)}, canapé à {deg(canape)} : {round(distance)}° d'écart. La télé peut être ignorée "
                     f"sans perdre le canapé (secteur de {deg(tele - marge_tele)} à {deg(tele + marge_tele)}).")
        voulus = {"ignorer": propose, "repere_canape": repere_canape, "repere_tele": repere_tele}
        changements = {k: v for k, v in voulus.items() if v != self.actuel(k)}
        return {"ton": ton, "titre": titre, "texte": texte,
                "lignes": [ligne(k, self.actuel(k), v) for k, v in voulus.items()],
                "ecrit": ["vivant.json — directions ignorées, repères"], "changements": changements}


# =========================================================================================================
# Gestes
# =========================================================================================================
def mesures_bras(points, taille, poignets):
    """Les deux mesures de la règle « bras levé » pour chaque côté, en largeurs d'épaules (`reachy_vue.raised`) :
    `coude` = le coude au-dessus de l'épaule, `nez` = le poignet au-dessus du nez ; et si le coude et le poignet
    sont assez visibles pour que la règle les croie. `points` = repères MediaPipe (x, y, visibilité), `poignets` =
    {côté: x du poignet en largeurs d'épaules} (ce que rend `Hands.look`). Pure."""
    largeur = max(abs(points[11][0] - points[12][0]) * taille, 1.0)
    nez_y, sortie = points[0][1], {}
    for nom, poignet, coude, epaule in (("gauche", 15, 13, 11), ("droite", 16, 14, 12)):
        sortie[nom] = {"coude": (points[epaule][1] - points[coude][1]) * taille / largeur,
                       "nez": (nez_y - points[poignet][1]) * taille / largeur,
                       "visible": points[poignet][2] >= reachy_vue.HAND_VISIBLE and points[coude][2] >= reachy_vue.ELBOW_VISIBLE,
                       "x": poignets.get(nom)}
    return sortie


class MesureGestes(Mesure):
    """Ce que la caméra voit du buste de la personne suivie : image par image, la hauteur du coude et du poignet.
    Étapes : repos (mesure le plus haut atteint BRAS BAISSÉS), coucou, main levée immobile (mesurent le plus bas
    atteint bras LEVÉ). Les deux seuils sont placés entre les deux, sans jamais passer sous les postures pièges
    mesurées le 11/10 (main sur la tête, menton dans la main… : coude ≤ 0,27, poignet/nez ≤ 0,29)."""

    ETAPES = (
        ("repos", "Assieds-toi à ta place habituelle, mains baissées, et ne bouge pas."),
        ("coucou", "Lève la main droite et fais coucou pendant 3 secondes."),
        ("main", "Garde la main droite levée, immobile, pendant 3 secondes."),
    )
    IMAGES_REPOS = 12             # images avec une personne, pour connaître le repos
    DUREE = 3.0                   # secondes de geste
    IMAGES_LEVEES = 6             # images « clairement levées » pour dire que le geste a été fait
    PIEGE = (0.27, 0.29)          # coude, poignet/nez : le plus haut des postures pièges (calibrage du 11/10)
    LEVE_COUDE, LEVE_NEZ = 0.05, 0.15     # au-dessus du repos : « clairement levé »
    MARGE = 0.03                  # un seuil reste à cette distance du repos et du bras levé
    AMPLEUR_MIN = reachy_vue.WAVE_SPAN    # va-et-vient d'un coucou, en largeurs d'épaules

    def commencer(self, i, now):
        self.d[i] = {"debut": now, "images": 0, "absent": 0, "repos": [0.0, 0.0], "cotes": {"gauche": [], "droite": []},
                     "geste": None, "ok": False}

    def ajouter(self, i, echantillon, now):
        d = self.d[i]
        if echantillon["type"] == "geste":
            d["geste"] = echantillon["genre"]
            return
        cotes = echantillon["cotes"]
        if cotes is None:
            d["absent"] += 1
            return
        d["images"] += 1
        for nom, m in cotes.items():
            if not m["visible"]:
                continue
            if i == 0:
                d["repos"] = [max(d["repos"][0], m["coude"]), max(d["repos"][1], m["nez"])]
            d["cotes"][nom].append(m)

    def _sol(self):
        """Le plus haut atteint bras baissés, sans jamais descendre sous les postures pièges."""
        repos = self.d[0]["repos"]
        return max(repos[0], self.PIEGE[0]), max(repos[1], self.PIEGE[1])

    def _leve(self, m):
        sol = self._sol()
        return m["coude"] > sol[0] + self.LEVE_COUDE and m["nez"] > sol[1] + self.LEVE_NEZ

    def _cote(self, d):
        """Le bras qui a fait le geste : celui vu levé le plus souvent."""
        return max(d["cotes"], key=lambda nom: sum(self._leve(m) for m in d["cotes"][nom]))

    def _regle(self, m):
        return m["coude"] >= self.actuel("main_coude") and m["nez"] >= self.actuel("main_poignet")

    def _ampleur(self, d):
        xs = [m["x"] for m in d["cotes"][self._cote(d)] if self._leve(m) and m["x"] is not None]
        return max(xs) - min(xs) if xs else 0.0

    def etat(self, i, now):
        d = self.d[i]
        if i == 0:
            n = d["images"]
            ok = n >= self.IMAGES_REPOS
            if ok:
                texte = (f"{n} images · bras baissés : coude {fr(d['repos'][0], 2)} au plus, "
                         f"poignet au-dessus du nez {fr(d['repos'][1], 2)} au plus")
            else:
                texte = f"{n} image{'s' if n > 1 else ''} sur {self.IMAGES_REPOS}" + (" · je ne te vois pas" if d["absent"] > n else "")
            return self.etat_de(ok, texte, n / self.IMAGES_REPOS,
                                "" if n or d["absent"] < 6 else "Je ne vois personne : mets-toi face au robot, dans la caméra.")
        cote = self._cote(d)
        images = d["images"]
        levees = [m for m in d["cotes"][cote] if self._leve(m)]
        vues = sum(self._regle(m) for m in d["cotes"][cote])
        ecoule = now - d["debut"]
        ok = ecoule >= self.DUREE and len(levees) >= self.IMAGES_LEVEES
        texte = f"bras levé vu {vues} fois sur {images}"
        if i == 1:
            texte += f" · ampleur {fr(self._ampleur(d), 2)}"
        elif len(levees) >= 2:
            texte += f" · ampleur {fr(self._ampleur(d), 2)} (immobile)" if self._ampleur(d) < self.AMPLEUR_MIN else \
                f" · ampleur {fr(self._ampleur(d), 2)} (ça bouge)"
        alerte = ""
        if ecoule >= self.DUREE and len(levees) < self.IMAGES_LEVEES:
            alerte = ("Le bras n'a pas été vu assez nettement levé : monte-le franchement (coude plus haut que l'épaule, "
                      "main au-dessus de la tête) et reste face au robot.")
        return self.etat_de(ok, texte, min(ecoule / self.DUREE, len(levees) / self.IMAGES_LEVEES), alerte)

    @staticmethod
    def _bas(valeurs):
        """Le bas de ce qui a été mesuré bras levé : on écarte la plus basse dixième (image floue, bras en route)."""
        ordre = sorted(valeurs)
        return ordre[int(len(ordre) * 0.1)]

    def resultat(self):
        sol = self._sol()
        levees = [m for i in (1, 2) for m in self.d[i]["cotes"][self._cote(self.d[i])] if self._leve(m)]
        haut_coude, haut_nez = self._bas([m["coude"] for m in levees]), self._bas([m["nez"] for m in levees])
        propose, serre = {}, False
        for cle, bas, haut in (("main_coude", sol[0], haut_coude), ("main_poignet", sol[1], haut_nez)):
            actuel = self.actuel(cle)
            mini, maxi = bas + self.MARGE, haut - self.MARGE
            if mini > maxi:
                serre, propose[cle] = True, actuel          # le repos et le bras levé se touchent : rien à proposer
            elif mini <= actuel <= maxi:
                propose[cle] = actuel
            else:
                propose[cle] = arrondi(cle, (bas + haut) / 2)
        retenues = sum(m["coude"] >= propose["main_coude"] and m["nez"] >= propose["main_poignet"]
                       for i in (2,) for m in self.d[i]["cotes"][self._cote(self.d[i])])
        images = self.d[2]["images"]
        alertes = []
        if serre:
            alertes.append(f"Le repos (coude {fr(sol[0], 2)}, poignet {fr(sol[1], 2)}) et le bras levé (coude {fr(haut_coude, 2)}, "
                           f"poignet {fr(haut_nez, 2)}) sont trop proches pour placer un seuil sûr. Rien n'est proposé : "
                           "recommence en levant le bras plus haut.")
        elif images and retenues / images < 0.75:
            alertes.append(f"Avec ces seuils, la main immobile ne serait vue que {retenues} fois sur {images} "
                           "(il en faut 3 sur 4) : recommence en gardant le bras bien levé.")
        if self.d[1]["geste"] != "coucou":
            ampleur = self._ampleur(self.d[1])
            if ampleur < self.AMPLEUR_MIN:
                alertes.append(f"Ton coucou n'a pas été reconnu comme un coucou (ampleur {fr(ampleur, 2)}, il faut "
                               f"{fr(self.AMPLEUR_MIN, 2)}) : fais un va-et-vient plus large. Il n'y a rien à régler ici, c'est le geste.")
            else:
                # 11/10 : ample (0,97) mais pas reconnu — le geste n'était pas en cause : le bras levé n'a pas été vu assez
                # souvent pendant le va-et-vient. Le dire tel quel plutôt que reprocher le geste.
                alertes.append(f"Ton coucou était assez ample ({fr(ampleur, 2)}), mais le détecteur ne l'a pas reconnu : "
                               "il n'a pas vu le bras levé assez souvent pendant le va-et-vient.")
        if self.d[2]["geste"] == "coucou":
            alertes.append("La main immobile a été prise pour un coucou : garde-la vraiment immobile.")
        if alertes:
            ton, titre = "warn", "Quelque chose demande attention."
            texte = " ".join(alertes)
        else:
            texte = (f"Bras baissés : coude {fr(sol[0], 2)}, poignet {fr(sol[1], 2)} au plus. Bras levé : coude "
                     f"{fr(haut_coude, 2)}, poignet {fr(haut_nez, 2)} au moins. Le coucou et la main immobile sont bien distingués.")
            ton, titre = "ok", ("Les réglages actuels conviennent." if all(propose[k] == self.actuel(k) for k in propose)
                                else "Des seuils mieux placés sont proposés.")
        changements = {k: v for k, v in propose.items() if v != self.actuel(k)}
        return {"ton": ton, "titre": titre, "texte": texte,
                "lignes": [ligne(k, self.actuel(k), propose[k]) for k in ("main_coude", "main_poignet")],
                "ecrit": ["vivant.json — seuils du bras levé"], "changements": changements}


# --- Les capteurs : ils lisent le monde et rendent des échantillons -----------------------------------------
class Capteur:
    """`disponible()` → (oui, raison) ; `ouvrir()` avant la première lecture ; `lire(now)` → une liste d'échantillons
    (peut être vide) ; `fermer()` toujours appelé. `periode` : secondes entre deux lectures."""

    periode = PERIODE

    def __init__(self, body):
        self.body = body

    def disponible(self):
        return True, ""

    def ouvrir(self):
        pass

    def lire(self, now):
        return []

    def fermer(self):
        pass

    def etat_complet(self):
        """L'état complet des moteurs (`reachy.FULL_STATE`), ou None. Rien d'autre n'est demandé au robot."""
        try:
            return self.body.robot.call(reachy.FULL_STATE) or {}
        except Exception:
            return None


class CapteurToucher(Capteur):
    """Les 7 moteurs (corps + tête) en degrés, comme `feel()` les lit ; 10 fois par seconde."""

    def __init__(self, body):
        super().__init__(body)
        self.ratees = 0

    def lire(self, now):
        full = self.etat_complet()
        joints = full.get("head_joints") if full else None
        if not (isinstance(joints, list) and len(joints) == 7):
            self.ratees += 1
            if self.ratees >= ERREURS_MAX:
                raise RuntimeError("le robot ne répond plus")
            return []
        self.ratees = 0
        self.body.motors_seen = (now, joints, full.get("antennas_position"))      # la carte « Moteurs » reste vivante
        return [{"moteurs": [math.degrees(v) for v in joints]}]


class CapteurPiece(Capteur):
    """La direction de la parole par les micros de la tête (`Ears`), 5 fois par seconde. Repère du socle : le
    lacet de la tête, lu toutes les 2 s (elle est immobile), plus l'angle entendu — comme `facing_for`, sans la
    borne de ±50° : la mesure veut les directions vraies."""

    periode = reachy.EARS_EVERY

    def __init__(self, body):
        super().__init__(body)
        self.tete, self.lu_a = 0.0, -1e9

    def disponible(self):
        ears = getattr(self.body, "ears", None)
        if ears is None or ears.device is None:
            return False, "les micros de la tête ne sont pas lisibles d'ici (le corps tourne-t-il sur la machine du robot ?)"
        return True, ""

    def ouvrir(self):
        if self.etat_tete(time.monotonic()) is None:
            raise RuntimeError("la position de la tête n'est pas lisible")

    def etat_tete(self, now):
        if now - self.lu_a > 2.0:
            full = self.etat_complet()
            pose = (full or {}).get("head_pose") or {}
            if "yaw" not in pose:
                return None
            self.tete, self.lu_a = pose["yaw"], now
        return self.tete

    def lire(self, now):
        entendu = self.body.ears.read()
        if not entendu or not entendu[1]:
            return []
        tete = self.etat_tete(now)
        if tete is None:
            return []
        return [{"yaw": math.degrees(tete + reachy.DOA_SIGN * (math.pi / 2 - entendu[0]))}]


class EspionMains:
    """Se glisse à la place de `Eyes.hands` pendant l'assistant : la vue continue son travail exactement comme
    d'habitude (même image, même visage suivi, même découpe du buste), et chaque analyse est aussi rangée dans
    `file` pour l'assistant. Tout le reste passe tel quel à la vraie détection."""

    def __init__(self, vraie, file):
        self.vraie, self.file = vraie, file

    def look(self, image, box):
        self.vraie.dernier = None
        vu = self.vraie.look(image, box)
        dernier = self.vraie.dernier
        if vu is None or dernier is None:
            self.file.append({"type": "image", "cotes": None})
        else:
            self.file.append({"type": "image", "cotes": mesures_bras(dernier[0], dernier[1], vu[1])})
        return vu

    def __getattr__(self, nom):
        return getattr(self.vraie, nom)


class CapteurGestes(Capteur):
    """Les analyses de la vue (`Hands`, MediaPipe Pose Lite) et les gestes qu'elle annonce (`Eyes.gesture`)."""

    periode = 0.2
    ATTENTE_MAINS = 30.0          # secondes pour que la vue crée sa détection si « Répondre à un coucou » était coupé

    def __init__(self, body):
        super().__init__(body)
        self.file, self.vraie, self.mains_avant, self.dernier_geste, self.debut = [], None, None, None, 0.0

    def disponible(self):
        eyes = getattr(self.body, "eyes", None)
        if eyes is None:
            return False, "aucune caméra n'est configurée pour le robot"
        if eyes.frame_url() is None:
            return False, "la détection des gestes exige la caméra en images seules (go2rtc)"
        return True, ""

    def ouvrir(self):
        eyes = self.body.eyes
        self.mains_avant = eyes.hands_on
        eyes.hands_on = True                         # « Répondre à un coucou » s'allume le temps de la mesure
        limite = time.monotonic() + self.ATTENTE_MAINS
        while eyes.hands is None and time.monotonic() < limite and "gestes indisponibles" not in eyes.error:
            time.sleep(0.1)
        if eyes.hands is None:
            raise RuntimeError(eyes.error or "la détection des gestes n'est pas disponible (MediaPipe ?)")
        self.vraie = eyes.hands
        eyes.hands = EspionMains(self.vraie, self.file)
        self.dernier_geste, self.debut = eyes.gesture, time.monotonic()

    def lire(self, now):
        sortie, self.file[:] = list(self.file), []
        eyes = self.body.eyes
        geste = eyes.gesture
        if geste is not None and geste is not self.dernier_geste and geste[2] >= self.debut:
            self.dernier_geste = geste
            sortie.append({"type": "geste", "genre": geste[0], "cote": geste[1]})
        return sortie

    def fermer(self):
        eyes = getattr(self.body, "eyes", None)
        if eyes is None or self.vraie is None:
            return
        if isinstance(eyes.hands, EspionMains):
            eyes.hands = self.vraie
        eyes.hands_on = self.body.gestes_actifs()                 # « Répondre à un coucou » / l'observation : comme avant


# --- Les assistants ------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Definition:
    cle: str
    titre: str
    rubrique: str
    intro: str
    mesure: str                   # ce qui est mesuré (une phrase)
    ecrit: str                    # ce qui sera écrit (une phrase)
    mesure_classe: type
    capteur_classe: type

    @property
    def etapes(self):
        return self.mesure_classe.ETAPES


DEFINITIONS = {d.cle: d for d in (
    Definition("gestes", "Calibrer les gestes de la main", "voir",
               "Pour que le robot reconnaisse une main levée et un coucou depuis ta place habituelle.",
               "La caméra : la hauteur du coude et du poignet de la personne suivie, image par image.",
               "Les deux seuils du « bras levé » (vivant.json).", MesureGestes, CapteurGestes),
    Definition("toucher", "Calibrer le toucher de la tête et du corps", "toucher",
               "Pour que le robot fasse la différence entre une main posée, une tête poussée et un corps tourné.",
               "La position réelle des 7 moteurs, 10 fois par seconde. Pendant la mesure, le robot ne bouge pas de lui-même.",
               "Les seuils « main posée » et « poussée » (vivant.json).", MesureToucher, CapteurToucher),
    Definition("piece", "Calibrer la pièce", "piece",
               "Pour savoir d'où viennent la télé et les voix, et quelles directions ignorer.",
               "La direction de la parole, par les micros de la tête. Pendant la mesure, la tête reste immobile.",
               "Les directions ignorées et les repères du canapé et de la télé (vivant.json).", MesurePiece, CapteurPiece),
)}


class Session:
    """Un assistant ouvert : où il en est, ce qu'il a mesuré, ce qu'il propose."""

    def __init__(self, definition, mesure, capteur, now):
        self.definition, self.mesure, self.capteur = definition, mesure, capteur
        self.etat = "preparation"       # preparation | mesure | resultat | applique | annule | interrompue
        self.etape, self.resultat, self.raison, self.ecrit = 0, None, "", []
        self.cree, self.fini = now, None


class Moteur:
    """Le moteur d'assistants d'UN corps : une session à la fois. Les mesures tournent dans un fil à part, la page
    ne fait que demander l'état (`etat()`) et envoyer ses boutons."""

    _par_corps = weakref.WeakKeyDictionary()
    _verrou_classe = threading.Lock()

    def __init__(self, body, contenu=None, ecrire=None, definitions=None, capteurs=None):
        self._corps = weakref.ref(body)                 # le moteur ne retient pas son corps (le cache `_par_corps` non plus)
        self.definitions = definitions if definitions is not None else DEFINITIONS
        self.capteurs = capteurs or {}                  # clé → fabrique de capteur, pour les essais
        self.contenu = contenu or self._contenu
        self.ecrire = ecrire or self._ecrire
        self.lock = threading.RLock()
        self.session = None

    @property
    def body(self):
        corps = self._corps()
        if corps is None:
            raise Refus("le corps du robot n'existe plus")
        return corps

    @classmethod
    def de(cls, body):
        """LE moteur de ce corps (créé à la première demande)."""
        with cls._verrou_classe:
            moteur = cls._par_corps.get(body)
            if moteur is None:
                moteur = cls._par_corps[body] = cls(body)
            return moteur

    def _contenu(self):
        """Le contenu des réglages : le fichier quand il existe (la vérité), sinon ce que le corps a reçu."""
        if self.body.fichier is not None:
            try:
                return reachy_reglages.lire(self.body.fichier)
            except ValueError:
                pass
        return dict(self.body.alive)

    def _ecrire(self, changements):
        """Écriture par défaut : le schéma (validation, sauvegarde, atomique), puis le corps l'applique à chaud."""
        if self.body.fichier is None:
            raise Refus("aucun fichier de réglages : lecture seule")
        nouveau = reachy_reglages.ecrire(self.body.fichier, changements)
        self.body.inbox.put(("reglages", nouveau))
        return nouveau

    @property
    def peut_ecrire(self):
        return self.body.fichier is not None

    # --- ce que la page lit
    def actuel(self, cle):
        return reachy_reglages.lu(self.contenu(), cle)

    def _capteur(self, definition):
        fabrique = self.capteurs.get(definition.cle, definition.capteur_classe)
        return fabrique(self.body)

    def catalogue(self):
        sortie = []
        for d in self.definitions.values():
            ok, raison = self._capteur(d).disponible()
            if ok and not self.peut_ecrire:
                ok, raison = False, "aucun fichier de réglages : lecture seule"
            sortie.append({"id": d.cle, "titre": d.titre, "rubrique": d.rubrique, "intro": d.intro, "mesure": d.mesure,
                           "ecrit": d.ecrit, "etapes": len(d.etapes), "disponible": ok, "raison": raison})
        return sortie

    def etat(self, now=None):
        """L'état de la session pour la page, ou None."""
        now = time.monotonic() if now is None else now
        with self.lock:
            s = self.session
            if s is None:
                return None
            sortie = {"id": s.definition.cle, "titre": s.definition.titre, "rubrique": s.definition.rubrique,
                      "etat": s.etat, "etape": s.etape, "etapes": [c for _, c in s.definition.etapes],
                      "raison": s.raison, "mesure": None, "resultat": None, "ecrit": list(s.ecrit), "reste": None}
            if s.etat == "mesure":
                sortie["mesure"] = s.mesure.etat(s.etape, now)
                sortie["reste"] = max(0, round(self.body.measure_until - now))
            if s.etat in ("resultat", "applique") and s.resultat is not None:
                sortie["resultat"] = {k: v for k, v in s.resultat.items() if k != "changements"}
            return sortie

    # --- les boutons
    def lancer(self, cle):
        with self.lock:
            definition = self.definitions.get(cle)
            if definition is None:
                raise ValueError(f"assistant inconnu : {cle}")
            if self.session is not None and self.session.etat in ("preparation", "mesure"):
                raise Refus("un assistant est déjà ouvert : l'annuler d'abord")
            capteur = self._capteur(definition)
            ok, raison = capteur.disponible()
            if not ok:
                raise Refus(raison)
            if not self.peut_ecrire:
                raise Refus("aucun fichier de réglages : lecture seule")
            ok, raison = self.body.enter_measure_mode(f"assistant « {definition.titre} »")
            if not ok:
                raise Refus(raison)
            now = time.monotonic()
            session = self.session = Session(definition, definition.mesure_classe(self.actuel), capteur, now)
        threading.Thread(target=self._boucle, args=(session,), daemon=True).start()
        return self.etat()

    def suivant(self):
        with self.lock:
            s = self._active("mesure")
            if not s.mesure.etat(s.etape, time.monotonic())["suffisante"]:
                raise Refus("la mesure n'est pas encore suffisante")
            if s.etape + 1 < len(s.definition.etapes):
                s.etape += 1
                s.mesure.commencer(s.etape, time.monotonic())
            else:
                s.resultat = s.mesure.resultat()
                s.etat, s.fini = "resultat", time.monotonic()
                self.body.leave_measure_mode("assistant terminé")
        return self.etat()

    def recommencer(self):
        """Recommence l'étape en cours (pendant les mesures) ou tout l'assistant (au résultat, ou après une
        interruption)."""
        with self.lock:
            s = self.session
            if s is not None and s.etat in ("resultat", "interrompue"):
                cle = s.definition.cle
                s.etat, s.raison = "annule", "recommencé"
                s.fini = time.monotonic()
            else:
                s = self._active("mesure")
                s.mesure.commencer(s.etape, time.monotonic())
                return self.etat()
        return self.lancer(cle)

    def annuler(self):
        """Ferme l'assistant sans rien changer. Sans effet s'il n'y en a pas (ou s'il est déjà fini)."""
        with self.lock:
            s = self.session
            if s is not None and s.etat in ("preparation", "mesure", "resultat"):
                s.etat, s.raison, s.fini = "annule", "annulé : rien n'a été changé", time.monotonic()
                self.body.leave_measure_mode("assistant annulé")
        return self.etat()

    def appliquer(self):
        """Écrit ce que l'assistant propose (sauvegarde de `vivant.json` d'abord, par le schéma)."""
        with self.lock:
            s = self._active("resultat")
            if time.monotonic() - s.fini > RESULTAT_VIE:
                raise Refus("ce résultat est trop ancien : recommencer l'assistant")
            changements = {k: v for k, v in s.resultat["changements"].items() if v != self.actuel(k)}
            if changements:
                self.ecrire(changements)
                self.body.on_note("assistant « " + s.definition.titre + " » appliqué : " + ", ".join(sorted(changements)))
            s.ecrit = sorted(changements)
            s.etat = "applique"
        return self.etat()

    def _active(self, etat):
        s = self.session
        if s is None or s.etat != etat:
            raise Refus("aucun assistant dans cet état" + (f" ({s.etat})" if s else ""))
        return s

    # --- le fil de mesure
    def _interrompre(self, session, raison):
        with self.lock:
            if session.etat in ("preparation", "mesure"):
                session.etat, session.raison, session.fini = "interrompue", raison, time.monotonic()
        self.body.leave_measure_mode(raison)

    def _boucle(self, session):
        body, capteur = self.body, session.capteur
        try:
            debut = time.monotonic()
            while not body.measure_ready():                       # le corps finit son geste, puis ne bouge plus
                if session.etat != "preparation":
                    return
                if not body.in_measure_mode():
                    return self._interrompre(session, body.measure_reason or "le mode mesure s'est levé")
                if time.monotonic() - debut > PREPARATION_MAX:
                    return self._interrompre(session, "le robot n'a pas fini de bouger")
                time.sleep(0.05)
            capteur.ouvrir()
            with self.lock:
                if session.etat != "preparation":
                    return
                session.etat = "mesure"
                session.mesure.commencer(0, time.monotonic())
            while True:
                with self.lock:
                    if session.etat != "mesure":
                        return
                if not body.in_measure_mode():
                    return self._interrompre(session, body.measure_reason or "le mode mesure s'est levé")
                now = time.monotonic()
                echantillons = capteur.lire(now)
                with self.lock:
                    if session.etat == "mesure":
                        for echantillon in echantillons:
                            session.mesure.ajouter(session.etape, echantillon, now)
                time.sleep(capteur.periode)
        except Exception as trouble:
            self._interrompre(session, f"mesure interrompue : {str(trouble)[:150]}")
        finally:
            capteur.fermer()
