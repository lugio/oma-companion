#!/usr/bin/env python3
"""Un rôle en appelle un autre : le garde remet la question dans un fichier privé à usage unique.

CLI : `delegue.py <rôle> --question-file <fichier-600>` ; les appelants de confiance peuvent aussi
transmettre la question par stdin avec `delegue.py <rôle>`. Aucun texte métier dans argv.

Le rôle actif (ou Alison elle-même) pose UNE question à un autre rôle installé et reçoit sa réponse,
à citer sous son nom. Un aller-retour, et rien d'autre :

- 🛑 une délégation ne dépasse jamais celui qui délègue : elle tourne au plus en LECTURE, avec les
  accès de lecture ouverts chez le déléguant ∩ permis au rôle appelé (backend.read_access) ;
- elle n'écrit rien, ne propose aucune action : aucune carte n'existe en Lecture, toute demande
  d'action est refusée d'office ;
- pas de chaîne : le cerveau appelé n'a pas cette commande, et la variable COMPANION_DELEGATED,
  héritée par tout ce qu'il lance, fait refuser un second niveau ;
- le rôle appelé répond avec son propre carnet (lu, jamais écrit) ;
- le journal garde « délégation X → Y : question ».

Un rôle restreint ses correspondants dans son role.json (`"delegate": [...]`, [] = personne) ;
l'interrupteur « délégation » des Réglages coupe tout.
"""
import os
import re
import stat
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def fail(message):
    print("Délégation : " + message, file=sys.stderr)
    sys.exit(1)


def read_question(argv, stream):
    """Jamais de question dans argv : elle arrive par stdin, bornée et non vide."""
    if len(argv) == 3 and argv[1] == "--question-file":
        path = Path(argv[2])
        if not re.fullmatch(r"claude-[A-Za-z0-9_-]+\.policy\.json-question-[A-Za-z0-9_-]+", path.name):
            raise ValueError("err.delegate_input")
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("err.delegate_input")
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 64000:
                    raise ValueError("err.delegate_input")
                with os.fdopen(descriptor, encoding="utf-8", closefd=False) as handle:
                    question = handle.read(16001)
            finally:
                os.close(descriptor)
                os.unlink(path.name, dir_fd=parent)
        finally:
            os.close(parent)
    elif len(argv) == 1:
        question = stream.read(16001)
    else:
        raise ValueError("err.delegate_input")
    if not question.strip() or len(question) > 16000:
        raise ValueError("err.delegate_input")
    return question.strip()


def main(argv):
    import backend, roles, texts, agents, memory, storage   # noqa: E401  (après sys.path)
    config = backend.settings()
    lang = texts.lang_of(config)
    if os.environ.get("COMPANION_DELEGATED"):
        fail(texts.t(lang, "err.delegate_chain"))
    try:
        question = read_question(argv, sys.stdin)
    except (OSError, UnicodeError, ValueError):
        fail(texts.t(lang, "err.delegate_input"))
    if not config.get("delegation", True):
        fail(texts.t(lang, "err.delegate_off"))
    asker = roles.current(config)
    name = roles.match(config, argv[0])
    target = roles.load(config, name) if name else None
    if not target:
        fail(texts.t(lang, "err.delegate_unknown", wanted=argv[0]))
    if asker and asker["name"] == target["name"]:
        fail(texts.t(lang, "err.delegate_self"))
    if not roles.may_delegate(asker, target["name"]):
        fail(texts.t(lang, "err.delegate_forbidden", asker=asker["label"], target=target["label"]))
    if backend.mode_of(config, asker) == "chat":
        fail(texts.t(lang, "err.delegate_chat"))
    mode = backend.delegation_mode(config, asker, target)
    asker_label = asker["label"] if asker else config["name"]
    access = backend.read_access(config, target) if mode == "read" else {"mail": False, "erp": False, "portail": False}
    prompt = backend.compose_delegated_prompt(config, target, access, asker_label)
    block = memory.prompt_block(memory.load(roles.state_dir(target, backend.STATE) / "memory.json"))
    storage.append_journal(backend.STATE / "journal.log",
                           texts.t(lang, "journal.delegation", asker=asker_label, target=target["label"],
                                   question=question[:120]), "securite/normal")
    os.environ["COMPANION_DELEGATED"] = "1"      # hérité par le cerveau appelé : pas de chaîne
    try:
        reply, _ = agents.run(agents.default_agent(), prompt, [], question, config.get("model", ""), {},
                              lambda _: None, lambda *a, **k: None,
                              on_permission=lambda request: {"behavior": "deny", "message": "Délégation : lecture seule."},
                              mode=mode, home=False, lang=lang, private=backend.protected_paths(config),
                              memory=block, mail=access["mail"], erp=access["erp"], portail=access["portail"],
                              role=target, delegate=False)
    except RuntimeError as trouble:
        fail(str(trouble)[:300])
    print(texts.t(lang, "reply.delegation", label=target["label"]))
    print(reply.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
