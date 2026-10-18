#!/usr/bin/env python3
"""Rôles du Compagnon : une personnalité, un métier, des droits — dans un dossier qu'on dépose.

Deux axes, qu'on ne confond jamais :
- le MODE dit ce qu'elle a le DROIT de faire (Discussion, Lecture, Assistant, Code) ;
- le RÔLE dit QUI répond, avec quel savoir, et quelles restrictions EN PLUS.

🛑 Invariant, et c'est lui qui rend la chose publiable : **un rôle ne peut que RETIRER**. Il ne
donne jamais un droit que le mode refuse. Sinon un dossier déposé — ou récupéré sur le web —
suffirait à ouvrir la machine, et « le mode Lecture ne change rien » redeviendrait une promesse.
Tout ce qu'un rôle déclare est une restriction : modes permis, aides autorisées, mots refusés.

Un rôle = un dossier, rien d'autre à installer :

    <dossier>/<nom>/role.md      la personnalité (à défaut AGENTS.md, puis CLAUDE.md)
    <dossier>/<nom>/role.json    facultatif : étiquette, restrictions, mémoire, modèle

Où on les cherche :
- toujours ~/.config/omarchy-companion/roles/ (l'emplacement standard, vide à l'installation) ;
- plus chaque chemin du réglage `rolePaths`, pour brancher un corpus qui existe déjà
  (~/.claude/roles par exemple) sans le recopier.

Aucun rôle trouvé = rien ne change à l'écran : le compagnon reste lui-même, et l'utilisateur qui
n'en veut pas ne voit jamais la notion.

Contenu de role.json (tous les champs sont facultatifs) :

    {
      "label":       "Compta",                  nom affiché (défaut : le nom du dossier)
      "description": "Écritures, TVA, bilans.", une ligne, affichée dans les Réglages
      "persona":     "~/ailleurs/AGENTS.md",    personnalité hors du dossier
      "modes":       ["read", "assistant"],     modes permis DANS ce rôle (défaut : tous)
      "access":      ["mail", "erp"],           accès permis parmi home/mail/erp/portail/robot (défaut : tous)
                                                (l'ancien nom "tools", avec "ha", est encore lu)
      "skills":      ["compta"],                liste blanche, en mode Code seulement
      "forbid":      ["smtp", "sendmail"],      mots refusés dans toute commande, par le garde
      "delegate":    ["compta"],                rôles à qui celui-ci peut poser une question (défaut : tous,
                                                [] = aucun) — lecture seule, un aller-retour (delegue.py)
      "memory":      "separate",                "separate" (défaut) ou "shared"
      "model":       ""                         modèle imposé (défaut : celui du compagnon)
    }
"""
import json
import os
import shutil
from pathlib import Path
import re
import unicodedata

import modes as modes_module

HOME = Path.home()
# Emplacement standard, toujours lu. Le réglage `rolePaths` en ajoute d'autres.
STANDARD = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config"))) / "omarchy-companion/roles"

# Nom de rôle = nom de dossier, et rien qui puisse remonter l'arborescence.
NAME_OK = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
PERSONA_FILES = ("role.md", "AGENTS.md", "CLAUDE.md")
# Une personnalité part dans CHAQUE question : au-delà, on coupe (et on le dit dans le journal).
MAX_PERSONA = 16000
# Les seuls accès qu'un rôle peut fermer. Il ne peut en ouvrir aucun : un accès dépend des
# réglages et du mode, pas du rôle. Mêmes clés que `backend.ACCESSES` et que les pastilles.
ACCESS_KEYS = ("home", "mail", "erp", "portail", "robot")
# Ancien nom du champ et ancienne clé de la maison, lus encore pour ne casser aucun rôle déposé.
LEGACY_ACCESS = {"ha": "home"}
MEMORIES = ("separate", "shared")


def expand(path):
    return Path(os.path.expanduser(os.path.expandvars(str(path)))).resolve()


def folders(config):
    """Dossiers où chercher des rôles : l'emplacement standard, puis ceux des réglages."""
    found, seen = [], set()
    for raw in [STANDARD] + list(config.get("rolePaths") or []):
        if not str(raw).strip():
            continue
        try:
            path = expand(raw)
        except (OSError, ValueError):
            continue
        if path not in seen and path.is_dir():
            seen.add(path)
            found.append(path)
    return found


def protected(path):
    """Vrai si ce chemin est un emplacement que le garde ferme de toute façon.

    Une personnalité est un fichier LU et recopié dans la consigne : sans ce contrôle, un role.json
    pointant sur ~/.ssh/id_ed25519 ferait sortir la clé par le premier message. On réutilise la
    liste du garde plutôt que d'en tenir une deuxième."""
    try:
        import guard
    except ImportError:          # garde absent : on ferme, jamais l'inverse
        return True
    text = str(path)
    return any(re.search(pattern, text, re.IGNORECASE)
               for pattern in guard.PROTECTED + guard.PROTECTED_ASSISTANT + guard.OWN_STATE)


def manifest(folder):
    """role.json lu sans jamais lever : un fichier abîmé donne un rôle aux valeurs par défaut."""
    try:
        data = json.loads((folder / "role.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def persona_path(folder, data):
    """Fichier de personnalité : celui que role.json désigne, sinon la première convention trouvée."""
    named = str(data.get("persona") or "").strip()
    if named:
        try:
            path = expand(named if os.path.isabs(os.path.expanduser(named)) else folder / named)
        except (OSError, ValueError):
            return None
        return path if path.is_file() and not protected(path) else None
    for name in PERSONA_FILES:
        path = folder / name
        if path.is_file():
            return path
    return None


def words(data, key, allowed=None):
    """Liste de chaînes propres d'un champ de role.json. Absent = None (aucune restriction),
    présent = la liste, même vide (tout est retiré). La différence compte."""
    if key not in data:
        return None
    raw = data.get(key)
    if not isinstance(raw, list):
        return None
    kept = [str(item).strip() for item in raw if str(item).strip()]
    if allowed is not None:
        kept = [item for item in kept if item in allowed]
    return tuple(dict.fromkeys(kept))


def access_of(data):
    """Les accès permis : `"access"`, sinon l'ancien `"tools"` (avec `ha` traduit), sinon None = tous."""
    if "access" in data:
        return words(data, "access", ACCESS_KEYS)
    if "tools" in data:
        raw = data.get("tools")
        if isinstance(raw, list):
            data = dict(data, access=[LEGACY_ACCESS.get(str(item).strip(), str(item).strip()) for item in raw])
            return words(data, "access", ACCESS_KEYS)
    return None


def read_persona(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return text[:MAX_PERSONA]


# Le rôle actif est relu à chaque message (mode, droits, consigne) : sans mémoire, c'est une
# personnalité de 8 000 caractères relue du disque à chaque fois. On garde la dernière lecture et
# on la jette dès que le fichier bouge — modifier sa personnalité se voit au message suivant.
_cache = {}


def load(config, name):
    """Le rôle nommé, ou None. Ne lève jamais : un rôle illisible n'existe pas, il ne casse rien."""
    name = str(name or "").strip().lower()
    if not NAME_OK.match(name):
        return None
    known = _cache.get(name)
    if known:
        role, stamp = known
        try:
            marks = [(str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in stamp]
        except OSError:
            marks = None
        if marks is not None and marks == role["_stamp"]:
            return role
    for folder in folders(config):
        here = folder / name
        if not here.is_dir():
            continue
        data = manifest(here)
        path = persona_path(here, data)
        persona = read_persona(path) if path else ""
        if not persona:
            continue                      # un dossier sans personnalité n'est pas un rôle
        modes = words(data, "modes", modes_module.MODES)
        memory = str(data.get("memory") or "separate")
        watched = [f for f in (path, here / "role.json") if f.exists()]
        role = {
            "name": name,
            "label": str(data.get("label") or name.replace("-", " ").replace("_", " ").capitalize()),
            "description": str(data.get("description") or "").strip()[:200],
            "persona": persona,
            "source": str(path),
            "truncated": path.stat().st_size > MAX_PERSONA if path.exists() else False,
            # Absent = aucune restriction. Présent mais vide (ou ne citant aucun mode connu) =
            # le mode le plus fermé, jamais « tous » : une liste vide veut dire « rien de plus ».
            "modes": (tuple(modes_module.MODES) if modes is None
                      else tuple(m for m in modes_module.MODES if m in modes) or (modes_module.MODES[0],)),
            "access": access_of(data),
            "folder": str(here),
            "skills": words(data, "skills"),
            "forbid": words(data, "forbid") or (),
            "delegate": words(data, "delegate"),
            "memory": memory if memory in MEMORIES else "separate",
            "model": str(data.get("model") or ""),
            "_stamp": [(str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in watched],
        }
        _cache[name] = (role, watched)
        return role
    _cache.pop(name, None)
    return None


def available(config):
    """Tous les rôles lisibles, pour le panneau. Le premier dossier gagne en cas d'homonyme."""
    found, seen = [], set()
    for folder in folders(config):
        try:
            children = sorted(child for child in folder.iterdir() if child.is_dir())
        except OSError:
            continue
        for child in children:
            if child.name in seen or not NAME_OK.match(child.name):
                continue
            role = load(config, child.name)
            if role:
                seen.add(child.name)
                found.append(card(role))
    return found


def current(config):
    """Le rôle actif, ou None. Un rôle disparu (dossier effacé) redevient simplement None."""
    return load(config, config.get("role", ""))


def mode_for(role, mode):
    """Le mode réellement appliqué : un rôle peut fermer des modes, jamais en ouvrir un (modes.narrow)."""
    return modes_module.narrow(role["modes"], mode) if role else mode


def allows(role, key):
    """Cet accès (home, mail, erp) est-il permis dans ce rôle ?"""
    return role is None or role["access"] is None or key in role["access"]


def card(role):
    """La fiche d'un rôle pour les Réglages : ce qu'il est, et tout ce qu'il RETIRE. Le panneau
    n'a rien à recalculer, il affiche — sinon il montrerait une limite que le moteur n'applique pas."""
    return {"name": role["name"], "label": role["label"], "description": role["description"],
            "closes": [m for m in modes_module.MODES if m not in role["modes"]],
            "access": list(role["access"]) if role["access"] is not None else None,
            "forbid": list(role["forbid"]), "memory": role["memory"], "folder": role["folder"],
            "editable": editable(role),
            "delegate": list(role["delegate"]) if role["delegate"] is not None else None}


def may_delegate(role, target_name):
    """Ce rôle (None = elle-même) peut-il poser une question à ce rôle-là ? Un rôle ne peut que
    RETIRER : absent = tous les rôles installés, une liste = seulement ceux-là, [] = personne."""
    if role is None:
        return True
    return role["delegate"] is None or target_name in role["delegate"]


def targets(config, role):
    """Les rôles à qui l'on peut déléguer maintenant : les autres rôles installés, filtrés par
    la liste du rôle actif, et rien du tout si la délégation est coupée dans les Réglages."""
    if not config.get("delegation", True):
        return []
    own = role["name"] if role else ""
    return [card for card in available(config) if card["name"] != own and may_delegate(role, card["name"])]


def state_dir(role, state):
    """Où vivent le carnet et les notes de ce rôle.

    Séparés par défaut : mélanger des souvenirs personnels et la comptabilité d'une entreprise
    dans le même carnet est une faute de confidentialité, pas un détail de rangement. Un rôle
    peut demander `"memory": "shared"` s'il veut au contraire tout partager.
    """
    if role is None or role["memory"] == "shared":
        return Path(state)
    return Path(state) / "roles" / role["name"]


def editable(role):
    """Modifiable depuis les Réglages : seulement un rôle du dossier standard. Un rôle branché par
    `rolePaths` (un corpus qui existe ailleurs) est lu, jamais réécrit d'ici."""
    try:
        return Path(role["folder"]).resolve().parent == STANDARD.resolve()
    except (OSError, KeyError, TypeError):
        return False


EXAMPLES = Path(__file__).resolve().parent / "roles-exemples.json"


def examples(lang="fr"):
    """Les rôles d'exemple livrés avec le plugin, dans la langue demandée (repli : anglais)."""
    try:
        data = json.loads(EXAMPLES.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for item in data.get("roles", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or not NAME_OK.match(str(item.get("name", ""))):
            continue
        pick = lambda field: (item.get(field) or {}).get(lang) or (item.get(field) or {}).get("en", "")  # noqa: E731
        out.append({"name": item["name"], "label": pick("label"), "description": pick("description"),
                    "persona": pick("persona"), "ceiling": item.get("ceiling", "chat"),
                    "access": [a for a in item.get("access", []) if a in ACCESS_KEYS]})
    return out


def add_example(config, name, lang="fr"):
    """Copie un exemple dans le dossier standard, par le MÊME chemin que le formulaire (save) : mêmes
    contrôles, et un exemple ne peut que retirer comme n'importe quel rôle. → clé d'erreur ou None."""
    found = next((e for e in examples(lang) if e["name"] == name), None)
    if found is None:
        return "err.role_name"
    target = STANDARD / name
    if load(config, name) or target.exists() or target.is_symlink():
        return "err.role_exists"           # jamais par-dessus un dossier, même vide ou invalide
    return save(config, {"name": found["name"], "label": found["label"], "description": found["description"],
                         "persona_text": found["persona"], "ceiling": found["ceiling"],
                         "access": found["access"], "forbid": "", "memory": "separate"})


def save(config, form, dry_run=False):
    """Crée ou modifie un rôle du dossier standard d'après le formulaire des Réglages.

    Retourne une clé d'erreur (`err.role_*`) ou None. Tout ce qui est écrit est une RESTRICTION :
    le formulaire ne connaît que le plafond de mode, les accès permis, les mots interdits et le
    carnet — il ne peut rien ouvrir. La personnalité est un texte (role.md) ou un fichier existant
    (`persona`) ; un fichier protégé (clé, coffre) est refusé comme au chargement.
    """
    import storage
    name = str(form.get("name") or "").strip().lower()
    if not NAME_OK.match(name):
        return "err.role_name"
    existing = load(config, name)
    if existing and not editable(existing):
        return "err.role_readonly"
    persona_text = str(form.get("persona_text") or "").strip()
    persona_path = str(form.get("persona_path") or "").strip()
    folder = STANDARD / name
    # Jamais à travers un lien : un dossier de rôle symbolique ferait écrire ailleurs (revue Codex, 18/10).
    if folder.is_symlink() or STANDARD.is_symlink() or (folder.exists() and folder.resolve().parent != STANDARD.resolve()):
        return "err.role_readonly"
    if persona_path:
        try:
            path = expand(persona_path)
        except (OSError, ValueError):
            return "err.role_persona_path"
        if not path.is_file() or protected(path):
            return "err.role_persona_path"
    elif not persona_text and not (existing and existing.get("source")):
        return "err.role_persona"          # en modification, vide = on garde la personnalité en place
    ceiling = str(form.get("ceiling") or modes_module.MODES[-1])
    allowed = [m for m in modes_module.MODES if modes_module.rank(m) <= modes_module.rank(ceiling)]
    access = [k for k in (form.get("access") or []) if k in ACCESS_KEYS]
    forbid = [w.strip() for w in re.split(r"[,\n;]+", str(form.get("forbid") or "")) if w.strip()]
    memory = "shared" if str(form.get("memory") or "") == "shared" else "separate"
    manifest = {"label": str(form.get("label") or "").strip()[:60] or name.capitalize(),
                "description": str(form.get("description") or "").strip()[:200],
                "modes": allowed, "access": access, "forbid": forbid, "memory": memory}
    if isinstance(form.get("delegate"), list):        # absent ou null = tous les rôles
        manifest["delegate"] = [str(n).strip().lower() for n in form["delegate"] if NAME_OK.match(str(n).strip().lower())]
    if persona_path:
        manifest["persona"] = persona_path
    elif existing and existing.get("source") and not persona_text \
            and Path(existing["source"]).resolve() != (folder / "role.md").resolve():
        manifest["persona"] = str(existing["source"])      # on garde le fichier qu'il pointait déjà
    if dry_run:
        return None
    storage.private_dir(folder)
    storage.private_write(folder / "role.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if persona_text:
        storage.private_write(folder / "role.md", persona_text[:MAX_PERSONA] + "\n")
    _cache.pop(name, None)
    return None


def delete(config, name):
    """Supprime un rôle du dossier standard (et rien d'autre). Le carnet séparé du rôle, dans
    l'état privé, reste : c'est de la mémoire, on ne l'efface pas sans le demander."""
    name = str(name or "").strip().lower()
    if not NAME_OK.match(name):
        return "err.role_name"
    role = load(config, name)
    if not role:
        return "err.role_unknown"
    if not editable(role):
        return "err.role_readonly"
    folder = (STANDARD / name).resolve()
    if folder.parent != STANDARD.resolve():
        return "err.role_readonly"
    shutil.rmtree(folder, ignore_errors=True)
    _cache.pop(name, None)
    return None


def plain(text):
    """Texte comparable : sans accent, sans ponctuation, en minuscules."""
    text = unicodedata.normalize("NFD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def match(config, wanted):
    """Le nom du rôle que cette phrase désigne, ou "".

    À la voix, « la compta » doit tomber sur le rôle `compta` : on compare sans accent ni
    ponctuation, d'abord à l'identique, puis par inclusion. Rien de flou au-delà — un rôle pris
    par erreur change la personnalité ET les droits, ce n'est pas le genre d'erreur qu'on devine.
    """
    said = plain(wanted)
    if not said:
        return ""
    known = [(role["name"], plain(role["name"]), plain(role["label"])) for role in available(config)]
    for name, plain_name, plain_label in known:
        if said in (plain_name, plain_label):
            return name
    hits = [name for name, plain_name, plain_label in known
            if said in plain_name or said in plain_label
            or plain_name in said or plain_label in said]
    return hits[0] if len(hits) == 1 else ""
