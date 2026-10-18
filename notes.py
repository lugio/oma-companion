"""Notes du jour d'Alison : la trace de ce qui s'est dit, un fichier par jour.

C'est la mémoire à court terme, sur le modèle d'OpenClaw (`memory/AAAA-MM-JJ.md`) : on écrit
tout, sans appeler le moindre modèle, et c'est le rêve qui ira y pêcher plus tard ce qui mérite
d'entrer au carnet. Rien n'est effacé : un fichier trop gros cesse simplement de grossir.

Dossier 700, fichiers 600, secrets expurgés comme dans le journal.
"""
import datetime
import re

import storage

DAY_MAX = 256 * 1024      # un jour très bavard ne mange pas le disque
LINE_MAX = 600            # une ligne de note, pas une dissertation
SPEAKERS = {"user": "toi", "assistant": "elle"}


def day_name(when=None):
    return (when or datetime.date.today()).strftime("%Y-%m-%d") + ".md"


def day_path(directory, when=None):
    return directory / day_name(when)


def days(directory):
    """Fichiers de notes existants, du plus ancien au plus récent."""
    try:
        return sorted(path for path in directory.iterdir()
                      if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", path.name))
    except OSError:
        return []


def note(directory, role, text, when=None):
    """Ajoute une ligne à la note du jour. Retourne la ligne écrite, ou "" si rien n'est écrit."""
    text = " ".join(str(text or "").split())
    if not text or role not in SPEAKERS:
        return ""
    now = when or datetime.datetime.now()
    path = day_path(directory, now.date())
    line = "- {} {} — {}".format(now.strftime("%H:%M"), SPEAKERS[role],
                                 storage.redact(text)[:LINE_MAX])
    storage.private_dir(directory)
    try:
        if path.exists() and path.stat().st_size > DAY_MAX:
            return ""
        before = path.read_text(encoding="utf-8") if path.exists() else "# " + now.strftime("%Y-%m-%d") + "\n\n"
    except OSError:
        return ""
    storage.private_write(path, before + line + "\n")
    return line


def forget(directory, written):
    """Retire des notes exactement les lignes `written` [(jour.md, ligne)] — celles qu'une conversation a
    écrites, rien d'autre (« Supprimer la conversation »). Un jour qui ne garde que son titre disparaît.
    → nombre de lignes retirées."""
    by_day = {}
    for day, line in written:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", str(day)) and line:
            by_day.setdefault(day, []).append(line)
    removed = 0
    for day, lines in by_day.items():
        path = directory / day
        try:
            if path.is_symlink():
                continue
            kept = path.read_text(encoding="utf-8").split("\n")
        except OSError:
            continue
        for line in lines:
            if line in kept:
                kept.remove(line)
                removed += 1
        body = [k for k in kept if k.strip() and not k.startswith("# ")]
        if body:
            storage.private_write(path, "\n".join(kept))
        else:
            path.unlink(missing_ok=True)
    return removed


def read_day(directory, when=None):
    try:
        return day_path(directory, when).read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":   # auto-vérification
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d) / "memory"
        moment = datetime.datetime(2026, 9, 18, 14, 32)
        assert note(directory, "user", "  on parle   de la wallbox ", moment).endswith("toi — on parle de la wallbox")
        assert note(directory, "assistant", "elle est en OCPP local", moment).startswith("- 14:32 elle — ")
        assert note(directory, "tool", "rien") == "" and note(directory, "user", "  ") == ""
        assert [p.name for p in days(directory)] == ["2026-09-18.md"]
        text = read_day(directory, moment.date())
        assert text.startswith("# 2026-09-18") and text.count("\n- ") == 2
        assert oct(day_path(directory, moment.date()).stat().st_mode & 0o777) == "0o600"
    print("notes ok")
