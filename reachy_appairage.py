#!/usr/bin/env python3
"""L'appairage des appareils qui ouvrent la page du robot (18/10/2026).

La page est sur le réseau local, sans compte. Avant : quiconque joignait l'adresse recevait le jeton d'écriture,
voyait l'image de la pièce, les caméras, les personnes, et pouvait ajouter un badge NFC (revue Codex du 18/10).
Maintenant, chaque appareil s'appaire UNE fois :

1. l'appareil inconnu demande un code (`demander`) ; le robot le DIT à voix haute (`annoncer`), et le corps l'écrit
   à son journal (la machine sans voix le lit là) — il faut donc être dans la pièce, ou sur la machine ;
2. on tape le code (`valider`) : 6 chiffres, valable 3 minutes, à usage unique, 5 essais, puis 5 minutes d'attente ;
3. l'appareil reçoit un jeton à lui (32 octets aléatoires), gardé par son navigateur et envoyé avec chaque demande
   (en-tête, ou paramètre pour une image) : ça marche aussi dans un cadre de Home Assistant, où un cookie d'un
   autre site serait refusé.

Le robot ne garde que l'EMPREINTE de chaque jeton (sha256), dans un fichier 600 à côté de ses réglages. Révoquer
un appareil = retirer son empreinte. Bibliothèque standard seulement.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time

CODE_DUREE = 180.0                 # secondes de validité d'un code
CODE_PAUSE = 30.0                  # secondes entre deux demandes de code
ESSAIS = 5                         # échecs par appareil (adresse) avant blocage, QUEL QUE SOIT le code
BLOCAGE = 300.0                    # secondes : fenêtre de comptage des échecs, et durée du blocage
ECHECS_TOUS = 20                   # échecs, toutes adresses confondues, avant de fermer l'appairage (force brute répartie)
NOM_MAX = 40
VU_ECRIRE = 600.0                  # « vu à » réécrit au plus toutes les 10 minutes
APPAREILS_MAX = 20


class Refus(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def empreinte(jeton):
    return hashlib.sha256(str(jeton).encode()).hexdigest()


class Appairage:
    def __init__(self, fichier=None, annoncer=None, noter=lambda texte: None, horloge=time.monotonic, maintenant=time.time,
                 trouver_annonce=None):
        """`annoncer(phrase)` fait parler le robot ; ou `trouver_annonce()` le rend au moment de la demande (un corps
        peut brancher sa voix APRÈS avoir créé la page)."""
        self.fichier = Path(fichier) if fichier else None
        self.annoncer, self.noter = annoncer, noter
        self.trouver_annonce = trouver_annonce
        self.horloge, self.maintenant = horloge, maintenant
        self.lock = threading.Lock()
        self.code = None               # {"valeur", "fin"}
        self.derniere_demande = -1e9
        self.bloque_jusqu = 0.0        # tout l'appairage fermé (trop d'échecs, toutes adresses)
        self.echecs = []               # [(heure, adresse)] — comptés hors du code : en redemander un ne remet rien à zéro
        self.appareils = self._lire()

    # --- fichier ------------------------------------------------------------------------------------------------
    def _lire(self):
        if self.fichier is None:
            return []
        try:
            if self.fichier.is_symlink():
                return []
            data = json.loads(self.fichier.read_text())
        except (OSError, ValueError):
            return []
        items = data.get("appareils") if isinstance(data, dict) else None
        return [a for a in (items or []) if isinstance(a, dict) and isinstance(a.get("empreinte"), str)
                and len(a["empreinte"]) == 64 and isinstance(a.get("id"), str)][:APPAREILS_MAX]

    def _ecrire(self):
        if self.fichier is None:
            return
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        if self.fichier.is_symlink() or self.fichier.parent.is_symlink():
            raise OSError("registre des appareils : un lien n'est jamais suivi")
        # Temporaire EXCLUSIF au nom imprévisible (mkstemp : O_EXCL, 600), puis renommage atomique.
        fd, tmp = tempfile.mkstemp(prefix=".appareils-", dir=str(self.fichier.parent))
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(json.dumps({"appareils": self.appareils}, ensure_ascii=False, indent=2) + "\n")
            os.replace(tmp, self.fichier)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # --- le code ------------------------------------------------------------------------------------------------
    def demander(self):
        """Un nouveau code, dit par le robot et écrit au journal LOCAL de la machine. → {"voix": bool}.
        Un code en cours n'est jamais remplacé : personne ne peut annuler celui qu'on est en train de taper."""
        maintenant = self.horloge()
        with self.lock:
            if maintenant < self.bloque_jusqu:
                raise Refus(429, "trop d'essais : réessayer dans quelques minutes")
            if self.code and maintenant <= self.code["fin"]:
                raise Refus(409, "un code est déjà en cours (3 minutes) : le taper, ou attendre")
            if maintenant - self.derniere_demande < CODE_PAUSE:
                raise Refus(429, "un code vient d'être demandé : patienter 30 s")
            if len(self.appareils) >= APPAREILS_MAX:
                raise Refus(409, f"{APPAREILS_MAX} appareils au plus : en révoquer un d'abord")
            valeur = f"{secrets.randbelow(10 ** 6):06d}"
            self.code = {"valeur": valeur, "fin": maintenant + CODE_DUREE}
            self.derniere_demande = maintenant
        dicte = ", ".join(valeur)
        # Le code part au journal de la MACHINE (stderr → journalctl), jamais au journal du corps que la page
        # montre aux appareils déjà appairés (revue Codex du 18/10). Ce journal-là dit seulement qu'un code existe.
        print(f"reachy-page : code d'appairage {valeur} (valable 3 minutes)", file=sys.stderr, flush=True)
        self.noter("appairage : un code a été demandé (dit par le robot et écrit au journal de la machine)")
        voix = False
        annoncer = self.annoncer or (self.trouver_annonce() if self.trouver_annonce else None)
        if annoncer is not None:
            threading.Thread(target=annoncer, args=(f"Code d'appairage : {dicte}.",), daemon=True).start()
            voix = True
        return {"voix": voix, "duree": int(CODE_DUREE)}

    def valider(self, code, nom="", adresse=""):
        """Le bon code → {"jeton", "id"} (le jeton n'est rendu qu'ici, une fois). Sinon Refus.
        Les échecs se comptent par adresse ET au total, sur 5 minutes, indépendamment du code : en redemander
        un ne remet rien à zéro (revue Codex du 18/10)."""
        maintenant = self.horloge()
        nom = " ".join(str(nom or "").split())[:NOM_MAX] or "appareil"
        with self.lock:
            self.echecs = [(t, a) for t, a in self.echecs if maintenant - t < BLOCAGE]
            if maintenant < self.bloque_jusqu:
                raise Refus(429, "trop d'essais : réessayer dans quelques minutes")
            if sum(1 for _, a in self.echecs if a == adresse) >= ESSAIS:
                raise Refus(429, "trop d'essais depuis cet appareil : réessayer dans 5 minutes")
            actif = self.code
            if not actif or maintenant > actif["fin"]:
                self.code = None
                raise Refus(409, "pas de code en cours : en demander un")
            if not hmac.compare_digest(str(code or "").strip().encode(), actif["valeur"].encode()):
                self.echecs.append((maintenant, adresse))
                if len(self.echecs) >= ECHECS_TOUS:
                    self.code = None
                    self.bloque_jusqu = maintenant + BLOCAGE
                    raise Refus(429, "trop d'essais : appairage fermé 5 minutes")
                raise Refus(403, "code incorrect")
            self.code = None               # à usage unique
            jeton = secrets.token_urlsafe(32)
            ident = secrets.token_hex(4)
            quand = int(self.maintenant())
            self.appareils.append({"id": ident, "nom": nom, "empreinte": empreinte(jeton), "cree": quand, "vu": quand})
            self._ecrire()
        self.noter(f"appareil appairé : {nom}")
        return {"jeton": jeton, "id": ident}

    # --- les appareils ------------------------------------------------------------------------------------------
    def reconnaitre(self, jeton):
        """L'appareil de ce jeton, ou None. Comparaison à temps constant, sur les empreintes."""
        if not jeton or not isinstance(jeton, str) or len(jeton) > 200:
            return None
        cherche = empreinte(jeton)
        with self.lock:
            trouve = None
            for appareil in self.appareils:
                if hmac.compare_digest(appareil["empreinte"], cherche):
                    trouve = appareil
            if trouve is not None and self.maintenant() - trouve.get("vu", 0) > VU_ECRIRE:
                trouve["vu"] = int(self.maintenant())
                try:
                    self._ecrire()
                except OSError:
                    pass
            return trouve

    def liste(self, actuel=None):
        with self.lock:
            return [{"id": a["id"], "nom": a.get("nom", ""), "cree": a.get("cree"), "vu": a.get("vu"),
                     "moi": actuel is not None and a["id"] == actuel.get("id")} for a in self.appareils]

    def revoquer(self, ident):
        with self.lock:
            avant = len(self.appareils)
            self.appareils = [a for a in self.appareils if a["id"] != str(ident)]
            if len(self.appareils) == avant:
                raise Refus(404, "appareil inconnu")
            self._ecrire()
        self.noter("appareil révoqué")
        return {"ok": True}
