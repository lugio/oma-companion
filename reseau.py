#!/usr/bin/env python3
"""Où un utilitaire a le droit d'envoyer un secret (jeton HA, clé Dolibarr) — 18/10/2026.

HTTPS partout ; HTTP en clair seulement vers la machine elle-même ou le réseau local (adresse IP privée,
nom en .local / .lan / .home.arpa / .internal). Ailleurs, le jeton passerait lisible sur Internet : refusé.
Bibliothèque standard seulement, rien d'autre ici (importé par ha.py et dolibarr.py, lancés en script).
"""
import ipaddress
import urllib.parse

LOCAL_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal")


def secret_destination_ok(url):
    """Vrai si l'on peut envoyer un secret à `url`."""
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local
