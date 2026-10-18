#!/usr/bin/env python3
"""La rubrique « Maison » de la page de réglages : ce que Home Assistant fait avec le robot, EN LECTURE SEULE
(11/10/2026, spec `2026-10-11-reachy-page-reglages.md`, lot 6 ; choix initial : lecture seule + lien vers HA).

- Une liste FERMÉE : les automatisations du robot et les trois entités qu'il publie. Rien d'autre n'est lu,
  rien n'est écrit (aucune action sur une automatisation, ici).
- Le module ne connaît NI le jeton NI l'adresse de Home Assistant. Le corps de la machine du robot, qui les a déjà
  (`ha.json`), passe à la page un LECTEUR : `body.lecteur_ha = lecteur`, une fonction `lecteur(ids) ->
  {entity_id: état ou None}` qui lève une exception si HA ne répond pas. `lecteur_http()` en fabrique un,
  avec l'adresse et le jeton que le corps lui donne (le jeton reste dans la fonction, jamais servi).
- Un cache (30 s) : la page peut interroger souvent, Home Assistant est lu au plus une fois par période.
  Un échec est gardé 10 s seulement. Sans lecteur ou sans HA, la page marche : les lignes disent « inconnu ».
Bibliothèque standard seulement.
"""
import json
import re
import threading
import time
import urllib.request

CACHE = 30.0                       # secondes entre deux lectures de Home Assistant
CACHE_ECHEC = 10.0                 # après un échec, on réessaie plus vite
DELAI = 3.0                        # secondes d'attente de Home Assistant au plus
VALEUR_MAX = 300                   # caractères gardés d'une valeur publiée

# La liste fermée vient du fichier de réglages du corps (`vivant.json`, clé « maison ») : CE QUE la maison fait
# avec le robot est propre à chaque maison, jamais dans le code (18/10 : prénoms et automatisations sortis du
# dépôt). Sans clé : liste vide, la rubrique dit qu'il n'y a rien à montrer.
#   "maison": {"automatisations": [[entité, intitulé, aide, groupe, sonore], …],
#              "publie": [[entité, intitulé, aide], …]}
AUTOMATISATIONS = ()               # (entité, intitulé, aide, groupe, sonore)
PUBLIE = ()                        # (entité, intitulé, aide) : ce que le robot publie dans HA
IDS = ()
ENTITE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def configurer(conf):
    """Pose la liste fermée depuis `alive["maison"]`. Une ligne mal formée est ignorée, jamais devinée."""
    global AUTOMATISATIONS, PUBLIE, IDS
    conf = conf if isinstance(conf, dict) else {}

    def lignes(cle, taille):
        out = []
        valeurs = conf.get(cle)
        for ligne in valeurs if isinstance(valeurs, (list, tuple)) else ():
            if isinstance(ligne, (list, tuple)) and len(ligne) == taille and isinstance(ligne[0], str) \
                    and ENTITE.fullmatch(ligne[0]) and all(isinstance(x, str) for x in ligne[1:4][:taille - 1]):
                out.append(tuple(ligne[:taille - 1]) + ((bool(ligne[-1]),) if taille == 5 else (ligne[-1],)))
        return tuple(out)
    AUTOMATISATIONS = lignes("automatisations", 5)
    PUBLIE = lignes("publie", 3)
    IDS = tuple(dict.fromkeys(e[0] for e in AUTOMATISATIONS + PUBLIE))


def lecteur_http(url, jeton, delai=DELAI):
    """Un lecteur de Home Assistant pour le corps : UN seul appel (`/api/template`) lit toute la liste fermée.
    `url` et `jeton` viennent du corps (jamais lus ici) ; le jeton reste dans la fonction. Lève une exception si
    HA ne répond pas. Une entité qui n'existe pas rend None."""
    url = str(url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")) or not jeton:
        raise ValueError("lecteur HA : une adresse http(s) et un jeton sont nécessaires")
    entetes = {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"}

    def lire(ids):
        # Les identifiants viennent de la liste fermée ci-dessus : on les revérifie avant de les mettre dans le modèle.
        if not all(i in IDS for i in ids):
            raise ValueError("lecteur HA : entité hors de la liste")
        modele = "{{ {" + ", ".join(
            f'"{i}": (states["{i}"].state if states["{i}"] is not none else none)' for i in ids) + "} | tojson }}"
        demande = urllib.request.Request(url + "/api/template", json.dumps({"template": modele}).encode(),
                                         entetes, method="POST")
        with urllib.request.urlopen(demande, timeout=delai) as reponse:
            lu = json.loads(reponse.read(65536))
        if not isinstance(lu, dict):
            raise ValueError("lecteur HA : réponse inattendue")
        return lu
    return lire


def _etat(valeur):
    if valeur is None:
        return "absente"
    valeur = str(valeur)
    return valeur if valeur in ("on", "off") else ("indisponible" if valeur in ("unavailable", "unknown") else valeur[:20])


class Maison:
    """L'instantané « Maison » de la page : lecture mise en cache, un seul appel à HA à la fois.
    `source()` rend le lecteur du moment (ou None) — le corps peut le poser après le démarrage de la page."""

    def __init__(self, source, horloge=time.monotonic):
        self.source = source
        self.horloge = horloge
        self.verrou = threading.Lock()
        self.cache = None                  # (heure, durée de validité, lecture ou None, erreur)

    def _lire(self, now):
        if not IDS:                        # maison non déclarée : rien à lire, HA n'est pas dérangé
            return {}, "", CACHE
        lecteur = self.source()
        if lecteur is None:
            return None, "pas de lecteur Home Assistant dans le corps", CACHE_ECHEC
        try:
            lu = lecteur(IDS)
            if not isinstance(lu, dict):
                raise ValueError("réponse inattendue")
            return lu, "", CACHE
        except Exception:                  # HA éteint, jeton refusé, délai dépassé : la page vit sans lui
            return None, "Home Assistant ne répond pas", CACHE_ECHEC

    def instantane(self):
        with self.verrou:
            now = self.horloge()
            if self.cache is None or now - self.cache[0] >= self.cache[1]:
                lu, erreur, duree = self._lire(now)
                self.cache = (now, duree, lu, erreur)
            heure, _, lu, erreur = self.cache
            age = round(now - heure, 1)
        connu = lu is not None
        return {
            "ha": {"disponible": connu, "age": age, "erreur": erreur},
            "automatisations": [{"id": i, "intitule": t, "aide": a, "groupe": g, "sonore": s,
                                 "etat": _etat(lu.get(i)) if connu else "inconnu"}
                                for i, t, a, g, s in AUTOMATISATIONS],
            "publie": [{"id": i, "intitule": t, "aide": a,
                        "valeur": (str(lu.get(i))[:VALEUR_MAX] if lu.get(i) is not None else None) if connu else None}
                       for i, t, a in PUBLIE],
        }
