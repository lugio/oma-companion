#!/usr/bin/env python3
"""Les personnes que le robot connaît : fiches, accord daté, enrôlement du visage, « Oublier » (11/10/2026).

Spec `docs/superpowers/specs/2026-10-11-reachy-page-reglages.md` (lot 5, décisions § 8) :
- l'accord de la personne est DATÉ et OBLIGATOIRE avant tout enregistrement (qui l'a donné, quand, pour quoi) ;
- « Oublier » EFFACE pour de bon, après confirmation : l'empreinte du visage, celle de la voix et l'accord.
  Pas de corbeille, aucune copie ;
- aucune image, aucun son, aucune empreinte n'est jamais écrit dans le journal ni renvoyé par la page : la page ne
  voit que des noms, des dates et des compteurs.

Où vit chaque chose (réglages du corps, `alive`, tous facultatifs, AJOUT seulement) :
- `visages` (existant) : dossier des empreintes de visages `<nom>.json` ;
- `voix_empreintes` (lot 5) : dossier des empreintes de voix `<nom>.json` ({nom, modele, phrases, empreinte}) ;
- `personnes` (lot 5) : fichier de l'accord daté ; sinon `personnes.json` à côté du dossier des visages (ou
  des voix). Dossiers 700, fichiers 600.

Apprendre un visage ou une voix (11/10) : la rubrique Apprentissage (`reachy_apprendre.py`), qui garde ici l'accord
daté. Aucune dépendance autre que la bibliothèque standard ; OpenCV n'est importé que pour le visage.
"""
import json
import os
import re
import threading
import time
import unicodedata
import urllib.request
from pathlib import Path

PREFIXE = "/api/personnes"                       # toutes les routes de ce module commencent par là
GENRES = ("visage", "voix")
IMAGES = 20                                      # vues demandées pour un visage (au moins 5 nettes)
POUR = {"visage": "Garder une empreinte numérique de son visage pour que le robot le reconnaisse (aucune photo gardée).",
        "voix": "Garder une empreinte numérique de sa voix pour que le robot la reconnaisse (aucun enregistrement gardé)."}
NOM_OK = re.compile(r"^[a-z][a-z0-9-]{0,29}$")



# Ce qu'une personne a aussi dans Home Assistant (souvenirs, dernier accueil) : des modèles d'entité avec
# `{nom}`, propres à chaque maison — fichier de réglages du corps, clé « personnes_ha » (18/10). Vide = rien.
HA_MODELES = {}


def configurer(conf):
    global HA_MODELES
    conf = conf if isinstance(conf, dict) else {}
    HA_MODELES = {cle: modele for cle, modele in conf.items()
                  if cle in ("souvenirs", "accueil") and isinstance(modele, str)
                  and re.fullmatch(r"[a-z_]+\.[a-z0-9_]*\{nom\}[a-z0-9_]*", modele)}


def ha_de(nom):
    """Les entités HA d'une personne. Un tiret (« jean-paul ») devient « _ » : HA n'en accepte pas."""
    nom = re.sub(r"[^a-z0-9_]", "_", str(nom).lower())
    return {cle: modele.replace("{nom}", nom) for cle, modele in HA_MODELES.items()}

class Refus(Exception):
    """Une demande refusée, avec le code HTTP à répondre et une phrase pour l'écran."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def accord_requis(body):
    """11/10 (besoin initial : « c'est mon système et il est local ») : le réglage « Demander l'accord avant d'apprendre »
    (`accord_requis`, actif d'origine). Coupé : un visage ou une voix s'apprend sans accord noté."""
    return (getattr(body, "alive", None) or {}).get("accord_requis") is not False


def nom_sur(texte):
    """Un prénom saisi → le nom de fichier sûr (minuscules, sans accent, lettres et chiffres). Refus sinon."""
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().strip().lower()
    texte = re.sub(r"[\s_]+", "-", texte)
    if not NOM_OK.match(texte) or texte == "inconnu":
        raise Refus(400, "prénom non valable : des lettres (sans espace), 30 au plus")
    return texte


def _ecrire(chemin, texte):
    """Écriture atomique, fichier 600, dossier 700."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(chemin.parent, 0o700)
    temporaire = chemin.with_suffix(".tmp")
    temporaire.write_text(texte)
    os.chmod(temporaire, 0o600)
    temporaire.replace(chemin)


def _horodatage(secondes=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(secondes))


class Personnes:
    """Les fiches. `body` donne les réglages (`alive`), le journal (`on_note`) et le reflet de la vue.
    `enroller` et `verifier` se remplacent dans les essais (OpenCV et la caméra n'y sont pas)."""

    def __init__(self, body, enroller=None, verifier=None):
        alive = body.alive
        self.body = body
        self.visages = Path(alive["visages"]) if alive.get("visages") else None
        self.voix = Path(alive["voix_empreintes"]) if alive.get("voix_empreintes") else None
        base = self.visages or self.voix
        self.accords_fichier = (Path(alive["personnes"]) if alive.get("personnes")
                                else (base.parent / "personnes.json" if base else None))
        self.source = str(alive.get("regard") or "")
        self.enroller = enroller or self._enroller
        self.verifier = verifier or self._verifier
        self.lock = threading.RLock()
        self.tache = None                          # l'enrôlement en cours ou le dernier terminé

    # --- ce que la page montre -----------------------------------------------------------------------
    def _dossier(self, genre):
        return self.visages if genre == "visage" else self.voix

    def _empreinte(self, genre, nom):
        """Les faits publics d'une empreinte (compteur, date) ; jamais les nombres. None si absente."""
        dossier = self._dossier(genre)
        chemin = dossier / f"{nom}.json" if dossier else None
        if chemin is None or not chemin.is_file():
            return None
        try:
            donnees = json.loads(chemin.read_text())
            nombre = donnees.get("vues" if genre == "visage" else "phrases")
        except (OSError, ValueError):
            donnees, nombre = {}, None
        return {"nombre": nombre if isinstance(nombre, int) and not isinstance(nombre, bool) else None,
                "le": _horodatage(chemin.stat().st_mtime)}

    def _accords(self):
        if self.accords_fichier is None or not self.accords_fichier.is_file():
            return {}
        try:
            donnees = json.loads(self.accords_fichier.read_text())
            gens = donnees.get("personnes")
            return gens if isinstance(gens, dict) else {}
        except (OSError, ValueError):
            return {}

    def _ecrire_accords(self, gens):
        if self.accords_fichier is None:
            raise Refus(409, "aucun dossier d'empreintes configuré")
        _ecrire(self.accords_fichier, json.dumps({"version": 1, "personnes": gens}, ensure_ascii=False, indent=1))

    def noms(self):
        trouves = set()
        for dossier in (self.visages, self.voix):
            if dossier and dossier.is_dir():
                trouves.update(p.stem for p in dossier.glob("*.json") if NOM_OK.match(p.stem))
        trouves.update(n for n in self._accords() if NOM_OK.match(n))
        return sorted(trouves)

    def fiche(self, nom, accords=None):
        accords = self._accords() if accords is None else accords
        accord = accords.get(nom) if isinstance(accords.get(nom), dict) else {}
        return {"nom": nom, "affiche": nom.capitalize(),
                "visage": self._empreinte("visage", nom), "voix": self._empreinte("voix", nom),
                "accord": {g: accord.get(g) for g in GENRES if isinstance(accord.get(g), dict)},
                "ha": ha_de(nom)}

    def liste(self):
        with self.lock:
            accords = self._accords()
            return {"personnes": [self.fiche(n, accords) for n in self.noms()],
                    "dossiers": {"visage": self.visages is not None, "voix": self.voix is not None},
                    "camera": bool(self.source), "ecriture": self.accords_fichier is not None,
                    "tache": self.etat_tache()}

    def etat_tache(self):
        with self.lock:
            return dict(self.tache) if self.tache else None

    # --- l'accord daté ----------------------------------------------------------------------------------
    def noter_accord(self, nom, genre, par, apres_coup=False):
        """Note l'accord (qui, quand, pour quoi). Retourne l'accord d'avant (pour le rétablir si l'enrôlement échoue)."""
        par = re.sub(r"\s+", " ", str(par or "")).strip()[:60]
        if not par:
            raise Refus(400, "qui donne l'accord ? (la personne elle-même, ou qui parle pour elle)")
        with self.lock:
            gens = self._accords()
            avant = (gens.get(nom) or {}).get(genre)
            gens.setdefault(nom, {})[genre] = {"par": par, "le": _horodatage(), "pour": POUR[genre],
                                               "apres_coup": bool(apres_coup)}
            self._ecrire_accords(gens)
            return avant

    def _rendre_accord(self, nom, genre, avant):
        with self.lock:
            gens = self._accords()
            if avant is None:
                (gens.get(nom) or {}).pop(genre, None)
                if nom in gens and not gens[nom]:
                    del gens[nom]
            else:
                gens.setdefault(nom, {})[genre] = avant
            self._ecrire_accords(gens)

    def accord_apres_coup(self, nom, genre, par):
        """Une empreinte qui existait déjà (avant cette page) : on NOTE l'accord, daté du jour, marqué « après coup »."""
        if genre not in GENRES:
            raise Refus(400, "visage ou voix")
        if self._empreinte(genre, nom) is None:
            raise Refus(404, f"pas d'empreinte de {genre} pour {nom.capitalize()}")
        self.noter_accord(nom, genre, par, apres_coup=True)
        return self.fiche(nom)

    # --- Oublier : définitif -------------------------------------------------------------------------------
    def oublier(self, nom, confirme):
        if confirme != nom:
            raise Refus(400, "confirmation manquante : « Oublier » demande de retaper le prénom")
        with self.lock:
            if self.tache and self.tache["etat"] == "en cours" and self.tache["nom"] == nom:
                raise Refus(409, "un enregistrement est en cours pour cette personne")
            efface = []
            for genre in GENRES:
                dossier = self._dossier(genre)
                chemin = dossier / f"{nom}.json" if dossier else None
                if chemin is not None and chemin.is_file():
                    chemin.unlink()
                    efface.append(genre)
            gens = self._accords()
            if nom in gens:
                del gens[nom]
                self._ecrire_accords(gens)
                efface.append("accord")
            if not efface:
                raise Refus(404, f"{nom.capitalize()} n'est pas connu·e du robot")
        self.body.on_note(f"personne oubliée : {nom} (effacé : {', '.join(efface)})")   # noms et genres, rien d'autre
        return {"efface": efface, "reste_dans_ha": list(ha_de(nom).values())}

    # --- enrôlement du visage ------------------------------------------------------------------------------
    def lancer_visage(self, nom, par, accord):
        requis = accord_requis(self.body)
        if accord is not True and requis:
            raise Refus(400, "l'accord de la personne est obligatoire avant d'enregistrer son visage")
        if self.visages is None or not self.source:
            raise Refus(409, "il faut un dossier de visages et une caméra dans les réglages du corps")
        if requis and not str(par or "").strip():
            raise Refus(400, "qui donne l'accord ? (la personne elle-même, ou qui parle pour elle)")
        with self.lock:
            if self.tache and self.tache["etat"] == "en cours":
                raise Refus(409, "un enregistrement est déjà en cours")
            self.tache = {"genre": "visage", "nom": nom, "etat": "en cours", "fait": 0, "total": IMAGES,
                          "retenues": 0, "debut": _horodatage()}
        threading.Thread(target=self._courir_visage, args=(nom, par), daemon=True).start()
        return self.etat_tache()

    def _maj(self, **champs):
        with self.lock:
            self.tache.update(champs)

    def _courir_visage(self, nom, par):
        avant, note = None, False
        try:
            if accord_requis(self.body) or str(par or "").strip():
                avant = self.noter_accord(nom, "visage", par)      # l'accord d'abord : pas d'empreinte sans lui
                note = True
            vues = self.enroller(self.source, str(self.visages), nom, progress=lambda fait, gardees: self._maj(fait=fait, retenues=gardees))
            self._maj(retenues=vues, etat="verification", fait=IMAGES)
            verdict = self.verifier(self.source, str(self.visages), nom)
            self._maj(etat="fini", verification=verdict)
            self.body.on_note(f"visage enregistré : {nom} ({vues} vues)")
        except Exception as erreur:                                 # noqa: BLE001 — rien ne doit tuer le fil
            if note:
                try:
                    self._rendre_accord(nom, "visage", avant)
                except Refus:
                    pass
            message = str(erreur)[:160] if isinstance(erreur, RuntimeError) else (
                "la caméra ne répond pas" if isinstance(erreur, OSError) else "enregistrement impossible")
            self._maj(etat="erreur", message=message)
            self.body.on_note(f"visage non enregistré : {nom} ({message})")

    def _enroller(self, source, dossier, nom, progress=None):
        import reachy_vue
        return reachy_vue.enroll(source, dossier, nom, images=IMAGES, progress=progress)

    def _verifier(self, source, dossier, nom):
        """Trois images fraîches : le robot reconnaît-il la personne qu'il vient d'enregistrer ?
        → {"reconnu": <nom ou "inconnu">, "ressemblance": <meilleur score>}. Aucune image gardée."""
        import cv2
        import numpy as np
        import reachy_vue
        noms = reachy_vue.FaceNames(dossier, getattr(self.body, "reglages", None))
        url = source.replace("/api/stream.mjpeg", "/api/frame.jpeg")
        prints = reachy_vue.load_prints(dossier)
        votes, meilleur = [], 0.0
        for _ in range(3):
            with urllib.request.urlopen(url, timeout=5) as reponse:
                image = cv2.imdecode(np.frombuffer(reponse.read(), np.uint8), cv2.IMREAD_COLOR)
            v = noms.feature(image) if image is not None else None
            if v is not None:
                scores = {n: float(v @ p) for n, p in prints.items()}
                trouve, score = reachy_vue.decide(scores, noms.r("who_min"), noms.r("who_gap"))
                votes.append(trouve)
                meilleur = max(meilleur, round(float(scores.get(nom, 0.0)), 2))
            time.sleep(0.5)
        reconnu = nom if votes.count(nom) >= 2 else "inconnu"
        return {"reconnu": reconnu, "ressemblance": meilleur}

    # --- le routeur des routes /api/personnes/… ---------------------------------------------------------------
    def route(self, methode, chemin, demande):
        """→ (code HTTP, réponse JSON). `demande` = le JSON déjà lu (POST) ou None."""
        try:
            if methode == "GET" and chemin == PREFIXE:
                return 200, self.liste()
            if methode != "POST" or not isinstance(demande, dict):
                raise Refus(404, "inconnu")
            nom = nom_sur(demande.get("nom"))
            action = chemin[len(PREFIXE) + 1:]
            if action == "visage":
                return 202, self.lancer_visage(nom, demande.get("par"), demande.get("accord"))
            if action == "accord":
                return 200, self.accord_apres_coup(nom, demande.get("genre"), demande.get("par"))
            if action == "oublier":
                return 200, self.oublier(nom, demande.get("confirme"))
            raise Refus(404, "inconnu")
        except Refus as refus:
            return refus.status, {"erreur": refus.message}
        except OSError as trouble:
            return 500, {"erreur": f"écriture impossible : {str(trouble)[:120]}"}
