"""Courrier d'Alison : lecture seule d'une boîte IMAP.

Utilitaire du plugin, sur le modèle de `ha.py` : le moteur et l'agent l'appellent, **le mot de passe
ne sort jamais d'ici**. Aucun verbe n'envoie, ne supprime, ne classe ni ne marque : ils n'existent
pas, et la boîte est ouverte en lecture seule côté serveur.

  python3 mail.py dossiers
  python3 mail.py liste [dossier] [nombre]
  python3 mail.py lire <dossier> <numéro>
  python3 mail.py chercher <mots…> [--dossier X]
  python3 mail.py tester

Identifiants, dans l'ordre :
1. `~/.local/state/omarchy-companion/mail.json` (600) — {"email", "password", "imap_host", "imap_port"} ;
2. `~/.local/state/omarchy-companion/mail-source.json` (600) — {"vault": "~/mon-coffre.json",
   "account": "section.clé"} : de quoi puiser dans un coffre déjà rempli, sans recopier le mot de
   passe ailleurs ; ou {"store": "keyring", "email", "imap_host", "imap_port"} : le mot de passe est
   dans le trousseau du système (trousseau.py). Écrit par le moteur d'après les réglages, jamais par l'agent.

Le chemin du coffre n'est PAS passé en variable d'environnement : l'agent hérite de l'environnement
du moteur, et `cat $UNE_VARIABLE` échapperait au garde, qui ne lit que le texte des commandes.
"""
import email
import email.header
import email.utils
import imaplib
import json
import texts
import os
import ssl
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trousseau  # noqa: E402

STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy-companion"
CREDENTIALS = STATE / "mail.json"          # identifiants saisis dans les Réglages
SOURCE = STATE / "mail-source.json"        # ou bien : où aller les chercher
BODY_MAX = 4000          # un corps de message plus long est coupé : on résume, on ne recopie pas
LIST_MAX = 25
TIMEOUT = 20
NEEDED = ("email", "password", "imap_host")


def credentials():
    """Les identifiants, ou {} si rien n'est configuré. Jamais affichés, jamais journalisés : dès qu'il
    est connu, le mot de passe est masqué dans tout ce que ce programme imprime."""
    found = _credentials()
    if found:
        trousseau.masquer_sorties(found.get("password"))
    return found


def _credentials():
    try:
        pointer = json.loads(SOURCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pointer = {}
    # Trousseau choisi : SEULE source (un ancien mail.json ne doit jamais repasser devant, revue Codex 18/10).
    if isinstance(pointer, dict) and pointer.get("store") == "keyring":
        data = {"email": str(pointer.get("email", "")), "imap_host": str(pointer.get("imap_host", "")),
                "imap_port": pointer.get("imap_port") or 993, "password": trousseau.lire("mail")}
        return data if all(data.get(k) for k in NEEDED) else {}
    try:
        vault, account = str(pointer.get("vault", "")), str(pointer.get("account", ""))
    except AttributeError:
        vault = account = ""
    # Ni trousseau ni coffre choisi : les identifiants saisis à l'ancienne (mail.json), en dernier recours.
    if not vault:
        try:
            data = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
            if all(data.get(key) for key in NEEDED):
                return data
        except (OSError, ValueError):
            pass
        return {}
    if not vault or "." not in account:
        return {}
    section, _, key = account.partition(".")
    try:
        data = json.loads(Path(vault).expanduser().read_text(encoding="utf-8"))[section][key]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return data if isinstance(data, dict) and all(data.get(k) for k in NEEDED) else {}


def connect():
    """Connexion IMAP SSL. Lève RuntimeError avec un message lisible, jamais le mot de passe."""
    account = credentials()
    if not account:
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.0"))
    host = str(account["imap_host"])
    port = int(account.get("imap_port") or 993)
    try:
        # imaplib ne vérifie ni le certificat ni le nom du serveur par défaut : contexte vérifiant
        # explicite, sinon un intermédiaire réseau recevrait le mot de passe (relecture du store, #12144).
        box = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
        box.login(str(account["email"]), str(account["password"]))
    except ssl.SSLCertVerificationError:
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.10", host=host))
    except imaplib.IMAP4.error:
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.4", host=host))
    except OSError as trouble:
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.5", host=host, reason=type(trouble).__name__))
    return box, account


def readable(raw):
    """En-tête MIME décodé en texte lisible."""
    if not raw:
        return ""
    parts = []
    for chunk, encoding in email.header.decode_header(str(raw)):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(encoding or "utf-8", "replace"))
        else:
            parts.append(chunk)
    return " ".join("".join(parts).split())


def folders(box):
    found = []
    ok, lines = box.list()
    if ok != "OK":
        return found
    for line in lines or []:
        match = re.search(r'"([^"]*)"\s*$|(\S+)\s*$', line.decode("utf-8", "replace"))
        name = (match.group(1) or match.group(2)) if match else ""
        if name and "\\Noselect" not in line.decode("utf-8", "replace"):
            found.append(name)
    return found


def when(message):
    stamp = email.utils.parsedate_to_datetime(message.get("Date")) if message.get("Date") else None
    return stamp.strftime("%d/%m %H:%M") if stamp else "?"


def attachments(message):
    """Noms des pièces jointes. On les signale, on ne les ouvre jamais."""
    names = []
    if message.is_multipart():
        for part in message.walk():
            name = part.get_filename()
            if name:
                names.append(readable(name)[:60])
    return names


def body(message):
    """Le texte du message, en clair. Le HTML est réduit à son texte : ni balise, ni image."""
    chosen, html = "", ""
    for part in (message.walk() if message.is_multipart() else [message]):
        kind = part.get_content_type()
        if part.get_filename() or kind not in ("text/plain", "text/html"):
            continue
        try:
            text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        except (AttributeError, LookupError, UnicodeError):
            continue
        if kind == "text/plain" and not chosen:
            chosen = text
        elif kind == "text/html" and not html:
            html = text
    if not chosen and html:
        chosen = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html))
        chosen = re.sub(r"&nbsp;?", " ", chosen)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in chosen.splitlines())).strip()


def headers(box, folder, count):
    """Les `count` derniers messages du dossier : (numéro, lu/non lu, de, objet, date, pièces)."""
    ok, info = box.select(f'"{folder}"', readonly=True)
    if ok != "OK":
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.folder", folder=folder))
    total = int(info[0] or 0)
    if not total:
        return []
    first = max(1, total - count + 1)
    ok, unseen = box.search(None, "UNSEEN")
    new = set((unseen[0] or b"").split()) if ok == "OK" else set()
    ok, data = box.fetch("%d:%d" % (first, total), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] FLAGS)")
    found = []
    for item in data or []:
        if not isinstance(item, tuple):
            continue
        number = re.match(rb"(\d+)", item[0]) and re.match(rb"(\d+)", item[0]).group(1)
        message = email.message_from_bytes(item[1])
        found.append({"n": int(number or 0), "unread": number in new,
                      "from": readable(message.get("From"))[:80],
                      "subject": readable(message.get("Subject"))[:120] or "(sans objet)",
                      "date": when(message)})
    found.reverse()
    return found


def show_list(box, folder, count):
    found = headers(box, folder, count)
    if not found:
        print("Dossier %s : aucun message." % folder)
        return
    unread = sum(1 for item in found if item["unread"])
    print("%s — %d message(s) affiché(s), %d non lu(s) :" % (folder, len(found), unread))
    for item in found:
        print("- [%d]%s %s — %s (%s)" % (item["n"], " NON LU" if item["unread"] else "",
                                         item["from"], item["subject"], item["date"]))


def show_message(box, folder, number):
    ok, _ = box.select(f'"{folder}"', readonly=True)
    if ok != "OK":
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.folder", folder=folder))
    ok, data = box.fetch(str(int(number)), "(BODY.PEEK[])")
    if ok != "OK" or not data or not isinstance(data[0], tuple):
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.message", number=number))
    message = email.message_from_bytes(data[0][1])
    text = body(message)
    joined = attachments(message)
    print("De : %s" % readable(message.get("From")))
    print("Objet : %s" % (readable(message.get("Subject")) or "(sans objet)"))
    print("Date : %s" % when(message))
    if joined:
        print("Pièces jointes (non ouvertes) : %s" % ", ".join(joined))
    print("---")
    print(text[:BODY_MAX] + ("\n[…] message coupé" if len(text) > BODY_MAX else ""))


def search(box, folder, words):
    ok, _ = box.select(f'"{folder}"', readonly=True)
    if ok != "OK":
        raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.folder", folder=folder))
    ok, data = box.search("UTF-8", "TEXT", '"%s"' % " ".join(words).replace('"', ""))
    numbers = (data[0] or b"").split()[-LIST_MAX:] if ok == "OK" else []
    if not numbers:
        print("Rien trouvé dans %s." % folder)
        return
    print("%d message(s) dans %s :" % (len(numbers), folder))
    for number in reversed(numbers):
        ok, item = box.fetch(number.decode(), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if ok != "OK" or not item or not isinstance(item[0], tuple):
            continue
        message = email.message_from_bytes(item[0][1])
        print("- [%s] %s — %s (%s)" % (number.decode(), readable(message.get("From"))[:60],
                                       readable(message.get("Subject"))[:100] or "(sans objet)", when(message)))


def main(argv):
    verb = argv[0] if argv else "liste"
    if verb in ("-h", "--help", "aide"):
        print(__doc__)
        return 0
    try:
        box, account = connect()
    except RuntimeError as trouble:
        print(str(trouble), file=sys.stderr)
        return 1
    try:
        if verb == "tester":
            names = folders(box)
            found = headers(box, "INBOX", 1)
            print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.connected",
                          email=account["email"], count=len(names)))
        elif verb == "dossiers":
            print("\n".join(folders(box)) or "(aucun)")
        elif verb == "liste":
            rest = [a for a in argv[1:] if a]
            count = int(rest[-1]) if rest and rest[-1].isdigit() else 5
            folder = rest[0] if rest and not rest[0].isdigit() else "INBOX"
            show_list(box, folder, min(count, LIST_MAX))
        elif verb == "lire":
            if len(argv) < 3:
                raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.read_usage"))
            show_message(box, argv[1], argv[2])
        elif verb == "chercher":
            words = [a for a in argv[1:] if not a.startswith("--")]
            folder = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--dossier=")), "INBOX")
            if not words:
                raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.search_usage"))
            search(box, folder, words)
        else:
            raise RuntimeError(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.verb", verb=verb))
    except (RuntimeError, ValueError) as trouble:
        print(str(trouble), file=sys.stderr)
        return 1
    except imaplib.IMAP4.error as trouble:
        print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.mail.server", reason=type(trouble).__name__), file=sys.stderr)
        return 1
    finally:
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
