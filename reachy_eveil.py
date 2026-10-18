#!/usr/bin/env python3
"""Rubrique Parler, carte « Mots d'éveil » de la page du robot (16/10/2026).

« salut Alison » (Vosk, wake_alison.py → pont_lva.py) reste TOUJOURS actif : rien ici ne le touche.
En plus, Linux Voice Assistant (LVA) a ses propres modèles microWakeWord (Okay Nabu…), réglables par
Home Assistant : `select.<satellite>_mot_d_activation` (le modèle) et `number.<satellite>_wake_word_1_sensitivity`
(le seuil = probabilité minimale : plus haut, moins de faux réveils ; 1,0 = jamais). LVA garde le choix dans son
`preferences.json`. Le modèle de LVA ne peut pas être retiré : « aucun » = seuil 1,0 (neutralisé le 10/10 après
4 faux réveils une nuit).

- Le module ne connaît NI le jeton NI l'adresse de HA : le corps pose `body.ha_eveil = client_http(url, jeton)`,
  une fonction `appel(methode, chemin, corps)` limitée à une liste FERMÉE de chemins.
Bibliothèque standard seulement.
"""
import json
import re
import threading
import urllib.request
from http import HTTPStatus

PREFIXE = "/api/eveil"
# Les deux entités du satellite viennent du fichier de réglages du corps (`vivant.json`, clé « eveil » :
# {"modele": "select.…", "seuil": "number.…"}) — leur nom dépend de l'appareil déclaré dans HA (18/10).
MODELE = ""
SEUIL = ""
JAMAIS = 1.0                       # seuil qui neutralise le mot d'éveil de LVA
SEUIL_MIN, SEUIL_MAX = 0.5, 0.99
DELAI = 5.0
# Modèles microWakeWord livrés avec LVA 1.1.15 : seuil d'origine (`probability_cutoff` de leur .json) et langues
# d'entraînement. Okay Nabu est le seul entraîné aussi en français. Les variantes « (OWW) » (openWakeWord, plus
# lourdes) ne sont pas proposées.
MODELES = {
    "Okay Nabu": (0.85, True),
    "Hey Jarvis": (0.97, False),
    "Alexa": (0.90, False),
    "Hey Mycroft": (0.95, False),
    "Okay Computer": (0.97, False),
    "Hey Morgan": (0.90, False),
    "Hey Home Assistant": (0.97, False),
    "Choo Choo Homie": (0.97, False),
    "hey_luna": (0.63, False),
}
CHEMINS = set()                    # la liste fermée des appels à HA (posée par `configurer`)


def configurer(conf):
    """Pose les entités depuis `alive["eveil"]`. Mal formées = rubrique non configurée."""
    global MODELE, SEUIL, CHEMINS
    conf = conf if isinstance(conf, dict) else {}
    modele, seuil = str(conf.get("modele") or ""), str(conf.get("seuil") or "")
    if not (re.fullmatch(r"select\.[a-z0-9_]+", modele) and re.fullmatch(r"number\.[a-z0-9_]+", seuil)):
        modele = seuil = ""
    MODELE, SEUIL = modele, seuil
    CHEMINS = {("GET", f"/api/states/{MODELE}"), ("GET", f"/api/states/{SEUIL}"),
               ("POST", "/api/services/select/select_option"),
               ("POST", "/api/services/number/set_value")} if MODELE else set()


def configure():
    return bool(MODELE and SEUIL)


class Refus(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def client_http(url, jeton, delai=DELAI):
    """L'accès à HA du corps pour cette carte. Le jeton reste dans la fonction, jamais servi."""
    url = str(url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")) or not jeton:
        raise ValueError("éveil : une adresse http(s) et un jeton sont nécessaires")
    entetes = {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"}

    def appel(methode, chemin, corps=None):
        if (methode, chemin) not in CHEMINS:
            raise ValueError("éveil : appel hors de la liste")
        donnees = json.dumps(corps).encode() if corps is not None else None
        demande = urllib.request.Request(url + chemin, donnees, entetes, method=methode)
        with urllib.request.urlopen(demande, timeout=delai) as reponse:
            return json.loads(reponse.read(262144) or b"null")
    return appel


def _nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


class Eveil:
    """`source()` rend l'appel à HA du corps (ou None)."""

    def __init__(self, source):
        self.source = source
        self.verrou = threading.Lock()

    def _ha(self):
        appel = self.source()
        if appel is None:
            raise Refus(HTTPStatus.SERVICE_UNAVAILABLE, "pas d'accès à Home Assistant dans le corps")
        return appel

    def _lire(self, appel):
        modele = appel("GET", f"/api/states/{MODELE}") or {}
        seuil = appel("GET", f"/api/states/{SEUIL}") or {}
        return modele.get("state"), (modele.get("attributes") or {}).get("options") or [], _nombre(seuil.get("state"))

    def etat(self):
        try:
            modele, options, seuil = self._lire(self._ha())
            ha, erreur = True, ""
        except Refus as refus:
            modele, options, seuil, ha, erreur = None, [], None, False, refus.message
        except Exception:              # HA éteint, jeton refusé, délai dépassé : la page vit sans lui
            modele, options, seuil, ha, erreur = None, [], None, False, "Home Assistant ne répond pas"
        actif = ha and modele in MODELES and seuil is not None and seuil < JAMAIS
        return {
            "ha": {"disponible": ha, "erreur": erreur},
            "mot": modele if actif else None,
            "seuil": seuil if actif else None,
            "modeles": [{"nom": n, "defaut": d, "francais": fr, "dispo": n in options} for n, (d, fr) in MODELES.items()],
            "min": SEUIL_MIN, "max": SEUIL_MAX,
        }

    def _seuil(self, valeur, defaut):
        if valeur is None:
            return defaut
        v = _nombre(valeur)
        if v is None or not SEUIL_MIN <= v <= SEUIL_MAX:
            raise Refus(HTTPStatus.BAD_REQUEST, f"un seuil entre {SEUIL_MIN} et {SEUIL_MAX}")
        return round(v, 3)

    def choisir(self, nom, seuil=None):
        """`nom` = un modèle de MODELES, ou vide pour « aucun » (seuil 1,0 : « salut Alison » seul)."""
        nom = str(nom or "")
        if nom and nom not in MODELES:
            raise Refus(HTTPStatus.BAD_REQUEST, "mot d'éveil inconnu")
        with self.verrou:
            appel = self._ha()
            try:
                if not nom:
                    appel("POST", "/api/services/number/set_value", {"entity_id": SEUIL, "value": JAMAIS})
                else:
                    valeur = self._seuil(seuil, MODELES[nom][0])
                    # seuil d'abord (s'il est à 1,0, le changement de modèle ne réveille rien entre-temps)
                    appel("POST", "/api/services/number/set_value", {"entity_id": SEUIL, "value": JAMAIS})
                    appel("POST", "/api/services/select/select_option", {"entity_id": MODELE, "option": nom})
                    appel("POST", "/api/services/number/set_value", {"entity_id": SEUIL, "value": valeur})
            except Refus:
                raise
            except Exception:
                raise Refus(HTTPStatus.SERVICE_UNAVAILABLE, "Home Assistant ne répond pas")
        return self.etat()

    def regler(self, seuil):
        with self.verrou:
            appel = self._ha()
            valeur = self._seuil(seuil, None)
            if valeur is None:
                raise Refus(HTTPStatus.BAD_REQUEST, f"un seuil entre {SEUIL_MIN} et {SEUIL_MAX}")
            try:
                modele, _, actuel = self._lire(appel)
                if modele not in MODELES or actuel is None or actuel >= JAMAIS:
                    raise Refus(HTTPStatus.CONFLICT, "aucun mot d'éveil du robot n'est actif")
                appel("POST", "/api/services/number/set_value", {"entity_id": SEUIL, "value": valeur})
            except Refus:
                raise
            except Exception:
                raise Refus(HTTPStatus.SERVICE_UNAVAILABLE, "Home Assistant ne répond pas")
        return self.etat()

    def route(self, methode, chemin, demande=None):
        """→ (statut HTTP, réponse JSON)."""
        if not configure():
            # Rien dans le fichier de réglages du corps : la rubrique le dit, sans jamais toucher à HA.
            return HTTPStatus.NOT_FOUND, {"erreur": "mots d'éveil : non configuré dans le fichier de réglages du corps",
                                          "configure": False}
        try:
            if methode == "GET" and chemin == PREFIXE:
                return HTTPStatus.OK, self.etat()
            if methode == "POST":
                demande = demande if isinstance(demande, dict) else {}
                if chemin == PREFIXE + "/choisir":
                    return HTTPStatus.OK, self.choisir(demande.get("mot"), demande.get("seuil"))
                if chemin == PREFIXE + "/seuil":
                    return HTTPStatus.OK, self.regler(demande.get("seuil"))
            return HTTPStatus.NOT_FOUND, {"erreur": "inconnu"}
        except Refus as refus:
            return refus.status, {"erreur": refus.message}
