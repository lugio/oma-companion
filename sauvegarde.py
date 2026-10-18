#!/usr/bin/env python3
"""Sauvegarde et restauration de la configuration d'Alison (Réglages › Sauvegarde, 18/10/2026).

Un fichier JSON lisible, versionné, qu'on garde ou qu'on emporte sur une autre machine.

- Ce qui part TOUJOURS : les préférences (PREFERENCES), les rôles du dossier standard, la personnalité
  choisie d'Alison, la veille de la maison (`maison.json`).
- Ce qui ne part QUE sur demande : les POINTEURS (chemins de coffre, comptes, adresses). Ce ne sont pas des
  secrets, mais ils disent où les secrets se trouvent et à quel compte ils ouvrent.
- Ce qui ne part JAMAIS : jetons et mots de passe (ha.json, coffres), mémoire et conversations, extensions
  privées (du code), le mode, les accès allumés, les sites de confiance, la validation vocale, le rôle actif.

Restaurer : aperçu d'abord (`preview`), sauvegarde automatique de l'état présent, puis application. Une
restauration ne RALLUME jamais rien : les clés de NEVER ne sont pas lues, même présentes dans le fichier.
Les réglages repartent vers le panneau, qui les fait écrire par le shell (seul écrivain de shell.json) ;
rôles, personnalité et maison sont écrits ici, en 600, par les mêmes contrôles que les Réglages.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re

import maison
import roles
import storage

FORMAT = "alison-backup"
VERSION = 1
SIZE_MAX = 1024 * 1024
DIR = Path(os.environ.get("COMPANION_BACKUPS",
                          str(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
                              / "omarchy-companion/sauvegardes")))
NAME = re.compile(r"alison-[0-9]{8}-[0-9]{6}(-[a-z-]{1,24})?\.json")

# Préférences : ce qui fait « mon Alison » sans rien ouvrir.
PREFERENCES = ("name", "language", "wakePhrase", "voice", "wakeword", "conversation", "recall", "dreams",
               "micro", "sttEngine", "sortie", "barge", "voiceStrip", "delegation", "omarchyKnowledge",
               "erpFiscalMonth", "mailStore", "erpStore")
# Pointeurs : sur demande seulement, à l'export comme à la restauration.
POINTERS = ("obsidianVault", "mailVault", "mailAccount", "erpVault", "erpAccount", "portailUrl",
            "portailVault", "portailAccount", "robotUrl", "privatePaths", "mailEmail", "mailHost", "mailPort", "erpUrl")
# Jamais restaurés : ce qui ouvre des droits ou dit qui répond. Ignorés même s'ils sont dans le fichier.
NEVER = ("mode", "home", "mail", "erp", "portail", "robot", "trustedSites", "voiceDecide", "role", "setupDone",
         # La DESTINATION des conversations (moteur, adresse, modèle, variable de clé) : une sauvegarde piégée
         # redirigerait les échanges — et la clé — vers son serveur (revue Codex, 18/10). Se règle à la main.
         "provider", "endpoint", "model", "keyEnv",
         # Les dossiers de rôles en plus : en changer peut faire disparaître le rôle actif, donc lever ses
         # restrictions (revue Codex, 18/10).
         "rolePaths")
# Une destination d'accès changée par la restauration ÉTEINT l'accès concerné : on le rallume soi-même,
# en connaissance de la nouvelle adresse. Éteindre ne coûte rien ; brancher sans le savoir, si.
DESTINATIONS = {"mailVault": "mail", "mailAccount": "mail", "erpVault": "erp", "erpAccount": "erp",
                "mailEmail": "mail", "mailHost": "mail", "mailPort": "mail", "erpUrl": "erp",
                "portailUrl": "portail", "portailVault": "portail", "portailAccount": "portail", "robotUrl": "robot"}
URL_CREDENTIALS = re.compile(r"(?<=://)[^/@\s]+@")
# Un jeton passé en paramètre d'adresse (« ?token=… ») : la valeur est retirée à l'export.
URL_SECRET_PARAM = re.compile(r"([?&](?:token|access_token|key|api_key|apikey|secret|password|pass|auth)=)[^&#\s]*",
                              re.IGNORECASE)


def _role_form(role):
    return {"label": role.get("label", ""), "description": role.get("description", ""),
            "persona": role.get("persona", ""), "modes": list(role.get("modes") or []),
            "access": None if role.get("access") is None else list(role["access"]),
            "forbid": list(role.get("forbid") or []), "memory": role.get("memory", "separate"),
            "delegate": None if role.get("delegate") is None else list(role["delegate"])}


def export(config, persona_text="", pointers=False):
    """Le contenu d'une sauvegarde (un dict), sans rien écrire."""
    settings = {key: config[key] for key in PREFERENCES if key in config}
    if pointers:
        settings.update({key: config[key] for key in POINTERS if key in config})
    for key, value in list(settings.items()):         # « https://moi:motdepasse@hôte » : l'identifiant reste ici
        if isinstance(value, str):
            settings[key] = URL_SECRET_PARAM.sub(r"\1", URL_CREDENTIALS.sub("", value))
    found = {}
    for card in roles.available(config):
        role = roles.load(config, card["name"])
        if role and roles.editable(role):          # un corpus branché par rolePaths reste où il est
            found[card["name"]] = _role_form(role)
    return {"format": FORMAT, "version": VERSION,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "pointers": bool(pointers), "settings": settings, "roles": found,
            "persona": persona_text or "",
            "maison": {"rules": [dict(rule, who=[list(w) for w in rule.get("who", ())]) for rule in maison.load()]}}


def write(data, label=""):
    """Écrit une sauvegarde dans DIR (700, fichier 600). → le chemin."""
    storage.private_dir(DIR)
    suffix = f"-{label}" if label and re.fullmatch(r"[a-z-]{1,24}", label) else ""
    stamp = datetime.datetime.now()
    path = DIR / f"alison-{stamp.strftime('%Y%m%d-%H%M%S')}{suffix}.json"
    while path.exists():                       # deux sauvegardes dans la même seconde : jamais d'écrasement
        stamp += datetime.timedelta(seconds=1)
        path = DIR / f"alison-{stamp.strftime('%Y%m%d-%H%M%S')}{suffix}.json"
    storage.private_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


def listing():
    """Les sauvegardes du dossier, la plus récente d'abord."""
    try:
        files = [p for p in DIR.iterdir() if NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    except OSError:
        return []
    return [{"path": str(p), "name": p.name, "size": p.stat().st_size}
            for p in sorted(files, key=lambda p: p.name, reverse=True)]


def read(path):
    """Une sauvegarde lue et contrôlée, ou ValueError avec une raison courte (clé de texte)."""
    return read_with_digest(path)[0]


def read_with_digest(path):
    """(sauvegarde contrôlée, empreinte sha256 des octets lus) — lus UNE fois : l'empreinte est celle du
    contenu contrôlé, pas d'une relecture."""
    try:
        path = Path(os.path.expanduser(str(path)))
        if path.is_symlink() or not path.is_file():
            raise ValueError("backup.err_file")
        if path.stat().st_size > SIZE_MAX:
            raise ValueError("backup.err_size")
        with path.open("rb") as handle:
            raw = handle.read(SIZE_MAX + 1)
        if len(raw) > SIZE_MAX:
            raise ValueError("backup.err_size")
        digest = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        raise ValueError("backup.err_file") from None
    except json.JSONDecodeError:
        raise ValueError("backup.err_format") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("backup.err_format")
    if data.get("version") != VERSION:
        raise ValueError("backup.err_version")
    for key, kind in (("settings", dict), ("roles", dict), ("maison", dict)):
        if not isinstance(data.get(key, {}), kind):
            raise ValueError("backup.err_format")
    if not isinstance(data.get("persona", ""), str):
        raise ValueError("backup.err_format")
    return data, digest


def importable_settings(data, defaults, pointers=False, config=None):
    """Les réglages restaurables : connus, du bon type, jamais une clé de NEVER, pointeurs sur demande.
    Avec `config` (l'état présent) : les emplacements privés sont FUSIONNÉS (une restauration n'en retire
    aucun), et un accès dont la destination change est éteint."""
    allowed = PREFERENCES + (POINTERS if pointers else ())
    config = config or {}
    out = {}
    for key, value in (data.get("settings") or {}).items():
        if key in NEVER or key not in allowed or key not in defaults:
            continue
        if isinstance(value, type(defaults[key])) and not (isinstance(value, bool) and not isinstance(defaults[key], bool)):
            out[key] = value
    if "privatePaths" in out:
        present = [p for p in (config.get("privatePaths") or []) if isinstance(p, str)]
        out["privatePaths"] = present + [p for p in out["privatePaths"] if isinstance(p, str) and p not in present]
    for key, access in DESTINATIONS.items():
        if key in out and out[key] != config.get(key, defaults.get(key)):
            out[access] = False
    return out


def preview(data, config, defaults, pointers=False):
    """Ce que la restauration changerait, sans rien écrire."""
    settings = importable_settings(data, defaults, pointers, config)
    changed = [{"key": k, "now": config.get(k), "then": v} for k, v in settings.items() if config.get(k) != v]
    existing = {card["name"] for card in roles.available(config)}
    names = [n for n in (data.get("roles") or {}) if isinstance(n, str) and roles.NAME_OK.match(n)]
    rules = (data.get("maison") or {}).get("rules") or []
    return {"created": str(data.get("created", ""))[:19], "settings": changed,
            "ignored": sorted(k for k in (data.get("settings") or {}) if k in NEVER),
            "pointersInFile": bool(data.get("pointers")),
            "rolesNew": sorted(n for n in names if n not in existing),
            "rolesReplaced": sorted(n for n in names if n in existing),
            "persona": bool(data.get("persona")), "personaReset": "persona" in data and not data.get("persona"),
            "maisonRules": len(rules) if isinstance(rules, list) else 0,
            "maisonPresent": isinstance(rules, list) and "maison" in data,
            "switchedOff": sorted(k for k in ("mail", "erp", "portail", "robot") if settings.get(k) is False)}


def apply(data, config, defaults, write_persona, pointers=False, replace_roles=False, persona_path=None):
    """Écrit rôles, personnalité et maison ; rend les réglages à faire écrire par le shell et la liste des
    erreurs. Tout est validé avant la première écriture."""
    errors = []
    pending = []
    existing = {card["name"] for card in roles.available(config)}
    for name, form in (data.get("roles") or {}).items():
        if not isinstance(name, str) or not roles.NAME_OK.match(name) or not isinstance(form, dict):
            errors.append(f"{name}: backup.err_role")
            continue
        if name in existing and not replace_roles:
            continue
        if name == config.get("role"):
            errors.append(f"{name}: backup.err_role_active")   # jamais sous les pieds du rôle en cours
            continue
        # Les modes d'un rôle sont une échelle continue depuis Discussion : autre chose ne se recopie pas
        # en plafond (["chat", "code"] ouvrirait Lecture et Assistant) — le rôle est refusé, pas deviné.
        if (not isinstance(form.get("modes"), list)
                or not isinstance(form.get("persona", ""), str)
                or len(form.get("persona", "")) > roles.MAX_PERSONA
                or (form.get("access") is not None and not isinstance(form["access"], list))
                or not isinstance(form.get("forbid", []), list)):
            errors.append(f"{name}: backup.err_role")
            continue
        modes = form["modes"]
        if not modes or modes != list(roles.modes_module.MODES[:len(modes)]):
            errors.append(f"{name}: backup.err_role")
            continue
        ceiling = modes[-1]
        access = form.get("access")
        access = list(roles.ACCESS_KEYS) if access is None else [a for a in access if a in roles.ACCESS_KEYS]
        role_form = {"name": name, "label": str(form.get("label", ""))[:64],
                                    "description": str(form.get("description", ""))[:200],
                                    "persona_text": str(form.get("persona", ""))[:roles.MAX_PERSONA],
                                    "ceiling": ceiling, "access": access,
                                    "forbid": ", ".join(str(w) for w in (form.get("forbid") or [])),
                                    "memory": form.get("memory", "separate"),
                                    "delegate": form.get("delegate") if isinstance(form.get("delegate"), list) else None}
        error = roles.save(config, role_form, dry_run=True)
        if error:
            errors.append(f"{name}: {error}")
        pending.append(role_form)
    # Restaurer = revenir à l'état du fichier, vides compris : une personnalité vide rend l'Alison livrée,
    # une veille sans règle n'en garde aucune (l'aperçu le dit, et l'état présent est sauvegardé avant).
    if "persona" in data and (not isinstance(data["persona"], str) or len(data["persona"]) > 4000):
        errors.append("backup.err_format")
    raw_rules = (data.get("maison") or {}).get("rules") if isinstance(data.get("maison"), dict) else None
    rules = []
    if "maison" in data:
        if not isinstance(raw_rules, list):
            errors.append("backup.err_format")
        else:
            for raw in raw_rules:
                rule = maison._rule(raw)
                if rule is None:
                    errors.append("backup.err_format")
                else:
                    rules.append(rule)
    if errors:
        return {}, errors

    # Garder les octets et les permissions, y compris l'absence d'un fichier.
    paths = [roles.STANDARD / form["name"] / file
             for form in pending for file in ("role.json", "role.md")]
    if "maison" in data:
        paths.append(maison.CONFIG)
    if persona_path is not None and "persona" in data:
        paths.append(Path(persona_path))
    before = {}
    absent_dirs = set()
    try:
        for path in paths:
            if path.is_symlink():
                return {}, ["backup.err_file"]
            before[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
            parent = path.parent
            while not parent.exists():
                absent_dirs.add(parent)
                parent = parent.parent
        for form in pending:
            error = roles.save(config, form)
            if error:
                raise ValueError(error)
        if "maison" in data:
            storage.private_dir(maison.CONFIG.parent)
            storage.private_write(maison.CONFIG, json.dumps(
                {"rules": [dict(r, who=[list(w) for w in r.get("who", ())]) for r in rules]},
                ensure_ascii=False, indent=2) + "\n")
        # Dernière écriture : l'appelant fournit son chemin pour permettre le retour arrière.
        if "persona" in data:
            write_persona(data["persona"])
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        for path, previous in before.items():
            try:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(previous[0])
                    path.chmod(previous[1])
            except OSError as rollback_error:
                errors.append(str(rollback_error))
        for folder in sorted(absent_dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass
        roles._cache.clear()
        return {}, errors
    return importable_settings(data, defaults, pointers, config), errors
