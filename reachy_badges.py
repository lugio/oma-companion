#!/usr/bin/env python3
"""La rubrique « Badges » de la page du robot : les badges NFC qui ouvrent une porte (16/10/2026).

Rien n'est enregistré chez le fabricant de la sonnette : une sonnette à lecteur NFC (UniFi G4 Doorbell Pro par
exemple) remonte dans Home Assistant l'identifiant de TOUT badge lu (une entité `event.…`, attribut `nfc_id`).
La liste des badges autorisés vit dans Home Assistant, une liste Local To-do (`todo.…`) :
un élément = un badge, son intitulé = le prénom, sa description = l'identifiant (majuscules). C'est une automatisation
de HA qui décide d'ouvrir : la porte s'ouvre même robot éteint. Les deux entités se déclarent dans le fichier de
réglages du corps (clé « badges »).
Un élément coché dans HA = badge suspendu (l'automatisation ne lit que les éléments à faire).

- La page ne reçoit JAMAIS un identifiant entier : seulement ses deux derniers caractères (« ••••••3F »).
- Apprendre : `apprendre(nom)` retient l'événement du lecteur du moment ; le badge passé ensuite (2 min au plus)
  est ajouté sous ce prénom. Un badge déjà dans la liste n'est pas ajouté deux fois.
- Le module ne connaît NI le jeton NI l'adresse de HA : le corps pose `body.ha_badges = client_http(url, jeton)`,
  une fonction `appel(methode, chemin, corps)` limitée à une liste FERMÉE de chemins.
Bibliothèque standard seulement.
"""
import json
import re
import threading
import time
import urllib.request
from http import HTTPStatus

PREFIXE = "/api/badges"
# Les deux entités viennent du fichier de réglages du corps (`vivant.json`, clé « badges » :
# {"liste": "todo.…", "lecteur": "event.…"}) — propres à chaque maison (18/10). Vides = rubrique non configurée.
LISTE = ""
LECTEUR = ""
APPRENDRE_S = 120                  # secondes pour passer le badge à apprendre
NOM_MAX = 30
DELAI = 5.0
ID_OK = re.compile(r"^[0-9A-F]{4,32}$")
CHEMINS = set()                    # la liste fermée des appels à HA (posée par `configurer`)
ENTITE = re.compile(r"^(todo|event)\.[a-z0-9_]+$")


def configurer(conf):
    """Pose la liste et le lecteur depuis `alive["badges"]`. Mal formés = rubrique non configurée."""
    global LISTE, LECTEUR, CHEMINS
    conf = conf if isinstance(conf, dict) else {}
    liste, lecteur = str(conf.get("liste") or ""), str(conf.get("lecteur") or "")
    if not (liste.startswith("todo.") and lecteur.startswith("event.") and ENTITE.fullmatch(liste)
            and ENTITE.fullmatch(lecteur)):
        liste = lecteur = ""
    LISTE, LECTEUR = liste, lecteur
    CHEMINS = {("GET", f"/api/states/{LECTEUR}"), ("POST", "/api/services/todo/get_items?return_response"),
               ("POST", "/api/services/todo/add_item"), ("POST", "/api/services/todo/remove_item")} if LISTE else set()


def configure():
    return bool(LISTE and LECTEUR)


class Refus(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def client_http(url, jeton, delai=DELAI):
    """L'accès à HA du corps pour cette rubrique. Le jeton reste dans la fonction, jamais servi."""
    url = str(url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")) or not jeton:
        raise ValueError("badges : une adresse http(s) et un jeton sont nécessaires")
    entetes = {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"}

    def appel(methode, chemin, corps=None):
        if (methode, chemin) not in CHEMINS:
            raise ValueError("badges : appel hors de la liste")
        donnees = json.dumps(corps).encode() if corps is not None else None
        demande = urllib.request.Request(url + chemin, donnees, entetes, method=methode)
        with urllib.request.urlopen(demande, timeout=delai) as reponse:
            return json.loads(reponse.read(262144) or b"null")
    return appel


def normer_id(valeur):
    v = re.sub(r"[\s:-]", "", str(valeur or "")).upper()
    return v if ID_OK.match(v) else ""


def aleatoire(ident):
    """Identifiant ALÉATOIRE (ISO 14443-3 : 4 octets commençant par 08) : téléphone, carte bancaire… change à chaque
    lecture (vu le 16/10 : trois passages du même objet, trois identifiants « 08… »). Inutilisable comme badge."""
    return len(ident) == 8 and ident.startswith("08")


def masquer(ident):
    return "••••••" + ident[-2:] if ident else "?"


class Badges:
    """`source()` rend l'appel à HA du corps (ou None). Un seul apprentissage à la fois."""

    def __init__(self, source, horloge=time.time):
        self.source = source
        self.horloge = horloge
        self.verrou = threading.Lock()
        self.session = None            # {"nom", "avant", "debut", "statut", "message"}

    def _ha(self):
        appel = self.source()
        if appel is None:
            raise Refus(HTTPStatus.SERVICE_UNAVAILABLE, "pas d'accès à Home Assistant dans le corps")
        return appel

    def _items(self, appel):
        r = appel("POST", "/api/services/todo/get_items?return_response",
                  {"entity_id": LISTE, "status": ["needs_action", "completed"]})
        items = ((r or {}).get("service_response") or {}).get(LISTE, {}).get("items", [])
        return [i for i in items if isinstance(i, dict)]

    def _lecteur(self, appel):
        etat = appel("GET", f"/api/states/{LECTEUR}") or {}
        attr = etat.get("attributes") or {}
        return etat.get("state"), attr.get("event_id"), normer_id(attr.get("nfc_id"))

    def _avancer(self, appel, items):
        """Pendant un apprentissage : regarde si un nouveau badge est passé. Sous verrou."""
        s = self.session
        if not s or s["statut"] != "attente":
            return
        if self.horloge() - s["debut"] > APPRENDRE_S:
            s.update(statut="expire", message="Aucun badge passé en 2 minutes.")
            return
        quand, event_id, ident = self._lecteur(appel)
        if not event_id or event_id == s["avant"] or quand in (None, "unknown", "unavailable"):
            return
        if not ident:
            s.update(statut="erreur", message="Le badge a été lu, mais son identifiant n'est pas arrivé dans HA.")
            return
        if aleatoire(ident):
            s.update(statut="erreur", message="Ce badge change d'identifiant à chaque passage (téléphone, carte bancaire, "
                     "badge sécurisé) : il ne peut pas servir. Prendre un badge ou un porte-clés NFC simple.")
            return
        deja = next((i for i in items if normer_id(i.get("description")) == ident), None)
        if deja:
            s.update(statut="deja", message=f"Ce badge est déjà dans la liste, au nom de {deja.get('summary', '?')}.")
            return
        appel("POST", "/api/services/todo/add_item", {"entity_id": LISTE, "item": s["nom"], "description": ident})
        s.update(statut="ajoute", message=f"Badge ajouté pour {s['nom']} ({masquer(ident)}).")

    def etat(self):
        with self.verrou:
            try:
                appel = self._ha()
                items = self._items(appel)
                if self.session and self.session["statut"] == "attente":
                    self._avancer(appel, items)
                    if self.session["statut"] == "ajoute":
                        items = self._items(appel)
                quand, _, ident = self._lecteur(appel)
                ha, erreur = True, ""
            except Refus as refus:
                items, quand, ident, ha, erreur = [], None, "", False, refus.message
            except Exception:          # HA éteint, jeton refusé, délai dépassé : la page vit sans lui
                items, quand, ident, ha, erreur = [], None, "", False, "Home Assistant ne répond pas"
            connus = {normer_id(i.get("description")): i.get("summary", "") for i in items
                      if i.get("status") == "needs_action"}
            session = None
            if self.session:
                s = self.session
                session = {"nom": s["nom"], "statut": s["statut"], "message": s["message"],
                           "reste": max(0, int(APPRENDRE_S - (self.horloge() - s["debut"])))}
        dernier = None
        if quand and quand not in ("unknown", "unavailable"):
            dernier = {"quand": quand, "nom": connus.get(ident, "") if ident else "", "badge": masquer(ident)}
        return {
            "ha": {"disponible": ha, "erreur": erreur},
            "liste": LISTE,
            "badges": [{"uid": i.get("uid", ""), "nom": i.get("summary", ""), "badge": masquer(normer_id(i.get("description"))),
                        "actif": i.get("status") == "needs_action", "valide": bool(normer_id(i.get("description")))}
                       for i in items],
            "apprentissage": session,
            "dernier": dernier,
        }

    def apprendre(self, nom):
        nom = " ".join(str(nom or "").split())
        if not 0 < len(nom) <= NOM_MAX:
            raise Refus(HTTPStatus.BAD_REQUEST, f"un prénom de 1 à {NOM_MAX} caractères")
        with self.verrou:
            appel = self._ha()
            try:
                _, avant, _ = self._lecteur(appel)
            except Exception:
                raise Refus(HTTPStatus.SERVICE_UNAVAILABLE, "Home Assistant ne répond pas")
            self.session = {"nom": nom, "avant": avant, "debut": self.horloge(), "statut": "attente",
                            "message": f"Passe le badge de {nom} devant le lecteur de la sonnette."}
        return self.etat()

    def annuler(self):
        with self.verrou:
            self.session = None
        return self.etat()

    def retirer(self, uid):
        uid = str(uid or "")
        if not uid or len(uid) > 100:
            raise Refus(HTTPStatus.BAD_REQUEST, "badge inconnu")
        with self.verrou:
            appel = self._ha()
            try:
                if uid not in {i.get("uid") for i in self._items(appel)}:
                    raise Refus(HTTPStatus.NOT_FOUND, "ce badge n'est plus dans la liste")
                appel("POST", "/api/services/todo/remove_item", {"entity_id": LISTE, "item": uid})
            except Refus:
                raise
            except Exception:
                raise Refus(HTTPStatus.SERVICE_UNAVAILABLE, "Home Assistant ne répond pas")
        return self.etat()

    def route(self, methode, chemin, demande=None):
        """→ (statut HTTP, réponse JSON)."""
        if not configure():
            # Rien dans le fichier de réglages du corps : la rubrique le dit, sans jamais toucher à HA.
            return HTTPStatus.NOT_FOUND, {"erreur": "badges : non configuré dans le fichier de réglages du corps",
                                          "configure": False}
        try:
            if methode == "GET" and chemin == PREFIXE:
                return HTTPStatus.OK, self.etat()
            if methode == "POST":
                demande = demande if isinstance(demande, dict) else {}
                if chemin == PREFIXE + "/apprendre":
                    return HTTPStatus.OK, self.apprendre(demande.get("nom"))
                if chemin == PREFIXE + "/annuler":
                    return HTTPStatus.OK, self.annuler()
                if chemin == PREFIXE + "/retirer":
                    return HTTPStatus.OK, self.retirer(demande.get("uid"))
            return HTTPStatus.NOT_FOUND, {"erreur": "inconnu"}
        except Refus as refus:
            return refus.status, {"erreur": refus.message}
