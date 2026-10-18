"""Écritures privées du Compagnon : fichiers en 600 dès leur création, journal expurgé et borné.

Partagé par le moteur, le mot d'éveil et le garde, qui écrivent tous dans le même journal.
"""
import os
from pathlib import Path
import re
import tempfile
import time

JOURNAL_MAX = 512 * 1024  # au-delà, le journal passe en journal.log.1 (un seul ancien gardé)

# Ce qui ressemble à un secret dans une commande journalisée : valeur après un mot-clé, jeton à
# préfixe connu, ou longue chaîne opaque mêlant majuscules, minuscules et chiffres.
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(bearer|token|api[_-]?key|secret|password|passwd|pwd|authorization)\b(\s*[:=]\s*|\s+)(\"[^\"]*\"|'[^']*'|\S+)")
SECRET_TOKEN = re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                          r"|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-.]+)")
OPAQUE = re.compile(r"\b(?=[A-Za-z0-9_\-]*[a-z])(?=[A-Za-z0-9_\-]*[A-Z])(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{24,}\b")


def redact(text):
    """Masque ce qui ressemble à un secret. Le journal est relu dans le panneau et copiable."""
    text = SECRET_ASSIGNMENT.sub(lambda m: m.group(1) + m.group(2) + "•••", str(text))
    text = SECRET_TOKEN.sub("•••", text)
    return OPAQUE.sub("•••", text)


def private_dir(path):
    """Dossier réservé à l'utilisateur, même s'il existait déjà avec des droits plus larges."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def private_write(path, text):
    """Écriture atomique en 600 : jamais un instant lisible par d'autres, jamais à moitié écrite."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def append_journal(path, line, tag=""):
    """Ajoute une ligne horodatée et expurgée au journal (600), avec rotation au-delà de 512 Ko.

    `tag` = « famille/aspect » (échange, voix, réveil, sécurité × message, normal, bruit, alerte) :
    le panneau classe la ligne sans lire son texte, quelle que soit la langue."""
    path = Path(path)
    private_dir(path.parent)
    try:
        if path.stat().st_size > JOURNAL_MAX:
            os.replace(path, path.with_name(path.name + ".1"))
    except FileNotFoundError:
        pass
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    clean = redact(line).replace("\n", " ⏎ ")
    label = f"[{tag}] " if tag else ""
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {label}{clean}\n")


def tail(path, lines=300, max_bytes=256 * 1024):
    """Dernières lignes du journal sans le relire en entier."""
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - max_bytes))
            data = handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    chunks = data.splitlines(keepends=True)
    if size > max_bytes and chunks:
        chunks = chunks[1:]  # première ligne probablement coupée
    return "".join(chunks[-lines:])
