#!/usr/bin/env python3
"""Le trousseau du système pour les secrets d'Alison (18/10/2026).

Omarchy livre gnome-keyring (Secret Service) et `secret-tool` (libsecret) : un mot de passe, un jeton ou une
clé d'API s'y range sans coffre JSON à tenir soi-même. Le coffre reste possible, il devient FACULTATIF.

- Une entrée = attributs `application=omarchy-companion`, `acces=<mail|erp|ha>`, `champ=<password|api_key|token>`.
  Ce qui n'est PAS secret (adresse, identifiant, serveur) reste dans les réglages, comme un pointeur.
- Seuls le moteur (pour ranger, sur un clic) et l'utilitaire de l'accès (pour lire) touchent au trousseau,
  tous deux hors du bac à sable. L'agent ne le peut pas : le bac à sable coupe D-Bus, et le garde refuse
  `secret-tool` et les appels D-Bus au service des secrets.
- Un utilitaire qui a lu son secret MASQUE toute réapparition de sa valeur dans
  ce qu'il imprime (`masquer_sorties`) : une réponse de serveur qui recrache la clé n'arrive jamais à l'agent.

Rien ne s'affiche jamais : ni valeur, ni morceau de valeur. Bibliothèque standard + `secret-tool`.
"""
import atexit
import io
import json
import shutil
import urllib.parse
import subprocess
import sys

APPLICATION = "omarchy-companion"
ACCES = ("mail", "erp", "ha")
CHAMPS = {"mail": "password", "erp": "api_key", "ha": "token"}
DELAI = 8
MASQUE = "[secret masqué]"


def disponible():
    """Vrai si `secret-tool` existe et que le service des secrets répond (session ouverte)."""
    if shutil.which("secret-tool") is None:
        return False
    try:
        done = subprocess.run(["secret-tool", "search", "application", APPLICATION, "acces", "_sonde_"],
                              capture_output=True, text=True, timeout=DELAI)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode in (0, 1)        # 1 = rien trouvé, le service a répondu


def _attributs(acces):
    if acces not in ACCES:
        raise ValueError("accès inconnu")
    return ["application", APPLICATION, "acces", acces, "champ", CHAMPS[acces]]


def lire(acces):
    """La valeur rangée pour cet accès, ou "" (absente, trousseau verrouillé ou indisponible)."""
    return lire_etat(acces)[0]


def lire_etat(acces):
    """(valeur, sûr) : `sûr` est faux quand le trousseau n'a pas pu répondre (verrouillé, absent, délai) —
    « vide » et « illisible » ne se confondent jamais là où une décision en dépend (revue Codex du 18/10)."""
    try:
        done = subprocess.run(["secret-tool", "lookup", *_attributs(acces)],
                              capture_output=True, text=True, timeout=DELAI)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return "", False
    if done.returncode == 0:
        return done.stdout.rstrip("\n"), True
    # secret-tool rend 1 sans rien sur stderr quand l'entrée n'existe pas ; un message = un vrai problème.
    return "", done.returncode == 1 and not done.stderr.strip()


def ranger(acces, valeur, libelle=""):
    """Range la valeur (par l'entrée standard de secret-tool, jamais en argument visible dans `ps`)."""
    valeur = str(valeur or "")
    # 8 caractères au moins : plus court, ce n'est pas un secret, et le masquage des sorties ne pourrait
    # pas le reconnaître sans abîmer tout le texte (revue Codex du 18/10).
    if len(valeur) < 8 or "\n" in valeur:
        return False
    try:
        done = subprocess.run(["secret-tool", "store", "--label", libelle or f"Alison — {acces}", *_attributs(acces)],
                              input=valeur, capture_output=True, text=True, timeout=DELAI)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return done.returncode == 0


def effacer(acces):
    try:
        done = subprocess.run(["secret-tool", "clear", *_attributs(acces)], capture_output=True, text=True,
                              timeout=DELAI)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return done.returncode == 0


def present(acces):
    """Vrai si une valeur est rangée (la valeur n'est jamais rendue ici)."""
    return bool(lire(acces))


class _Masque(io.TextIOBase):
    """Une sortie qui remplace chaque valeur secrète connue par un masque, ligne par ligne."""

    def __init__(self, cible, valeurs):
        self.cible = cible
        self.valeurs = []
        self.ajouter(valeurs)
        self.reste = ""

    def ajouter(self, valeurs):
        """La valeur, et ses formes courantes dans une réponse (encodée en URL, échappée en JSON)."""
        formes = set(self.valeurs)
        for valeur in valeurs:
            if not valeur:
                continue
            if len(valeur) >= 3:               # la valeur exacte dès 3 caractères (1 ou 2 : ce n'est pas un secret,
                formes.add(valeur)             # et masquer « t » effacerait toutes les lettres t du texte)
            formes.update(f for f in (urllib.parse.quote(valeur, safe=""), urllib.parse.quote_plus(valeur),
                                      json.dumps(valeur)[1:-1]) if len(f) >= 4 and f != valeur)
        self.valeurs = sorted(formes, key=len, reverse=True)

    def write(self, texte):
        self.reste += texte
        if "\n" not in self.reste:
            return len(texte)
        lignes, self.reste = self.reste.rsplit("\n", 1)
        self.cible.write(self._masquer(lignes) + "\n")
        return len(texte)

    def flush(self, final=False):
        # Une valeur peut arriver en deux morceaux : on garde la fin du tampon (la longueur du plus long
        # secret moins un) jusqu'à la ligne suivante ou la sortie du programme.
        garde = 0 if final or not self.valeurs else len(self.valeurs[0]) - 1
        if self.reste:
            masque = self._masquer(self.reste)
            if garde and len(self.reste) > garde:
                coupe = len(self.reste) - garde
                tete, self.reste = self.reste[:coupe], self.reste[coupe:]
                masque = self._masquer(tete)
                if any(v[:1] and tete.endswith(v[:i]) for v in self.valeurs for i in range(1, len(v))):
                    self.reste, masque = tete + self.reste, ""
                self.cible.write(masque)
            elif not garde:
                self.cible.write(masque)
                self.reste = ""
        self.cible.flush()

    def _masquer(self, texte):
        for valeur in self.valeurs:
            texte = texte.replace(valeur, MASQUE)
        return texte


def masquer_sorties(*valeurs):
    """À appeler dès qu'un utilitaire connaît ses secrets : stdout et stderr ne les laisseront plus passer."""
    valeurs = [str(v) for v in valeurs if v]   # même court : mieux vaut un texte abîmé qu'un secret qui sort
    if not valeurs:
        return
    if not isinstance(sys.stdout, _Masque):
        sys.stdout = _Masque(sys.stdout, valeurs)
        sys.stderr = _Masque(sys.stderr, valeurs)
        atexit.register(lambda: (sys.stdout.flush(final=True), sys.stderr.flush(final=True)))
    else:
        for flux in (sys.stdout, sys.stderr):
            flux.ajouter(valeurs)
