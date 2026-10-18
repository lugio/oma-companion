#!/usr/bin/env python3
"""Caméras de la maison (11/10/2026) : trier les visages vus par les caméras, pour apprendre.

Principe, façon Picasa : quand une caméra de la maison voit quelqu'un, le collecteur (propre à la machine,
un programme de la machine du robot) range les gros plans des visages et leurs empreintes SFace dans un dossier, un
sous-dossier par passage. La page (rubrique « Caméras ») les montre, regroupés par ressemblance, avec ce que
le robot en pense ; la personne indique qui c'est. Un tri devient UNE séance « caméra » par personne et par caméra
(empreintes fusionnées, pondérées par le nombre de vues), visible et oubliable dans Apprentissage : le robot
reconnaît alors la famille telle que la caméra la voit (de haut, de loin, dehors), pas seulement de près.

Vie privée (règles locales) :
- tout reste sur la machine : dossier 700, fichiers 600 ; rien n'est envoyé ailleurs ;
- un passage non trié est effacé après `cams_garder` jours ; un groupe trié ou ignoré est effacé tout de suite
  (seule l'empreinte apprise reste, dans le fichier de la personne) ;
- la page ne reçoit jamais d'empreinte ni de chemin ; une image n'est servie qu'avec le jeton de la page ;
- un nom n'est appris que pour une personne qui a donné son accord (celui d'Apprentissage, ou noté ici).

Disposition : `<dossier>/<id>/passage.json` + `v001.jpg`… ; `passage.json` = {"id", "camera", "debut", "fin",
"vues": [{"f", "t", "empreinte", "net", "taille"}], "tries": {"<groupe>": {"nom" | "ignore", "le", "garde"}}}.
`<dossier>/historique.json` : les derniers tris (date, caméra, nom ou « ignoré », nombre de vues).
"""
import json
import re
import shutil
import threading
import time
from pathlib import Path

import reachy_apprendre
import reachy_personnes
from reachy_personnes import Refus, nom_sur

PREFIXE = "/api/cams"
GROUPE_SEUIL = 0.40         # ressemblance (cosinus SFace) pour mettre deux vues dans le même groupe
                            # (0,50 au début : un passage de la terrasse en 5 groupes, trop de clics ; 0,40 → 3)
VOTE_MIN = 2                # vues d'accord au moins pour proposer un nom
GARDER_JOURS = 7            # passages non triés gardés (réglage `cams_garder`)
HISTORIQUE_MAX = 50
VUES_MAX = 40               # vues gardées au plus par passage (les plus nettes)
ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,30}$")
# 11/10 (test local) : aussi les animaux (chien, chat) et les véhicules (sa voiture, le facteur). Ils sont étiquetés, pas
# « appris » comme un visage : chaque tri ajoute un EXEMPLE à l'étiquette (`etiquettes.json` du dossier).
GENRES = ("visage", "animal", "vehicule")
OBJET_GROUPE = 0.80         # ressemblance (`reachy_objets.ressemblance`) pour un même groupe d'objets
OBJET_MIN, OBJET_ECART = 0.80, 0.05     # proposer une étiquette : assez ressemblant, et devant la suivante
EXEMPLES_MAX = 40           # exemples gardés par étiquette (les plus récents)
PLAQUE_ACCORD = 3           # 12/10 : images lisant le MÊME texte au moins pour qu'une plaque soit sûre
PLAQUES_MAX = 5             # plaques gardées par étiquette (les véhicules peuvent changer)
PLAQUE = re.compile(r"^[A-Z0-9]{4,10}$")
FICHIER = re.compile(r"^v[0-9]{3}\.jpg$")
# Les caméras sont celles de chaque maison : n'importe quel identifiant bien formé est accepté (le collecteur
# de la machine les nomme), et leur libellé vient du fichier de réglages du corps (clé « cameras_noms » :
# {"identifiant": "Libellé"}), sinon l'identifiant lui-même (18/10 : plus de caméras figées dans le code).
CAMERAS = {}
CAMERA_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,20}")


def configurer(conf):
    global CAMERAS
    conf = conf if isinstance(conf, dict) else {}
    CAMERAS = {cle: str(nom)[:40] for cle, nom in conf.items()
               if isinstance(cle, str) and CAMERA_ID.fullmatch(cle) and isinstance(nom, str) and nom.strip()}


def _normer(v):
    n = sum(float(x) * float(x) for x in v) ** 0.5 or 1.0
    return [float(x) / n for x in v]


def _cos(a, b):
    return sum(float(x) * float(y) for x, y in zip(a, b))


def grouper(vecteurs, seuil=GROUPE_SEUIL):
    """Les vues d'un passage en groupes de même personne : [[indices]]. Chaque vue rejoint le groupe dont le
    centre lui ressemble le plus (≥ seuil), sinon en ouvre un. Les plus grands groupes d'abord. Pur, testable."""
    groupes, centres = [], []
    for i, v in enumerate(vecteurs):
        v = _normer(v)
        notes = [_cos(v, c) for c in centres]
        if notes and max(notes) >= seuil:
            k = notes.index(max(notes))
            groupes[k].append(i)
            somme = [a * (len(groupes[k]) - 1) + b for a, b in zip(centres[k], v)]
            centres[k] = _normer(somme)
        else:
            groupes.append([i])
            centres.append(v)
    return sorted(groupes, key=len, reverse=True)


def proposer(vecteurs, sets, least, gap):
    """Ce que le robot pense d'un groupe : chaque vue vote (`reachy_vue.decide`, mêmes seuils que le robot) ;
    un nom n'est proposé que s'il a au moins VOTE_MIN voix ET la majorité des vues, sans autre nom en face.
    → {"nom" ou None, "score" (meilleure ressemblance du nom ou de la meilleure personne), "voix", "sur"}. Pur."""
    votes, meilleurs = {}, {}
    for v in vecteurs:
        v = _normer(v)
        scores = {nom: max(_cos(v, p) for p in ps) for nom, ps in sets.items() if ps}
        if not scores:
            continue
        rang = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        nom, best = rang[0]
        second = rang[1][1] if len(rang) > 1 else 0.0
        meilleurs[nom] = max(meilleurs.get(nom, -1.0), best)
        if best >= least and best - second >= gap:
            votes[nom] = votes.get(nom, 0) + 1
    sur = len(vecteurs)
    if len(votes) == 1:
        nom, n = next(iter(votes.items()))
        if n >= VOTE_MIN and n * 2 >= sur:
            return {"nom": nom, "score": round(meilleurs[nom], 2), "voix": n, "sur": sur}
    if meilleurs:
        nom = max(meilleurs, key=meilleurs.get)
        return {"nom": None, "pres": nom, "score": round(meilleurs[nom], 2), "voix": votes.get(nom, 0), "sur": sur,
                "desaccord": len(votes) > 1}
    return {"nom": None, "score": 0.0, "voix": 0, "sur": sur}


def _ecrire(chemin, octets):
    """Écrit un fichier 600 de façon atomique."""
    chemin = Path(chemin)
    tmp = chemin.with_name("." + chemin.name + ".tmp")
    tmp.write_bytes(octets)
    tmp.chmod(0o600)
    tmp.replace(chemin)


def ressemblance_objets(a, b):
    """Deux vues d'objet ({"empreinte", "couleur"}) : 0,7 × apparence + 0,3 × couleur. Pure."""
    app = _cos(_normer(a["empreinte"]), _normer(b["empreinte"]))
    if a.get("couleur") and b.get("couleur"):
        return 0.7 * app + 0.3 * _cos(_normer(a["couleur"]), _normer(b["couleur"]))
    return app


def grouper_objets(vues, seuil=None):
    """Comme `grouper`, pour des vues d'objet (apparence + couleur) ; chaque vue rejoint le groupe dont elle
    ressemble le plus à la PREMIÈRE vue. Pur."""
    seuil = OBJET_GROUPE if seuil is None else seuil
    groupes = []
    for i, v in enumerate(vues):
        notes = [ressemblance_objets(v, vues[g[0]]) for g in groupes]
        if notes and max(notes) >= seuil:
            groupes[notes.index(max(notes))].append(i)
        else:
            groupes.append([i])
    return sorted(groupes, key=len, reverse=True)


def lire_etiquettes(dossier):
    """{genre: {nom: {"affiche", "cacher", "exemples": [{"empreinte", "couleur", ...}]}}}."""
    try:
        donnees = json.loads((Path(dossier) / "etiquettes.json").read_text())
        return {g: donnees.get(g) if isinstance(donnees.get(g), dict) else {} for g in GENRES[1:]}
    except (OSError, ValueError, TypeError):
        return {g: {} for g in GENRES[1:]}


def plaque_sure(vues):
    """12/10 : la plaque d'un groupe de vues de véhicule, si au moins PLAQUE_ACCORD images lisent le même texte
    et qu'il a la majorité des lectures ; sinon None. Pur."""
    lues = [v.get("plaque") for v in vues if PLAQUE.match(str(v.get("plaque") or ""))]
    if not lues:
        return None
    texte, n = max(((t, lues.count(t)) for t in set(lues)), key=lambda c: c[1])
    return texte if n >= PLAQUE_ACCORD and 2 * n > len(lues) else None


def proposer_objet(vues, etiquettes):
    """Ce que le robot pense d'un groupe d'objets : chaque vue vote pour l'étiquette la plus ressemblante
    (≥ OBJET_MIN et OBJET_ECART devant la suivante) ; majorité et VOTE_MIN comme pour les visages. Pur.
    12/10 : une plaque sûre PRIME : connue → ce nom ; différente des plaques d'une étiquette → jamais ce nom
    (deux voitures pareilles ne se confondent plus)."""
    plaque = plaque_sure(vues)
    if plaque:
        for nom, e in etiquettes.items():
            if plaque in (e.get("plaques") or []):
                return {"nom": nom, "score": 1.0, "voix": len(vues), "sur": len(vues), "plaque": plaque, "par": "plaque"}
        etiquettes = {n: e for n, e in etiquettes.items() if not e.get("plaques")}
    avis = _proposer_apparence(vues, etiquettes)
    if plaque:
        avis["plaque"] = plaque
    return avis


def _proposer_apparence(vues, etiquettes):
    votes, meilleurs = {}, {}
    for v in vues:
        notes = {nom: max((ressemblance_objets(v, x) for x in e.get("exemples") or []), default=-1.0)
                 for nom, e in etiquettes.items()}
        notes = {n: s for n, s in notes.items() if s > -1.0}
        if not notes:
            continue
        rang = sorted(notes.items(), key=lambda kv: kv[1], reverse=True)
        nom, best = rang[0]
        second = rang[1][1] if len(rang) > 1 else 0.0
        meilleurs[nom] = max(meilleurs.get(nom, -1.0), best)
        if best >= OBJET_MIN and best - second >= OBJET_ECART:
            votes[nom] = votes.get(nom, 0) + 1
    sur = len(vues)
    if len(votes) == 1:
        nom, n = next(iter(votes.items()))
        if n >= min(VOTE_MIN, sur) and n * 2 >= sur:
            return {"nom": nom, "score": round(meilleurs[nom], 2), "voix": n, "sur": sur}
    if meilleurs:
        nom = max(meilleurs, key=meilleurs.get)
        return {"nom": None, "pres": nom, "score": round(meilleurs[nom], 2), "voix": votes.get(nom, 0), "sur": sur,
                "desaccord": len(votes) > 1}
    return {"nom": None, "score": 0.0, "voix": 0, "sur": sur}


def a_cacher(dossier, genre, empreinte, couleur, plaque=None):
    """Le collecteur : cette découpe ressemble-t-elle à une étiquette « toujours ignorer » (voiture garée) ?
    12/10 : avec une plaque lue, seule la plaque compte pour une étiquette qui a des plaques."""
    v = {"empreinte": empreinte, "couleur": couleur}
    for e in lire_etiquettes(dossier).get(genre, {}).values():
        if not e.get("cacher"):
            continue
        if plaque and e.get("plaques"):
            if plaque in e["plaques"]:
                return True
            continue
        if any(ressemblance_objets(v, x) >= OBJET_MIN for x in e.get("exemples") or []):
            return True
    return False


def ecrire_passage(dossier, camera, vues, debut=None, fin=None, genre="visage"):
    """Le collecteur range un passage. `vues` = [(jpeg, empreinte, net, taille, t[, {"couleur", "classe"}])].
    Les VUES_MAX plus nettes sont gardées. → l'identifiant du passage, ou None s'il n'y a rien à garder."""
    if not isinstance(camera, str) or not CAMERA_ID.fullmatch(camera) or genre not in GENRES or not vues:
        return None
    suffixe = camera if genre == "visage" else f"{camera}-{genre}"
    vues = sorted(vues, key=lambda v: (v[2], v[3]), reverse=True)[:VUES_MAX]
    vues.sort(key=lambda v: v[4])
    debut = debut if debut is not None else vues[0][4]
    base = Path(dossier)
    base.mkdir(parents=True, exist_ok=True)
    base.chmod(0o700)
    seconde = int(debut)
    while (base / (time.strftime("%Y%m%d-%H%M%S", time.localtime(seconde)) + "-" + suffixe)).exists():
        seconde += 1                       # deux passages dans la même seconde : jamais l'un sur l'autre
    ident = time.strftime("%Y%m%d-%H%M%S", time.localtime(seconde)) + "-" + suffixe
    rep = base / ident
    rep.mkdir(mode=0o700)
    fiche = {"id": ident, "camera": camera, "genre": genre, "debut": round(debut, 1),
             "fin": round(fin or vues[-1][4], 1), "vues": [], "tries": {}}
    for i, (jpeg, empreinte, net, taille, t, *extra) in enumerate(vues, 1):
        nom = f"v{i:03d}.jpg"
        _ecrire(rep / nom, bytes(jpeg))
        vue = {"f": nom, "t": round(t, 1), "empreinte": [round(float(x), 6) for x in empreinte],
               "net": round(float(net), 3), "taille": int(taille)}
        if extra and isinstance(extra[0], dict):
            if extra[0].get("couleur"):
                vue["couleur"] = [round(float(x), 6) for x in extra[0]["couleur"]]
            if extra[0].get("classe"):
                vue["classe"] = str(extra[0]["classe"])[:20]
            if PLAQUE.match(str(extra[0].get("plaque") or "")):
                vue["plaque"] = str(extra[0]["plaque"])
        fiche["vues"].append(vue)
    # Les groupes sont FIGÉS ici : un changement de seuil ne décale jamais un passage à moitié trié.
    fiche["groupes"] = (grouper([v["empreinte"] for v in fiche["vues"]]) if genre == "visage"
                        else grouper_objets(fiche["vues"]))
    _ecrire(rep / "passage.json", json.dumps(fiche).encode())
    return ident


def groupes(fiche):
    """Les groupes d'un passage : ceux figés à l'écriture (sinon calculés, ancien passage)."""
    figes = fiche.get("groupes")
    if isinstance(figes, list) and all(isinstance(g, list) for g in figes):
        return figes
    if fiche.get("genre", "visage") != "visage":
        return grouper_objets(fiche.get("vues") or [])
    return grouper([v["empreinte"] for v in fiche.get("vues") or []])


def purger(dossier, jours, maintenant=None):
    """Efface les passages plus vieux que `jours` (triés ou non). → nombre de passages effacés."""
    base = Path(dossier)
    if not base.is_dir():
        return 0
    limite = (maintenant or time.time()) - float(jours) * 86400
    n = 0
    for rep in base.iterdir():
        if not rep.is_dir() or not ID.match(rep.name):
            continue
        try:
            debut = json.loads((rep / "passage.json").read_text()).get("debut", 0)
        except (OSError, ValueError):
            debut = rep.stat().st_mtime
        if debut < limite:
            shutil.rmtree(rep, ignore_errors=True)
            n += 1
    return n


class Cams:
    """La rubrique « Caméras » de la page. `body.alive["cameras"]` = le dossier des passages ; les empreintes
    apprises vont dans le dossier des visages (`personnes.visages`)."""

    def __init__(self, body, personnes):
        self.body, self.personnes = body, personnes
        dossier = (body.alive or {}).get("cameras")
        self.dossier = Path(dossier) if dossier else None
        self.visages = personnes.visages
        # 15/10 (page qui rame : 280 passages « animal » du robot, ~11 s de calcul refait à chaque ouverture et
        # après chaque tri) : une proposition est gardée tant que ce dont elle dépend ne change pas ; un seul calcul
        # de l'état à la fois (les autres appels attendent puis lisent le mémo).
        self._memo, self._verrou_etat = {}, threading.Lock()

    def _jours(self):
        try:
            return max(1, int((self.body.alive or {}).get("cams_garder") or GARDER_JOURS))
        except (TypeError, ValueError):
            return GARDER_JOURS

    def _seuils(self):
        alive = self.body.alive or {}
        try:
            import reachy_vue
            least, gap = reachy_vue.WHO_MIN, reachy_vue.WHO_GAP
        except ImportError:
            least, gap = 0.45, 0.10
        return float(alive.get("who_min") or least), float(alive.get("who_gap") or gap)

    def _sets(self):
        """{nom: [empreintes normées]} de toutes les séances (robot et caméras)."""
        sets = {}
        if self.visages is None or not Path(self.visages).is_dir():
            return sets
        for chemin in sorted(Path(self.visages).glob("*.json")):
            vecteurs = [_normer(s["empreinte"]) for s in reachy_apprendre.lire_seances(chemin, "vues")]
            if vecteurs:
                sets[chemin.stem] = vecteurs
        return sets

    def _passage(self, ident):
        if self.dossier is None:
            raise Refus(409, "aucun dossier de caméras configuré")
        if not ID.match(str(ident)):
            raise Refus(400, "passage inconnu")
        rep = self.dossier / ident
        try:
            return rep, json.loads((rep / "passage.json").read_text())
        except (OSError, ValueError):
            raise Refus(404, "passage introuvable (déjà trié ou effacé)")

    def _historique(self):
        try:
            return json.loads((self.dossier / "historique.json").read_text())
        except (OSError, ValueError, TypeError):
            return []

    def _versions(self, least, gap):
        """Ce dont dépendent les propositions : visages appris (+ seuils) pour les visages, étiquettes pour les objets."""
        def empreinte_fichiers(chemins):
            return tuple((c.name, c.stat().st_mtime_ns) for c in chemins if c.exists())
        visages = empreinte_fichiers(sorted(Path(self.visages).glob("*.json"))) if self.visages and Path(self.visages).is_dir() else ()
        return {"visage": (visages, least, gap), "objet": empreinte_fichiers([self.dossier / "etiquettes.json"])}

    def etat(self):
        with self._verrou_etat:
            return self._etat()

    def _etat(self):
        if self.dossier is None:
            return {"actif": False, "manque": "pas de dossier de caméras dans les réglages du corps (« cameras »)",
                    "a_trier": [], "recents": [], "appris": [], "jours": self._jours()}
        purger(self.dossier, self._jours())
        least, gap = self._seuils()
        versions = self._versions(least, gap)
        sets, etiquettes = None, None                     # lus seulement si une proposition manque au mémo
        a_trier, vus = [], set()
        for rep in sorted(self.dossier.iterdir(), reverse=True) if self.dossier.is_dir() else []:
            if not rep.is_dir() or not ID.match(rep.name):
                continue
            try:
                fiche = json.loads((rep / "passage.json").read_text())
            except (OSError, ValueError):
                continue
            vues, genre = fiche.get("vues") or [], fiche.get("genre", "visage")
            for k, indices in enumerate(groupes(fiche)):
                if str(k) in fiche.get("tries", {}):
                    continue
                choisies = [vues[i] for i in indices]
                cle, version = (fiche["id"], k, tuple(indices)), versions["visage" if genre == "visage" else "objet"]
                vus.add(cle)
                memo = self._memo.get(cle)
                if memo and memo[0] == version:
                    proposition = memo[1]
                else:
                    if genre == "visage":
                        sets = self._sets() if sets is None else sets
                        proposition = proposer([v["empreinte"] for v in choisies], sets, least, gap)
                    else:
                        etiquettes = lire_etiquettes(self.dossier) if etiquettes is None else etiquettes
                        proposition = proposer_objet(choisies, etiquettes.get(genre, {}))
                    self._memo[cle] = (version, proposition)
                a_trier.append({"passage": fiche["id"], "groupe": k, "camera": fiche["camera"], "genre": genre,
                                "camera_nom": CAMERAS.get(fiche["camera"], fiche["camera"]), "debut": fiche["debut"],
                                "vues": [v["f"] for v in choisies], "taille": max(v["taille"] for v in choisies),
                                "classe": next((v["classe"] for v in choisies if v.get("classe")), None),
                                "plaque": plaque_sure(choisies) if genre == "vehicule" else None,
                                "proposition": proposition})
        self._memo = {c: m for c, m in self._memo.items() if c in vus}     # passages triés ou effacés : oubliés
        etiquettes = lire_etiquettes(self.dossier) if etiquettes is None else etiquettes
        appris = []
        for nom in self.personnes.noms():
            seances = reachy_apprendre.lire_seances(Path(self.visages) / f"{nom}.json", "vues") if self.visages else []
            appris.append({"nom": nom, "robot": sum(1 for s in seances if not str(s.get("id", "")).startswith("cam-")),
                           "cameras": sum(int(s.get("vues") or 0) for s in seances if str(s.get("id", "")).startswith("cam-"))})
        objets = {g: [{"nom": n, "affiche": e.get("affiche") or n, "exemples": len(e.get("exemples") or []),
                       "cacher": bool(e.get("cacher")), "plaques": list(e.get("plaques") or [])}
                      for n, e in sorted(etiquettes.get(g, {}).items())]
                  for g in GENRES[1:]}
        return {"actif": True, "accord_requis": reachy_personnes.accord_requis(self.body), "a_trier": a_trier,
                "recents": self._historique()[:20], "appris": appris, "etiquettes": objets,
                "jours": self._jours(), "accords": sorted(n for n, a in self.personnes._accords().items()
                                                         if isinstance(a, dict) and a.get("visage"))}

    def image(self, ident, fichier):
        """Les octets d'une vue (jpeg). Seuls un identifiant et un nom de fichier valides sont acceptés."""
        if not FICHIER.match(str(fichier)):
            raise Refus(400, "vue inconnue")
        rep, _ = self._passage(ident)
        try:
            return (rep / fichier).read_bytes()
        except OSError:
            raise Refus(404, "vue effacée")

    def _clore(self, rep, fiche, groupe, indices, note):
        """Efface les images du groupe, le note trié ; le passage entier part quand tout est trié."""
        for i in indices:
            (rep / fiche["vues"][i]["f"]).unlink(missing_ok=True)
        fiche.setdefault("tries", {})[str(groupe)] = note
        restants = [k for k in range(len(groupes(fiche))) if str(k) not in fiche["tries"]]
        if restants:
            _ecrire(rep / "passage.json", json.dumps(fiche).encode())
        else:
            shutil.rmtree(rep, ignore_errors=True)
        histo = [{"le": reachy_apprendre._horodatage(), "camera": fiche["camera"],
                  "camera_nom": CAMERAS.get(fiche["camera"], fiche["camera"]), "debut": fiche["debut"],
                  "nom": note.get("nom"), "affiche": note.get("affiche"), "genre": fiche.get("genre", "visage"),
                  "ignore": bool(note.get("ignore")), "vues": note.get("garde", 0)}]
        _ecrire(self.dossier / "historique.json", json.dumps((histo + self._historique())[:HISTORIQUE_MAX]).encode())

    def _groupe(self, fiche, groupe):
        tous = groupes(fiche)
        if not isinstance(groupe, int) or isinstance(groupe, bool) or not 0 <= groupe < len(tous):
            raise Refus(400, "groupe inconnu")
        if str(groupe) in fiche.get("tries", {}):
            raise Refus(409, "groupe déjà trié")
        return tous[groupe]

    def _etiqueter(self, rep, fiche, groupe, nom, ecartees, affiche, cacher):
        """Un groupe d'animaux ou de véhicules : un EXEMPLE de plus pour l'étiquette (créée au besoin)."""
        genre = fiche["genre"]
        indices = self._groupe(fiche, groupe)
        ecartees = {str(f) for f in (ecartees or [])}
        gardees = [fiche["vues"][i] for i in indices if fiche["vues"][i]["f"] not in ecartees]
        if not gardees:
            raise Refus(400, "toutes les vues sont écartées : choisir « ignorer »")
        app = _normer([sum(float(v["empreinte"][j]) for v in gardees) for j in range(len(gardees[0]["empreinte"]))])
        avec = [v for v in gardees if v.get("couleur")]
        coul = (_normer([sum(float(v["couleur"][j]) for v in avec) for j in range(len(avec[0]["couleur"]))])
                if avec else [])
        etiquettes = lire_etiquettes(self.dossier)
        e = etiquettes[genre].setdefault(nom, {"affiche": nom.replace("-", " ").capitalize(), "cacher": False, "exemples": []})
        if affiche:
            e["affiche"] = re.sub(r"\s+", " ", str(affiche)).strip()[:40] or e["affiche"]
        if cacher is not None:
            e["cacher"] = bool(cacher)
        plaque = plaque_sure(gardees) if genre == "vehicule" else None
        if plaque:                                       # 12/10 : la plaque reconnaîtra cette voiture à coup sûr
            e["plaques"] = [p for p in e.get("plaques") or [] if p != plaque][-(PLAQUES_MAX - 1):] + [plaque]
        e["exemples"] = (e.get("exemples") or [])[-(EXEMPLES_MAX - 1):] + [
            {"empreinte": [round(x, 6) for x in app], "couleur": [round(x, 6) for x in coul], "camera": fiche["camera"],
             "le": reachy_apprendre._horodatage(), "vues": len(gardees)}]
        _ecrire(self.dossier / "etiquettes.json", json.dumps(etiquettes).encode())
        self._clore(rep, fiche, groupe, indices, {"nom": nom, "affiche": e["affiche"], "genre": genre,
                                                   "le": reachy_apprendre._horodatage(), "garde": len(gardees)})
        note = getattr(self.body, "on_note", None)
        if note:
            note(f"caméras : {e['affiche']} ({genre}, {fiche['camera']}) : un exemple de plus")
        return self.etat()

    def etiquette(self, genre, nom, cacher=None, oublier=False, retirer_plaque=None):
        """Changer une étiquette d'animal ou de véhicule : « toujours ignorer » (voiture garée), l'oublier, ou
        lui retirer une plaque (voiture vendue, plaque mal lue)."""
        if genre not in GENRES[1:]:
            raise Refus(400, "animal ou véhicule")
        nom = nom_sur(nom)
        etiquettes = lire_etiquettes(self.dossier)
        if nom not in etiquettes[genre]:
            raise Refus(404, "étiquette inconnue")
        if oublier:
            del etiquettes[genre][nom]
        elif retirer_plaque is not None:
            plaques = etiquettes[genre][nom].get("plaques") or []
            if retirer_plaque not in plaques:
                raise Refus(404, "plaque inconnue")
            etiquettes[genre][nom]["plaques"] = [p for p in plaques if p != retirer_plaque]
        elif cacher is not None:
            etiquettes[genre][nom]["cacher"] = bool(cacher)
        _ecrire(self.dossier / "etiquettes.json", json.dumps(etiquettes).encode())
        return self.etat()

    def trier(self, ident, groupe, nom, ecartees=(), accord=None, par=None, affiche=None, cacher=None):
        """« C'est <nom> » : les vues gardées (moins les écartées) deviennent la séance « caméra » de la personne
        pour cette caméra (fusionnée avec la précédente), puis les images du groupe sont effacées."""
        nom = nom_sur(nom)
        rep, fiche = self._passage(ident)
        if fiche.get("genre", "visage") != "visage":
            return self._etiqueter(rep, fiche, groupe, nom, ecartees, affiche, cacher)
        if self.visages is None or self.personnes.accords_fichier is None:
            raise Refus(409, "aucun dossier d'empreintes configuré")
        indices = self._groupe(fiche, groupe)
        ecartees = {str(f) for f in (ecartees or [])}
        gardees = [i for i in indices if fiche["vues"][i]["f"] not in ecartees]
        if not gardees:
            raise Refus(400, "toutes les vues sont écartées : choisir « inconnu »")
        if not (self.personnes._accords().get(nom) or {}).get("visage") and reachy_personnes.accord_requis(self.body):
            if accord is not True:
                raise Refus(400, f"l'accord de {nom.capitalize()} est obligatoire avant d'apprendre son visage")
            self.personnes.noter_accord(nom, "visage", par)
        somme = [0.0] * len(fiche["vues"][gardees[0]]["empreinte"])
        for i in gardees:
            somme = [a + b for a, b in zip(somme, _normer(fiche["vues"][i]["empreinte"]))]
        chemin = Path(self.visages) / f"{nom}.json"
        seances = reachy_apprendre.lire_seances(chemin, "vues")
        cle = "cam-" + fiche["camera"]
        avant = next((s for s in seances if s.get("id") == cle), None)
        n_avant = int(avant.get("vues") or 0) if avant else 0
        if avant:                                  # fusion pondérée : la séance caméra grandit, elle ne se multiplie pas
            somme = [a + n_avant * float(b) for a, b in zip(somme, _normer(avant["empreinte"]))]
        seance = {"id": cle, "le": reachy_apprendre._horodatage(), "moment": "caméra " + fiche["camera"],
                  "vues": n_avant + len(gardees), "empreinte": [round(x, 6) for x in _normer(somme)]}
        seances = [s for s in seances if s.get("id") != cle] + [seance]
        reachy_apprendre.ecrire_seances(chemin, nom, "sface_2021dec", "vues", seances)
        self._clore(rep, fiche, groupe, indices, {"nom": nom, "le": reachy_apprendre._horodatage(), "garde": len(gardees)})
        note = getattr(self.body, "on_note", None)
        if note:
            note(f"caméras : {len(gardees)} vue(s) apprise(s) pour {nom} ({fiche['camera']})")
        return self.etat()

    def ignorer(self, ident, groupe):
        """« Inconnu, ne pas apprendre » : les images du groupe sont effacées, rien n'est appris."""
        rep, fiche = self._passage(ident)
        indices = self._groupe(fiche, groupe)
        self._clore(rep, fiche, groupe, indices, {"ignore": True, "le": reachy_apprendre._horodatage(), "garde": 0})
        return self.etat()

    def route(self, methode, chemin, demande):
        try:
            if methode == "GET":
                if chemin == PREFIXE:
                    return 200, self.etat()
                raise Refus(404, "inconnu")
            if not isinstance(demande, dict):
                raise Refus(400, "un objet JSON est attendu")
            action = chemin[len(PREFIXE) + 1:]
            if action == "trier":
                return 200, self.trier(str(demande.get("passage", "")), demande.get("groupe"), demande.get("nom"),
                                       demande.get("ecartees") or [], demande.get("accord"), demande.get("par"),
                                       demande.get("affiche"), demande.get("cacher"))
            if action == "etiquette":
                return 200, self.etiquette(str(demande.get("genre", "")), demande.get("nom"),
                                           demande.get("cacher"), demande.get("oublier") is True,
                                           demande.get("retirer_plaque"))
            if action == "ignorer":
                return 200, self.ignorer(str(demande.get("passage", "")), demande.get("groupe"))
            raise Refus(404, "inconnu")
        except Refus as refus:
            return refus.status, {"erreur": refus.message}
        except OSError as trouble:
            return 500, {"erreur": f"écriture impossible : {str(trouble)[:120]}"}
