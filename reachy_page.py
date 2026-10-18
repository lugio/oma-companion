#!/usr/bin/env python3
"""La page de réglages du robot, servie par son corps (11/10/2026).

Spec `docs/superpowers/specs/2026-10-11-reachy-page-reglages.md`, option A retenue : un serveur HTTP
de la BIBLIOTHÈQUE STANDARD (`http.server.ThreadingHTTPServer`) dans un fil du corps (`reachy.Body`),
seulement si `alive["page"]` = {"hote": "<adresse du réseau local>", "port": 8010[, "ha": "<adresse de HA>"]}.

- Écoute sur l'adresse donnée, JAMAIS sur toutes les interfaces (une machine peut avoir plusieurs réseaux).
- En-tête `Host` vérifié à chaque requête (une page d'un autre site ne peut pas se faire passer pour elle).
- Routes FIXES, en lecture : la page, `GET /api/etat` (l'instantané du corps), `GET /api/reglages` (schéma
  et valeurs), `GET /api/image` (la dernière image déjà reçue par la vue : aucun appel de plus à la caméra).
- Aucun secret servi : ni le jeton de Home Assistant, ni l'adresse de la caméra, ni les dossiers.
- Écriture (lot 3) : `POST /api/reglages` {"valeurs": {clé: valeur ou null}}, SEULEMENT les clés du schéma,
  validées par lui (`reachy_reglages.ecrire` : sauvegarde, écriture atomique), puis appliquées à chaud.
  Contre une requête forgée par un autre site ouvert dans le navigateur (CSRF) : même origine exigée
  (`Origin`, et `Sec-Fetch-Site` quand il est là), `Content-Type: application/json`, et l'en-tête
  `X-Reachy-Jeton` portant le jeton donné à cette page à son ouverture. Sans fichier de réglages : lecture seule.

La page elle-même : `reachy_page.html`, à côté de ce fichier (HTML, CSS et JS, aucune dépendance externe).
"""
import json
import secrets
import urllib.parse
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import reachy_appairage
import reachy_apprendre
import reachy_badges
import reachy_eveil
import reachy_cams
import reachy_personnes
import reachy_maison
import reachy_assistants
import reachy_reglages
import reachy_son

HTML = Path(__file__).resolve().parent / "reachy_page.html"
TOUTES = ("", "0.0.0.0", "::", "*")     # « toutes les interfaces » : refusé, la page reste sur le réseau local
JETONS_MAX = 64                         # pages ouvertes gardées en mémoire
JETON_VIE = 12 * 3600                   # secondes
TAILLE_MAX = 16 * 1024                  # octets d'une demande d'écriture
ASSISTANTS = "/api/assistants"          # lot 4 : les assistants de calibrage (`reachy_assistants.py`)


class Page:
    """Le serveur de la page : un fil, une adresse, des routes fixes. `close()` l'arrête."""

    def __init__(self, body, config):
        if not isinstance(config, dict):
            raise ValueError("réglage page : {\"hote\": …, \"port\": …} attendu")
        self.host = str(config.get("hote") or "").strip()
        if self.host in TOUTES:
            raise ValueError("réglage page : une adresse précise du réseau local, jamais toutes les interfaces")
        self.port = int(config.get("port", 8010))
        ha = str(config.get("ha") or "").strip().rstrip("/")
        self.ha = ha if ha.startswith(("http://", "https://")) else ""
        self.body = body
        self.jetons = {}                  # jeton → expiration (lot 3) ; un jeton par page ouverte
        # Maison (lot 6, lecture seule) : le corps pose `body.lecteur_ha` (il a le jeton) ; sans lui, la page marche.
        # Ce qui est propre à la maison (automatisations, badges, satellite, entités des personnes) vient du
        # fichier de réglages du corps, jamais du code (18/10) : sans clé, la rubrique reste vide.
        # Toujours reposée, fichier de réglages ou non : une clé retirée vide la rubrique (une page
        # recréée ne garde pas l'ancienne maison). Une rubrique mal décrite reste vide sans tuer la page.
        alive = getattr(body, "alive", None)
        alive = alive if isinstance(alive, dict) else {}
        for module, cle in ((reachy_maison, "maison"), (reachy_badges, "badges"), (reachy_eveil, "eveil"),
                            (reachy_personnes, "personnes_ha"), (reachy_cams, "cameras_noms")):
            try:
                module.configurer(alive.get(cle))
            except Exception:  # noqa: BLE001 - une rubrique mal décrite ne tue pas la page
                module.configurer(None)
                body.on_note(f"page : rubrique « {cle} » mal décrite dans le fichier du corps, ignorée")
        # Appareils appairés (18/10) : leurs empreintes à côté du fichier de réglages du corps (sans fichier :
        # en mémoire, le temps de la session). Le code est dit par le robot quand il a une voix.
        fichier = getattr(body, "fichier", None)
        self.appairage = reachy_appairage.Appairage(
            Path(fichier).with_name("appareils.json") if fichier else None,
            trouver_annonce=lambda: getattr(getattr(body, "voix", None), "annoncer", None),   # voix branchée après
            noter=getattr(body, "on_note", lambda texte: None))
        self.maison = reachy_maison.Maison(lambda: getattr(body, "lecteur_ha", None))
        # Badges NFC (16/10) : la liste vit dans HA ; le corps pose `body.ha_badges` (il a le jeton).
        self.badges = reachy_badges.Badges(lambda: getattr(body, "ha_badges", None))
        # Mots d'éveil du robot (16/10, rubrique Parler) : le corps pose `body.ha_eveil` (il a le jeton).
        self.eveil = reachy_eveil.Eveil(lambda: getattr(body, "ha_eveil", None))
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.server.daemon_threads = True
        self.server.page = self
        self.port = self.server.server_address[1]          # port 0 (essais) : celui choisi par le système
        self.origin = f"http://{self.host}:{self.port}" if self.port != 80 else f"http://{self.host}"
        self.hosts = {f"{self.host}:{self.port}"} | ({self.host} if self.port == 80 else set())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        body.on_note(f"page de réglages : {self.origin}")

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def nouveau_jeton(self):
        jeton = secrets.token_urlsafe(24)
        with self.lock:
            now = time.monotonic()
            self.jetons = {j: fin for j, fin in self.jetons.items() if fin > now}
            while len(self.jetons) >= JETONS_MAX:
                self.jetons.pop(min(self.jetons, key=self.jetons.get))
            self.jetons[jeton] = now + JETON_VIE
        return jeton

    def jeton_valide(self, jeton):
        with self.lock:
            fin = self.jetons.get(jeton or "")
            return fin is not None and fin > time.monotonic()

    def valeurs(self, contenu):
        return {r["cle"]: reachy_reglages.lu(contenu, r["cle"]) for r in reachy_reglages.REGLAGES}

    def ecrire(self, changements):
        """Écrit, puis fait appliquer par le corps sans attendre la surveillance du fichier."""
        nouveau = reachy_reglages.ecrire(self.body.fichier, changements)
        self.body.inbox.put(("reglages", nouveau))
        return self.valeurs(nouveau)

    def contenu(self):
        """Le contenu des réglages : le fichier quand il existe (la vérité), sinon ce que le corps a reçu."""
        if self.body.fichier is not None:
            try:
                return reachy_reglages.lire(self.body.fichier)
            except ValueError:
                pass
        return dict(self.body.alive)

    def reglages(self):
        contenu = self.contenu()
        valeurs = self.valeurs(contenu)
        # Un réglage qui demande une caméra ou un dossier de visages absent est montré, mais grisé.
        manque = {r["cle"]: r["exige"] for r in reachy_reglages.REGLAGES
                  if r.get("exige") and not self.body.alive.get(r["exige"])}
        return {"schema": reachy_reglages.schema_public(), "valeurs": valeurs, "manque": manque,
                "ecriture": self.body.fichier is not None, "ha": self.ha, "rubriques": list(reachy_reglages.RUBRIQUES)}


# --- Maison (lot 6) : routes sous /api/maison, en lecture seule ---------------------------------------------
def _routes_maison(handler, path):
    """`GET /api/maison/etat` : l'état des automatisations du robot dans Home Assistant (liste fermée, en cache).
    → True si la route est traitée. Aucune écriture, aucun secret : le lecteur de HA est celui du corps."""
    if path != "/api/maison/etat":
        return False
    handler.send(HTTPStatus.OK, handler.page.maison.instantane())
    return True


class Handler(BaseHTTPRequestHandler):
    qui = None                         # l'appareil appairé de la demande en cours
    server_version = "reachy-page"
    sys_version = ""

    def log_message(self, *args):           # pas de journal par requête : le corps a le sien
        pass

    @property
    def page(self):
        return self.server.page

    def send(self, status, data, kind="application/json; charset=utf-8", extra=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        ancetres = "'self'" + (f" {self.page.ha}" if self.page.ha else "")   # intégrable dans HA, rien d'autre
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                         f"script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors {ancetres}; "
                         "base-uri 'none'; form-action 'none'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def refuse(self, status, message):
        self.send(status, {"erreur": message})

    def host_ok(self):
        return (self.headers.get("Host") or "") in self.page.hosts

    OUVERTES = ("/api/appairage/demander", "/api/appairage/valider", "/api/appairage/etat")

    def appareil(self):
        """L'appareil appairé qui demande (en-tête X-Reachy-Appareil, ou paramètre `appareil` pour une image),
        ou None."""
        jeton = self.headers.get("X-Reachy-Appareil") or ""
        if not jeton and "?" in self.path:
            jeton = (urllib.parse.parse_qs(self.path.split("?", 1)[1]).get("appareil") or [""])[0]
        return self.page.appairage.reconnaitre(jeton)

    def appareil_requis(self, path):
        """Vrai si la demande peut passer ; sinon le refus 401 est envoyé (la page montre alors l'appairage)."""
        if not path.startswith("/api/") or path in self.OUVERTES:
            return True
        self.qui = self.appareil()
        if self.qui is None:
            self.send(HTTPStatus.UNAUTHORIZED, {"erreur": "appareil non appairé", "appairage": True})
            return False
        return True

    def do_GET(self):
        if not self.host_ok():
            return self.refuse(HTTPStatus.MISDIRECTED_REQUEST, "adresse inattendue")
        path = self.path.split("?", 1)[0]
        if not self.appareil_requis(path):
            return
        if path == "/api/appairage/etat":
            return self.send(HTTPStatus.OK, {"appaire": self.appareil() is not None})
        if path == "/api/appareils":
            return self.send(HTTPStatus.OK, {"appareils": self.page.appairage.liste(self.qui)})
        if path == "/":
            try:
                html = HTML.read_text()
            except OSError:
                return self.refuse(HTTPStatus.INTERNAL_SERVER_ERROR, "page introuvable (reachy_page.html)")
            html = html.replace("__JETON__", self.page.nouveau_jeton())
            return self.send(HTTPStatus.OK, html.encode(), "text/html; charset=utf-8")
        if _routes_assistants(self, "GET", path):                                # lot 4
            return
        if path == "/api/etat":
            return self.send(HTTPStatus.OK, self.page.body.etat())
        if path == "/api/reglages":
            return self.send(HTTPStatus.OK, self.page.reglages())
        if _routes_maison(self, path):
            return
        if path == "/api/image":
            eyes = self.page.body.eyes
            jpeg = getattr(eyes, "jpeg", None) if eyes is not None else None
            if not jpeg:
                return self.refuse(HTTPStatus.NOT_FOUND, "pas d'image")
            return self.send(HTTPStatus.OK, bytes(jpeg), "image/jpeg")
        if path == reachy_badges.PREFIXE:                   # 16/10 : Badges NFC
            return self.send(*self.page.badges.route("GET", path))
        if path == reachy_eveil.PREFIXE:                    # 16/10 : Parler, mots d'éveil
            return self.send(*self.page.eveil.route("GET", path))
        if path == reachy_son.PREFIXE:                      # 11/10 : Parler (le volume de sa voix)
            return self.send(*reachy_son.route(getattr(self.page.body, "voix", None), "GET", path))
        if path.startswith(reachy_personnes.PREFIXE):       # lot 5 : Personnes
            return _routes_personnes(self, "GET", path)
        if path == reachy_apprendre.PREFIXE or path.startswith(reachy_apprendre.PREFIXE + "/"):   # Apprentissage
            return _routes_apprendre(self, "GET", path)
        if path == reachy_cams.PREFIXE or path.startswith(reachy_cams.PREFIXE + "/"):   # Caméras de la maison
            return _routes_cams(self, "GET", self.path)
        return self.refuse(HTTPStatus.NOT_FOUND, "inconnu")

    do_HEAD = do_GET

    def ecriture_permise(self):
        """Les trois gardes de TOUTE écriture : même origine, JSON, jeton de cette page. Sinon la réponse de refus
        est déjà envoyée et on rend faux."""
        if self.headers.get("Origin") != self.page.origin or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            self.refuse(HTTPStatus.FORBIDDEN, "demande venue d'une autre page")
        elif not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self.refuse(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON attendu")
        elif not self.page.jeton_valide(self.headers.get("X-Reachy-Jeton")):
            self.refuse(HTTPStatus.FORBIDDEN, "page périmée : la recharger")
        else:
            return True
        return False

    def do_POST(self):
        page = self.page
        if not self.host_ok():
            return self.refuse(HTTPStatus.MISDIRECTED_REQUEST, "adresse inattendue")
        if not self.appareil_requis(self.path.split("?", 1)[0]):
            return
        if self.path.startswith("/api/appairage/") or self.path.startswith("/api/appareils/"):
            demande, refuse = _demande_permise(self) or (None, True)
            if refuse:
                return
            try:
                if self.path == "/api/appairage/demander":
                    return self.send(HTTPStatus.OK, page.appairage.demander())
                if self.path == "/api/appairage/valider":
                    return self.send(HTTPStatus.OK, page.appairage.valider(demande.get("code"), demande.get("nom"),
                                                                           self.client_address[0]))
                if self.path == "/api/appareils/revoquer":
                    return self.send(HTTPStatus.OK, page.appairage.revoquer(demande.get("id")))
            except reachy_appairage.Refus as refus:
                return self.refuse(refus.status, refus.message)
            return self.refuse(HTTPStatus.NOT_FOUND, "inconnu")
        if self.path.startswith(reachy_personnes.PREFIXE + "/"):    # lot 5 : Personnes
            return _routes_personnes(self, "POST", self.path)
        if self.path.startswith(reachy_apprendre.PREFIXE + "/"):    # Apprentissage (11/10)
            return _routes_apprendre(self, "POST", self.path)
        if self.path.startswith(reachy_cams.PREFIXE + "/"):         # Caméras de la maison (11/10)
            return _routes_cams(self, "POST", self.path)
        if self.path.startswith(reachy_badges.PREFIXE + "/"):       # Badges NFC (16/10)
            demande, refuse = _demande_permise(self) or (None, True)
            if refuse:
                return
            return self.send(*page.badges.route("POST", self.path.split("?", 1)[0], demande))
        if self.path.startswith(reachy_eveil.PREFIXE + "/"):        # Parler, mots d'éveil (16/10)
            demande, refuse = _demande_permise(self) or (None, True)
            if refuse:
                return
            return self.send(*page.eveil.route("POST", self.path.split("?", 1)[0], demande))
        if self.path.startswith(reachy_son.PREFIXE + "/"):          # Parler (11/10)
            demande, refuse = _demande_permise(self) or (None, True)
            if refuse:
                return
            return self.send(*reachy_son.route(getattr(page.body, "voix", None), "POST", self.path, demande))
        if _routes_assistants(self, "POST", self.path):                         # lot 4
            return
        if self.path != "/api/reglages":
            return self.refuse(HTTPStatus.NOT_FOUND, "inconnu")
        if not self.ecriture_permise():
            return
        if page.body.fichier is None:
            return self.refuse(HTTPStatus.CONFLICT, "aucun fichier de réglages : lecture seule")
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = -1
        if not 0 < size <= TAILLE_MAX:
            return self.refuse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "demande trop grande")
        try:
            demande = json.loads(self.rfile.read(size))
            changements = demande.get("valeurs") if isinstance(demande, dict) else None
            if not isinstance(changements, dict) or not changements:
                raise ValueError("rien à changer")
            valeurs = page.ecrire(changements)
        except ValueError as trouble:            # JSON illisible, clé inconnue, valeur hors bornes : rien n'est écrit
            return self.refuse(HTTPStatus.BAD_REQUEST, str(trouble)[:200])
        except OSError as trouble:
            return self.refuse(HTTPStatus.INTERNAL_SERVER_ERROR, f"écriture impossible : {str(trouble)[:120]}")
        return self.send(HTTPStatus.OK, {"valeurs": valeurs})


# --- PERSONNES : début (lot 5, 11/10/2026) -----------------------------------------------------------------
# Les routes de la rubrique Personnes. Toute la logique est dans `reachy_personnes.py` ; ici, seulement les gardes
# (mêmes que l'écriture des réglages : même origine, JSON, jeton de la page) et la lecture de la demande.
# Aucune empreinte, image ou chemin ne sort : la page ne reçoit que des noms, des dates et des compteurs.
def _demande_permise(h):
    """Les gardes d'une écriture de Personnes ou d'Apprentissage (même origine, JSON, jeton de la page), puis la
    demande lue. → (demande, False), ou None quand le refus est déjà envoyé."""
    page = h.page
    if h.headers.get("Origin") != page.origin or h.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
        return h.refuse(HTTPStatus.FORBIDDEN, "demande venue d'une autre page")
    if not (h.headers.get("Content-Type") or "").startswith("application/json"):
        return h.refuse(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON attendu")
    if not page.jeton_valide(h.headers.get("X-Reachy-Jeton")):
        return h.refuse(HTTPStatus.FORBIDDEN, "page périmée : la recharger")
    try:
        taille = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        taille = -1
    if not 0 < taille <= TAILLE_MAX:
        return h.refuse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "demande trop grande")
    try:
        return json.loads(h.rfile.read(taille)), False
    except ValueError:
        return h.refuse(HTTPStatus.BAD_REQUEST, "JSON illisible")


def _personnes(page):
    with page.lock:
        if getattr(page, "personnes", None) is None:
            page.personnes = reachy_personnes.Personnes(page.body)
        return page.personnes


def _routes_personnes(h, methode, chemin):
    demande = None
    if methode == "POST":
        demande, refuse = _demande_permise(h) or (None, True)
        if refuse:
            return
    statut, reponse = _personnes(h.page).route(methode, chemin.split("?", 1)[0], demande)
    return h.send(statut, reponse)


# Apprentissage (11/10/2026) : visage et voix, logique dans `reachy_apprendre.py`. Mêmes gardes que Personnes, et
# la même fiche (l'accord daté). Seuls des noms, des dates, des compteurs et des scores sortent.
def _routes_apprendre(h, methode, chemin):
    demande = None
    if methode == "POST":
        demande, refuse = _demande_permise(h) or (None, True)
        if refuse:
            return
    page = h.page
    personnes = _personnes(page)
    with page.lock:
        if getattr(page, "apprendre", None) is None:
            page.apprendre = reachy_apprendre.Apprendre(page.body, personnes)
    statut, reponse = page.apprendre.route(methode, chemin.split("?", 1)[0], demande)
    return h.send(statut, reponse)
# Caméras de la maison (11/10/2026) : trier les visages vus par les caméras, logique dans `reachy_cams.py`.
# Écritures : mêmes gardes que Personnes. Une VUE (gros plan d'un visage) n'est servie qu'avec le jeton de cette
# page dans l'adresse (`?p=<passage>&f=<vue>&jeton=…`) : une balise <img> ne peut pas porter d'en-tête.
def _routes_cams(h, methode, chemin):
    from urllib.parse import parse_qs, urlsplit
    page = h.page
    personnes = _personnes(page)                  # prend le verrou de la page : AVANT le nôtre (non réentrant)
    with page.lock:
        if getattr(page, "cams", None) is None:
            page.cams = reachy_cams.Cams(page.body, personnes)
    parties = urlsplit(chemin)
    if methode == "GET" and parties.path == reachy_cams.PREFIXE + "/vue":
        q = {k: v[0] for k, v in parse_qs(parties.query).items()}
        if not page.jeton_valide(q.get("jeton")):
            return h.refuse(HTTPStatus.FORBIDDEN, "page périmée : la recharger")
        try:
            jpeg = page.cams.image(q.get("p", ""), q.get("f", ""))
        except reachy_personnes.Refus as refus:
            return h.refuse(refus.status, refus.message)
        return h.send(HTTPStatus.OK, jpeg, "image/jpeg")
    demande = None
    if methode == "POST":
        demande, refuse = _demande_permise(h) or (None, True)
        if refuse:
            return
    statut, reponse = page.cams.route(methode, parties.path, demande)
    return h.send(statut, reponse)


# --- PERSONNES : fin ----------------------------------------------------------------------------------------
# --- Lot 4 : les routes des assistants de calibrage ---------------------------------------------------------
def _routes_assistants(handler, methode, chemin):
    """`/api/assistants…` : le catalogue, l'état de la session, et ses boutons (lancer, suivant, recommencer,
    annuler, appliquer). → vrai si la route est de ce module (la réponse est alors envoyée), faux sinon.
    Une écriture passe par les mêmes trois gardes que celle des réglages (`Handler.ecriture_permise`) ; ce que
    « appliquer » écrit passe par le schéma (validation, sauvegarde de `vivant.json`, écriture atomique)."""
    if chemin != ASSISTANTS and not chemin.startswith(ASSISTANTS + "/"):
        return False
    sous, page = chemin[len(ASSISTANTS):], handler.page
    moteur = reachy_assistants.Moteur.de(page.body)
    if methode == "GET":
        if sous == "":
            handler.send(HTTPStatus.OK, {"assistants": moteur.catalogue(), "ecriture": moteur.peut_ecrire})
        elif sous == "/session":
            handler.send(HTTPStatus.OK, {"session": moteur.etat()})
        else:
            handler.refuse(HTTPStatus.NOT_FOUND, "inconnu")
        return True
    boutons = {"/suivant": moteur.suivant, "/recommencer": moteur.recommencer, "/annuler": moteur.annuler,
               "/appliquer": moteur.appliquer}
    if sous not in boutons and sous != "/lancer":
        handler.refuse(HTTPStatus.NOT_FOUND, "inconnu")
        return True
    if not handler.ecriture_permise():
        return True
    try:
        taille = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        taille = -1
    if not 0 < taille <= TAILLE_MAX:
        handler.refuse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "demande trop grande")
        return True
    try:
        demande = json.loads(handler.rfile.read(taille))
        if not isinstance(demande, dict):
            raise ValueError("un objet JSON est attendu")
        if sous == "/lancer":
            etat = moteur.lancer(str(demande.get("assistant", "")))
        else:
            etat = boutons[sous]()
        handler.send(HTTPStatus.OK, {"session": etat})
    except reachy_assistants.Refus as refus:       # pas maintenant (quelqu'un parle, mesure pas finie…)
        handler.refuse(HTTPStatus.CONFLICT, str(refus)[:200])
    except ValueError as trouble:                  # JSON illisible, assistant inconnu, valeur refusée par le schéma
        handler.refuse(HTTPStatus.BAD_REQUEST, str(trouble)[:200])
    except OSError as trouble:
        handler.refuse(HTTPStatus.INTERNAL_SERVER_ERROR, f"écriture impossible : {str(trouble)[:120]}")
    return True
