#!/usr/bin/env python3
"""Helper Home Assistant du Compagnon.

Seul composant qui détient le token HA (dans ~/.config/omarchy-companion/ha.json).
L'agent ne voit jamais le token : il n'appelle que des verbes.
Les domaines sensibles (serrures, alarme…) sont refusés ici, quoi que demande l'agent.

Usage :
  ha.py areas                      -> pièces et entités pilotables (pour le prompt)
  ha.py state <entity_id>          -> état courant d'une entité
  ha.py on  <entity...>            -> allume / ouvre (plusieurs entités permises)
  ha.py off <entity...>            -> éteint / ferme
  ha.py set <entity...> <0-100>    -> luminosité ou position en pourcentage
  ha.py scene <entity_id>          -> active une scène

Aucun appel de service libre : chaque verbe fixe lui-même le domaine et le service, sur une
seule entité validée. Une entité hors des domaines pilotables est refusée.
"""
import json
import texts
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reseau  # noqa: E402
import trousseau  # noqa: E402

CONFIG = Path(os.environ.get("COMPANION_HA_CONFIG",
                             str(Path.home() / ".config/omarchy-companion/ha.json")))
# Jamais pilotables, même sur demande explicite de l'utilisateur.
DEFAULT_BLOCKED = ["lock", "alarm_control_panel"]
# Seuls domaines pilotables. Tout le reste (serrures, alarme, automatisations, `all`…) est refusé.
CONTROLLABLE = ("light", "switch", "cover", "fan", "climate", "media_player", "scene", "script", "input_boolean")
ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def load():
    if not CONFIG.exists():
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.0"))
    try:
        data = json.loads(CONFIG.read_text())
    except json.JSONDecodeError:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.1"))
    # Le jeton peut vivre dans le trousseau du système (18/10) : ha.json ne garde alors que l'adresse.
    if data.get("token_store") == "keyring":
        data["token"] = trousseau.lire("ha")
    if not data.get("url") or not data.get("token"):
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.2"))
    trousseau.masquer_sorties(data["token"])
    # Le jeton ne part jamais en clair sur Internet (reseau.py) : HTTPS, ou HTTP vers le réseau local.
    if not reseau.secret_destination_ok(data["url"]):
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.3"))
    data.setdefault("blocked_domains", DEFAULT_BLOCKED)
    return data


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Une redirection emporterait le jeton (en-tête Authorization) vers une autre adresse."""
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def api(config, method, path, payload=None):
    url = config["url"].rstrip("/") + path
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method,
                                     headers={"Authorization": "Bearer " + config["token"],
                                              "Content-Type": "application/json"})
    try:
        with OPENER.open(request, timeout=12) as response:
            text = response.read().decode()
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.4"))
        if error.code == 401:
            fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.5"))
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.0", code=error.code))
    except urllib.error.URLError as error:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.1", reason=error.reason))


def check_domain(config, entity_id, allowed=CONTROLLABLE):
    """Une seule entité, bien formée, d'un domaine pilotable et non bloqué. Sinon refus."""
    if not ENTITY.match(entity_id or ""):
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.entity", entity=entity_id))
    domain = entity_id.split(".", 1)[0]
    if domain in DEFAULT_BLOCKED or domain in config.get("blocked_domains", DEFAULT_BLOCKED):
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.protected", domain=domain))
    if domain not in allowed:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.domain", domain=domain))
    return domain


def friendly(state):
    attrs = state.get("attributes", {})
    name = attrs.get("friendly_name", state.get("entity_id"))
    return name, state.get("state"), attrs


def informative(entity, name):
    """Le nom lisible apporte-t-il quelque chose de plus que l'identifiant ?

    « LUMIERE-PORCHE-ENTREE » pour `light.lumiere_porche_entree` ne dit rien de neuf et coûte la
    place d'une autre entité. « Inter - Couloir » pour `switch.inter_couloir`, si.
    """
    short = entity.split(".", 1)[-1]
    reduce = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
    return bool(name) and reduce(name) != reduce(short)


def chacune(config, entities, action):
    """Applique l'action à chaque entité. Une qui échoue n'emporte pas les suivantes : Home
    Assistant répond 429 quand les appels s'enchaînent trop vite, et le volet suivant restait
    ouvert (constaté le 20/09 sur les trois volets du salon). Petite pause entre deux."""
    problems = []
    for index, entity in enumerate(entities):
        if index:
            time.sleep(0.4)
        try:
            action(config, entity)
        except SystemExit:
            problems.append(entity)
    if problems:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.failed", items=", ".join(problems)))


def cmd_areas(config):
    """Liste compacte des entités pilotables par domaine utile, pour le prompt système.

    🛑 Pas de coupe : elle en gardait 60 par domaine, par ordre alphabétique. Sur les 203
    interrupteurs d'une vraie maison, 143 entités pilotables sur 325 tombaient hors de la liste — dont
    `switch.inter_couloir`, la lumière de son couloir, qu'il voyait pourtant dans Home Assistant et
    dans Google Home (19/09). Le nom lisible n'est écrit que s'il ajoute quelque chose : les 325
    entités tiennent alors en ~17 000 caractères, sous le plafond du moteur.
    """
    states = api(config, "GET", "/api/states")
    useful = CONTROLLABLE
    blocked = config.get("blocked_domains", DEFAULT_BLOCKED)
    lines = {}
    for state in states:
        entity = state.get("entity_id", "")
        domain = entity.split(".", 1)[0]
        if domain not in useful or domain in blocked:
            continue
        name = state.get("attributes", {}).get("friendly_name", "")
        lines.setdefault(domain, []).append(f"{entity} ({name})" if informative(entity, name) else entity)
    out = []
    for domain in useful:
        if domain in lines:
            out.append(domain + " : " + " · ".join(sorted(lines[domain])))
    print("\n".join(out) if out else "Aucune entité pilotable exposée.")


def cmd_state(config, entity_id):
    if not ENTITY.match(entity_id or ""):
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.entity", entity=entity_id))
    state = api(config, "GET", "/api/states/" + entity_id)
    name, value, attrs = friendly(state)
    extra = ""
    if "brightness" in attrs and attrs["brightness"] is not None:
        extra = f" ({round(attrs['brightness'] / 255 * 100)} %)"
    elif "current_position" in attrs:
        extra = f" ({attrs['current_position']} %)"
    print(f"{name} : {value}{extra}")


def service_call(config, domain, service, entity_id, extra=None):
    """Appel interne seulement : domaine et service fixés par le verbe, l'entité jamais écrasée."""
    check_domain(config, entity_id)
    payload = dict(extra or {})
    payload["entity_id"] = entity_id
    api(config, "POST", f"/api/services/{domain}/{service}", payload)
    print(f"OK {domain}.{service} → {entity_id}")


def cmd_onoff(config, entity_id, on):
    """Une entité. Plusieurs se font en plusieurs appels, depuis `main` — chacune est validée."""
    domain = check_domain(config, entity_id)
    service_domain = domain if domain in ("light", "switch", "fan", "cover", "input_boolean", "climate", "media_player") else "homeassistant"
    if domain == "cover":
        service = "open_cover" if on else "close_cover"
    else:
        service = "turn_on" if on else "turn_off"
    service_call(config, service_domain, service, entity_id)


def cmd_set(config, entity_id, percent):
    domain = check_domain(config, entity_id)
    try:
        value = max(0, min(100, int(percent)))
    except ValueError:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.percent"))
    if domain == "light":
        service_call(config, "light", "turn_on", entity_id, {"brightness_pct": value})
    elif domain == "cover":
        service_call(config, "cover", "set_cover_position", entity_id, {"position": value})
    else:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.set", domain=domain))


def main(argv):
    if not argv:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.ha.verb"))
    config = load()
    verb = argv[0]
    if verb == "areas":
        cmd_areas(config)
    elif verb == "state" and len(argv) == 2:
        cmd_state(config, argv[1])
    elif verb in ("on", "off") and len(argv) >= 2:
        # Plusieurs entités en UN appel : sinon l'agent écrit une boucle shell, et une boucle perd
        # l'autorisation du helper comme sa sortie du bac à sable — donc l'accès au jeton (constaté
        # le 20/09 : « ferme les volets du salon » a échoué pour cette seule raison). Chaque entité
        # reste validée une par une, la carte montre la commande entière.
        chacune(config, argv[1:], lambda c, e: cmd_onoff(c, e, verb == "on"))
    elif verb == "set" and len(argv) >= 3:
        # Le pourcentage est le DERNIER argument ; tout ce qui précède est une entité.
        chacune(config, argv[1:-1], lambda c, e: cmd_set(c, e, argv[-1]))
    elif verb == "scene" and len(argv) == 2:
        check_domain(config, argv[1], allowed=("scene",))
        service_call(config, "scene", "turn_on", argv[1])
    else:
        fail("Usage : areas | state <e> | on <e...> | off <e...> | set <e...> <0-100> | scene <e>")


if __name__ == "__main__":
    main(sys.argv[1:])
