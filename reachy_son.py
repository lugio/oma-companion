#!/usr/bin/env python3
"""Le volume de SA voix, partagé entre le corps et la page (rubrique « Parler », 11/10/2026).

Interface de réglage du son et de la parole.
Né d'une panne muette : le haut-parleur du robot (réglage interne `PCM`,1 de sa puce son) retombait à -20 dB à
chaque reconnexion USB, et personne ne pouvait voir lequel des étages du son baissait la voix.

Quatre étages, montrés côte à côte : le volume voulu (`normal`, réglé ici), la voix du soir (`facteur` posé par
le fil du soir du corps), le haut-parleur (posé par la garde du corps), et le volume réellement appliqué.

`Voix` ne parle à aucun matériel : le corps lui donne ses fonctions (`poser` le volume, `annoncer` une phrase,
`etat_corps`, `est_soir`). Sans `body.voix` (Alison au bureau, essais), la rubrique dit « non disponible ».
Routes : `GET /api/son` (l'état), `POST /api/son/volume` {"normal": 0.1…1.0}, `POST /api/son/essai`,
`POST /api/son/ecouter` {"son": "eveil"|"reflexion"} (le son choisi dans « Ses sons », joué sur le robot),
`POST /api/son/mimique` {"mimique": "confused1"|…} (la mimique « pas compris », jouée par le corps).
"""
import json
import os
import threading
import time
from http import HTTPStatus
from pathlib import Path

PREFIXE = "/api/son"
VOLUME_MIN, VOLUME_MAX = 0.1, 1.0
PHRASE_ESSAI = "Voici ma voix, à ce volume."
ESSAI_PAUSE = 8.0                  # secondes entre deux essais (ou deux écoutes)
SONS = ("eveil", "reflexion")      # les sons qu'on peut écouter (choisis par les réglages `son_eveil`, `son_reflexion`)
MIMIQUES = ("confused1", "incomprehensible2")   # les émotions Pollen du réglage `mimique_incompris` (liste fermée)


class Voix:
    """L'état du volume ({"normal", "applique", "manuel"} dans `fichier`), sous verrou : le fil du soir du corps
    et la page le lisent et l'écrivent tous les deux."""

    def __init__(self, fichier, poser, annoncer=None, etat_corps=lambda: ("idle", False),
                 est_soir=lambda: False, lire=lambda: None, horloge=time.monotonic, noter=lambda texte: None,
                 jouer=None, mimer=None):
        self.fichier = Path(fichier) if fichier else None
        self.noter, self.jouer, self.mimer = noter, jouer, mimer
        self.poser, self.annoncer, self.etat_corps = poser, annoncer, etat_corps
        self.est_soir, self.lire, self.horloge = est_soir, lire, horloge
        self.lock = threading.Lock()
        self.cran, self.facteur = "normal", 1.0
        self.haut_parleur = {"niveau": None, "remis": None, "retombe": None, "garde": True}
        self.enregistre = None              # le niveau que la machine remet au rebranchement (dB), ou None
        self.dernier_essai = -1e9
        try:
            self.etat = json.loads(self.fichier.read_text())
            float(self.etat["normal"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            actuel = lire()
            self.etat = {"normal": actuel or 1.0, "applique": None, "manuel": False}

    def sauver(self):
        """Écriture atomique (appelée sous verrou)."""
        if self.fichier is None:
            return
        tmp = self.fichier.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.etat))
        os.replace(tmp, self.fichier)

    def noter_cran(self, cran, facteur):
        with self.lock:
            self.cran, self.facteur = cran, float(facteur)

    def noter_haut_parleur(self, niveau, retombe=None, garde=True):
        """La garde du corps dit le niveau du haut-parleur ; `retombe` = le niveau trouvé avant de le remettre."""
        with self.lock:
            self.haut_parleur.update(niveau=niveau, garde=bool(garde))
            if retombe is not None:
                self.haut_parleur.update(retombe=retombe, remis=time.strftime("%H:%M"))

    def regler(self, normal):
        """Le volume voulu, appliqué tout de suite (multiplié par la voix du soir du moment). → l'état public."""
        if isinstance(normal, bool) or not isinstance(normal, (int, float)):
            raise ValueError("volume : un nombre attendu")
        if not VOLUME_MIN <= normal <= VOLUME_MAX:
            raise ValueError(f"volume : entre {VOLUME_MIN:.0%} et {VOLUME_MAX:.0%}")
        with self.lock:
            normal = round(float(normal), 2)
            cible = round(normal * self.facteur, 2)
            self.poser(cible)
            self.etat.update(normal=normal, applique=cible, manuel=False)
            self.sauver()
        self.noter(f"volume de sa voix réglé à {round(normal * 100)} % (appliqué : {round(cible * 100)} %)")
        return self.public()

    def essayer(self):
        """Une courte phrase au volume réglé. → (True, None) ou (False, raison en français)."""
        if self.annoncer is None:
            return False, "essai indisponible"
        return self._jouer_si_permis("essai du son demandé", self.annoncer, PHRASE_ESSAI)

    def ecouter(self, son):
        """Le son choisi (`eveil` ou `reflexion`), joué sur le robot. Mêmes refus que l'essai."""
        if son not in SONS:
            raise ValueError("son inconnu")
        if self.jouer is None:
            return False, "écoute indisponible"
        return self._jouer_si_permis(f"écoute du son « {son} » demandée", self.jouer, son)

    def montrer(self, mimique):
        """La mimique « pas compris » jouée par le corps (ses émotions ont un son). Mêmes refus que l'essai."""
        if mimique not in MIMIQUES:
            raise ValueError("mimique inconnue")
        if self.mimer is None:
            return False, "mimique indisponible"
        return self._jouer_si_permis(f"mimique « {mimique} » demandée", self.mimer, mimique)

    def _jouer_si_permis(self, note, action, argument):
        etat, dort = self.etat_corps()
        if dort:
            return False, "il dort : le réveiller d'abord"
        if etat != "idle":
            return False, "il est occupé (conversation en cours)"
        if self.est_soir():
            return False, "pas le soir : la maison se repose"
        maintenant = self.horloge()
        with self.lock:
            if maintenant - self.dernier_essai < ESSAI_PAUSE:
                return False, "un essai vient d'être fait"
            self.dernier_essai = maintenant
        self.noter(note)
        threading.Thread(target=action, args=(argument,), daemon=True).start()
        return True, None

    def public(self):
        with self.lock:
            normal = float(self.etat.get("normal") or 1.0)
            return {"disponible": True, "normal": normal, "cran": self.cran, "facteur": self.facteur,
                    "applique": round(normal * self.facteur, 2) if not self.etat.get("manuel") else self.etat.get("applique"),
                    "manuel": bool(self.etat.get("manuel")), "haut_parleur": dict(self.haut_parleur),
                    "enregistre": self.enregistre, "min": VOLUME_MIN, "max": VOLUME_MAX}


def route(voix, methode, chemin, demande=None):
    """→ (statut HTTP, réponse JSON). `voix` = `body.voix` ou None."""
    if methode == "GET" and chemin == PREFIXE:
        return HTTPStatus.OK, (voix.public() if voix is not None else {"disponible": False})
    if methode != "POST" or chemin not in (PREFIXE + "/volume", PREFIXE + "/essai", PREFIXE + "/ecouter",
                                           PREFIXE + "/mimique"):
        return HTTPStatus.NOT_FOUND, {"erreur": "inconnu"}
    if voix is None:
        return HTTPStatus.CONFLICT, {"erreur": "le son ne se règle pas sur cette machine"}
    if chemin.endswith("/volume"):
        try:
            normal = (demande or {}).get("normal") if isinstance(demande, dict) else None
            return HTTPStatus.OK, voix.regler(normal)
        except ValueError as trouble:
            return HTTPStatus.BAD_REQUEST, {"erreur": str(trouble)}
        except Exception as trouble:                 # pactl absent ou en erreur : rien n'est enregistré
            return HTTPStatus.INTERNAL_SERVER_ERROR, {"erreur": f"volume impossible : {str(trouble)[:120]}"}
    if chemin.endswith("/mimique"):
        try:
            ok, raison = voix.montrer((demande or {}).get("mimique") if isinstance(demande, dict) else None)
        except ValueError as trouble:
            return HTTPStatus.BAD_REQUEST, {"erreur": str(trouble)}
        return (HTTPStatus.OK, {"ok": True}) if ok else (HTTPStatus.CONFLICT, {"erreur": raison})
    if chemin.endswith("/ecouter"):
        try:
            ok, raison = voix.ecouter((demande or {}).get("son") if isinstance(demande, dict) else None)
        except ValueError as trouble:
            return HTTPStatus.BAD_REQUEST, {"erreur": str(trouble)}
        return (HTTPStatus.OK, {"ok": True}) if ok else (HTTPStatus.CONFLICT, {"erreur": raison})
    ok, raison = voix.essayer()
    return (HTTPStatus.OK, {"ok": True}) if ok else (HTTPStatus.CONFLICT, {"erreur": raison})
