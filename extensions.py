#!/usr/bin/env python3
"""Extensions privées d'Alison : les connecteurs propres à UNE installation, rangés hors du dépôt.

Le dépôt est générique (n'importe qui peut l'installer) ; ce qui n'existe que chez quelqu'un — le site
interne de son entreprise, par exemple — vit dans `~/.config/omarchy-companion/extensions/` (variable
`COMPANION_EXTENSIONS` pour les tests). Aucune extension n'est livrée : sans fichier, l'accès n'existe pas,
ni dans la consigne, ni dans les permissions, ni dans les Réglages.

Une extension « portail » = `portail.py`, un utilitaire sur le modèle de `mail.py` : il détient seul ses
identifiants et n'expose que des verbes. Le moteur n'EXÉCUTE jamais ce fichier pour le connaître : il en lit
trois constantes littérales (`READ_VERBS`, `WRITE_VERBS`, `PROMPT`) sans l'importer. L'agent, lui, l'appelle
comme un autre utilitaire : verbes de lecture pré-autorisés, le reste par carte.

Garde-fou : un fichier que d'autres comptes peuvent modifier (groupe ou monde en écriture), ou qui n'est pas à
l'utilisateur, est ignoré — sinon un tiers pourrait s'inviter dans la consigne et les pré-autorisations.
"""
import ast
import os
from pathlib import Path
import re

DIR = Path(os.environ.get("COMPANION_EXTENSIONS",
                          str(Path.home() / ".config/omarchy-companion/extensions")))
VERB = re.compile(r"[a-z][a-z0-9-]{0,30}")      # toujours en fullmatch (« $ » laisse passer un « \n »)
WANTED = ("READ_VERBS", "WRITE_VERBS", "PROMPT")
PROMPT_MAX = 4000


def _constantes(path):
    """Les constantes littérales de haut niveau d'un fichier Python, sans l'exécuter."""
    tree = ast.parse(path.read_text(), filename=str(path))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in WANTED:
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                continue
    return out


def _sur(path):
    """Le fichier ET ses dossiers jusqu'au dossier personnel : à l'utilisateur (ou root pour les dossiers),
    jamais modifiables par d'autres — sinon un tiers remplacerait le fichier après la vérification."""
    try:
        info = path.lstat()
    except OSError:
        return False
    if not path.is_file() or path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o022:
        return False
    home = Path.home().resolve()
    folder = path.parent
    while True:
        try:
            meta = folder.lstat()
        except OSError:
            return False
        # Un dossier collectif à bit collant (/tmp) n'est pas un risque : personne n'y renomme ce qui
        # n'est pas à lui.
        if folder.is_symlink() or meta.st_uid not in (os.getuid(), 0) \
                or (meta.st_mode & 0o022 and not meta.st_mode & 0o1000):
            return False
        if folder.resolve() == home or folder.parent == folder:
            return True
        folder = folder.parent


def portail():
    """{"path", "read_verbs", "write_verbs", "prompt"} si l'extension est là et saine, sinon None."""
    path = DIR / "portail.py"
    if not _sur(path):
        return None
    try:
        values = _constantes(path)
    except (OSError, SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return None
    read = values.get("READ_VERBS")
    write = values.get("WRITE_VERBS", ())
    prompt = values.get("PROMPT")
    if not (isinstance(read, tuple) and read and all(isinstance(v, str) and VERB.fullmatch(v) for v in read)):
        return None
    if not (isinstance(write, tuple) and all(isinstance(v, str) and VERB.fullmatch(v) for v in write)):
        return None
    if not (isinstance(prompt, str) and "{prefix}" in prompt and len(prompt) <= PROMPT_MAX):
        return None
    if set(read) & set(write):
        return None
    return {"path": path, "read_verbs": read, "write_verbs": write, "prompt": prompt}
