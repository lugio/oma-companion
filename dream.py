"""Le rêve d'Alison : trois phases qui rangent sa mémoire, une fois par jour au plus.

Repris de `docs.openclaw.ai/concepts/dreaming`, à notre échelle (un utilisateur, une machine) :

- **light**  — relit les notes des jours passés, regroupe ce qui se répète, prépare des candidats.
               N'écrit JAMAIS au carnet.
- **REM**    — un seul appel de modèle, sans aucun outil : il met les candidats en phrases nettes et
               dégage les thèmes de la période. N'écrit JAMAIS au carnet.
- **deep**   — applique les portes (score, récurrence, diversité), refuse les secrets et les
               doublons, puis promeut. **Seule phase qui touche au carnet.**

Règles de sûreté, toutes reprises de la référence :
- rien n'est effacé : on ajoute, ou on remplace un souvenir devenu faux ;
- un rêve qui toucherait plus de MAX_LOSS du carnet est refusé en entier ;
- le carnet est sauvegardé avant écriture, et le dernier rêve s'annule ;
- un échec de phase arrête le rêve, il ne s'empile pas (OpenClaw a saturé 2 Go de mémoire en avril
  parce que le nettoyage d'un cycle échouait en silence) ;
- ce qui a déjà été rappelé n'est pas repromu : on ne réapprend pas ce qu'on sait.
"""
import datetime
import json
from pathlib import Path
import shutil

import memory
import notes
import recall
import storage

MIN_DAYS_BACK = 1          # on ne rêve jamais sur le jour courant
LOOK_BACK = 14             # profondeur d'un rêve, en jours
MAX_PROMOTIONS = 5         # au plus par rêve : un carnet se remplit lentement ou pas du tout
MAX_LOSS = 0.25            # refus si le rêve touchait plus d'un quart du carnet
MIN_SCORE = 0.18
MAX_CLUSTERS = 12          # ce qu'on montre au modèle, borné
MAX_LINES_PER_CLUSTER = 6
COOLDOWN = datetime.timedelta(hours=20)

# Poids d'OpenClaw, repris tels quels.
WEIGHTS = {"relevance": 0.30, "frequency": 0.24, "diversity": 0.15,
           "recency": 0.15, "consolidation": 0.10, "richness": 0.06}


# ---------------------------------------------------------------- phase claire

def stems(words_set):
    """Racines grossières (cinq lettres) : « régulation » et « régule » doivent se reconnaître.

    Ce n'est pas de la linguistique, juste de quoi éviter de réapprendre ce qu'on sait déjà.
    """
    return {word[:5] for word in words_set}


def clusters(notes_dir, today, look_back=LOOK_BACK):
    """Regroupe les lignes des jours passés autour des mots qui reviennent.

    Une phrase isolée n'est jamais un sujet : il faut qu'un mot (sa racine) revienne au moins deux
    fois. Grouper par « au moins deux mots communs » ne marchait pas — « je dois préparer l'AG
    d'Assemblo » et « on reparle de l'AG Assemblo » n'ont qu'un mot en commun, et c'est le bon.
    """
    hits = recall.load_hits(notes_dir)
    lines = []
    for path in notes.days(notes_dir):
        day = recall.day_of(path)
        if day is None or day > today - datetime.timedelta(days=MIN_DAYS_BACK):
            continue
        if (today - day).days > look_back:
            continue
        rows = recall.lines_of(path)
        for index, (clock, who, text) in enumerate(rows):
            if who != notes.SPEAKERS["user"]:
                continue                      # on part de ce que l'utilisateur dit, pas des réponses
            keys = recall.words(text)
            if not keys:
                continue
            counted = hits.get("%s %s" % (day.isoformat(), clock)) or {"n": 0, "q": []}
            lines.append({"date": day.isoformat(), "time": clock, "text": text,
                          "answer": rows[index + 1][2] if index + 1 < len(rows) else "",
                          "words": keys, "stems": stems(keys),
                          "n": int(counted.get("n", 0)), "q": len(counted.get("q", []))})

    # Index inversé racine → lignes ; un sujet = une racine citée dans au moins deux lignes.
    index = {}
    for line in lines:
        for stem in line["stems"]:
            index.setdefault(stem, []).append(line)
    groups, seen = [], set()
    for stem, found in sorted(index.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(found) < 2:
            continue
        signature = tuple(sorted(id(line) for line in found))
        if signature in seen:
            continue                          # deux mots qui désignent exactement le même sujet
        seen.add(signature)
        words = set()
        for line in found:
            words |= line["words"]
        groups.append({"words": words, "key": stem, "lines": found})
    return [scored(group, today) for group in groups]


def scored(group, today):
    """Les six signaux d'OpenClaw, bornés entre 0 et 1, puis pondérés."""
    lines = group["lines"]
    days = sorted({line["date"] for line in lines})
    age = (today - datetime.date.fromisoformat(days[-1])).days
    signals = {
        "relevance": min(1.0, sum(line["n"] for line in lines) / 3.0),
        "frequency": min(1.0, (len(days) - 1) / 2.0),
        "diversity": min(1.0, sum(line["q"] for line in lines) / 2.0),
        "recency": 0.5 ** (age / 14.0),
        "consolidation": min(1.0, (len(lines) - 1) / 4.0),
        "richness": min(1.0, len(group["words"]) / 12.0),
    }
    return {"words": group["words"], "key": group.get("key", ""), "lines": lines, "days": days, "signals": signals,
            "recalls": sum(line["n"] for line in lines),
            "queries": sum(line["q"] for line in lines),
            "score": round(sum(WEIGHTS[k] * v for k, v in signals.items()), 3)}


def gated(candidates, known=()):
    """Les trois portes : score, récurrence, diversité — plus « on ne réapprend pas ».

    Retourne (retenus, [(candidat, raison du refus)]).
    """
    known_words = [stems(recall.words(text)) for text in known]
    kept, refused = [], []
    for candidate in sorted(candidates, key=lambda c: -c["score"]):
        reason = ""
        if candidate["score"] < MIN_SCORE:
            reason = "score"
        elif len(candidate["lines"]) < 2 and candidate["recalls"] < 1:
            reason = "recurrence"
        elif len(candidate["days"]) < 2 and len(candidate["lines"]) < 2 and candidate["queries"] < 1:
            reason = "diversity"
        elif any(len(stems(candidate["words"]) & seen) >= max(2, len(seen) * 0.5) for seen in known_words):
            reason = "connu"
        (refused if reason else kept).append((candidate, reason) if reason else candidate)
    return kept[:MAX_CLUSTERS], refused


# ------------------------------------------------------------------ phase REM

PROMPT = """Tu ranges la mémoire d'un assistant de bureau. Voici des extraits de conversations entre \
l'utilisateur (« toi ») et l'assistante (« elle »), regroupés par sujet.

Rends UNIQUEMENT un tableau JSON, sans autre texte, d'au plus {max} objets :
{{"text": "...", "topic": "me|home|work|prefs|other", "replaces": "", "why": "..."}}

Règles absolues :
- N'INVENTE RIEN. Chaque phrase doit être appuyée par les extraits. Dans le doute, ne propose rien.
- Garde ce qui reste vrai demain : préférences de l'utilisateur, faits stables sur lui, sur sa maison
  ou son travail, et les ÉVÉNEMENTS DATÉS importants (« le 13/09/2026, migration faite ») — écris \
alors la date dans la phrase.
- Ne garde JAMAIS : l'avancement d'une tâche, un journal de travail, un TODO, une question sans
  réponse, un mot de passe, une clé, un jeton.
- Une phrase courte, à la troisième personne de l'utilisateur, 200 caractères au plus.
- "replaces" : recopie un extrait EXACT d'un souvenir existant que ta phrase rend faux, sinon "".
- "topic" : me = sur lui, home = sa maison, work = son travail, prefs = ses préférences, other = le reste.
- "why" : cinq mots maximum, pour le journal des rêves.

Souvenirs déjà connus (ne les répète pas) :
{known}

Extraits :
{extracts}
"""


def extracts(candidates):
    blocks = []
    for candidate in candidates:
        lines = []
        for line in candidate["lines"][:MAX_LINES_PER_CLUSTER]:
            lines.append("  %s — toi : %s" % (line["date"], line["text"]))
            if line["answer"]:
                lines.append("  %s — elle : %s" % (line["date"], line["answer"][:300]))
        blocks.append("- sujet (%d jour(s), %d rappel(s)) :\n" % (len(candidate["days"]), candidate["recalls"])
                      + "\n".join(lines))
    return "\n".join(blocks)


def compose(candidates, known, ask, max_items=MAX_PROMOTIONS):
    """Phase REM : un appel de modèle, sans outil. Retourne (propositions, texte brut)."""
    if not candidates:
        return [], ""
    prompt = PROMPT.format(max=max_items, known="\n".join("- " + text for text in known) or "(aucun)",
                           extracts=extracts(candidates))
    raw = ask(prompt) or ""
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end < start:
        return [], raw
    try:
        proposals = json.loads(raw[start:end + 1])
    except ValueError:
        return [], raw
    clean = []
    for item in proposals if isinstance(proposals, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        clean.append({"text": memory.clean(item["text"]),
                      "topic": item.get("topic") if item.get("topic") in memory.TOPICS else None,
                      "replaces": memory.clean(item.get("replaces") or ""),
                      "why": str(item.get("why") or "")[:60]})
    return clean[:max_items], raw


# --------------------------------------------------------------- phase profonde

def promote(memory_path, proposals, backup_dir):
    """Phase profonde : porte de sûreté, sauvegarde, puis écriture. Retourne le rapport."""
    before = memory.load(memory_path)
    touched = sum(1 for p in proposals if p["replaces"])
    if before and touched / len(before) > MAX_LOSS:
        # Règle d'OpenClaw : une consolidation qui remanierait plus d'un quart du carnet est refusée.
        return {"kept": [], "replaced": [], "rejected": [["tout le rêve", "trop de remaniement"]],
                "backup": ""}
    backup = ""
    if proposals:
        storage.private_dir(backup_dir)
        copy = backup_dir / ("carnet-%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        # Même un carnet vide est sauvegardé : « annuler ce rêve » doit toujours savoir quoi remettre.
        storage.private_write(copy, json.dumps(before, ensure_ascii=False, indent=1))
        backup = str(copy)
    kept, replaced, rejected = [], [], []
    for proposal in proposals:
        text = proposal["text"]
        if not text:
            continue
        if memory.looks_secret(text):
            rejected.append([text, "secret"])
            continue
        if proposal["replaces"]:
            fixed, reason = memory.edit(memory_path, proposal["replaces"], text=text, topic=proposal["topic"])
            if fixed:
                replaced.append([proposal["replaces"], text])
                continue
            if reason != "missing":
                rejected.append([text, reason])
                continue
            # Le souvenir visé n'existe plus : on retombe sur un simple ajout.
        item, reason = memory.remember(memory_path, text, source="dream", topic=proposal["topic"])
        if item:
            kept.append([text, proposal["why"]])
        else:
            rejected.append([text, reason])
    return {"kept": kept, "replaced": replaced, "rejected": rejected, "backup": backup}


# ------------------------------------------------------------------- le rêve

def last(state_dir):
    try:
        return json.loads((state_dir / "dreams" / "last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def due(state_dir, notes_dir, now=None):
    """Vrai s'il y a de quoi rêver : assez de temps passé et des notes plus récentes que le dernier rêve."""
    now = now or datetime.datetime.now()
    previous = last(state_dir)
    if previous.get("at"):
        try:
            if now - datetime.datetime.fromisoformat(previous["at"]) < COOLDOWN:
                return False
        except ValueError:
            pass
    since = previous.get("through", "")
    days = [recall.day_of(path) for path in notes.days(notes_dir)]
    yesterday = now.date() - datetime.timedelta(days=MIN_DAYS_BACK)
    return any(day and day <= yesterday and day.isoformat() > since for day in days)


def run(state_dir, memory_path, notes_dir, ask, now=None, look_back=LOOK_BACK):
    """Les trois phases. Retourne le rapport, écrit le journal des rêves, ne lève jamais."""
    now = now or datetime.datetime.now()
    today = now.date()
    report = {"at": now.isoformat(timespec="seconds"), "kept": [], "replaced": [], "rejected": [],
              "themes": "", "looked": 0, "candidates": 0, "backup": "", "through": ""}
    try:
        known = [item["text"] for item in memory.load(memory_path)]
        found = clusters(notes_dir, today, look_back)
        report["looked"] = len(found)
        kept, refused = gated(found, known)
        report["candidates"] = len(kept)
        report["rejected"] = [[" / ".join(sorted(c["words"])[:4]), reason] for c, reason in refused[:10]]
        proposals, raw = compose(kept, known, ask)
        report["themes"] = "" if proposals else raw[:200]
        written = promote(memory_path, proposals, state_dir / "dreams")
        report.update(written)
        report["rejected"] += written["rejected"]
        days = [d for candidate in found for d in candidate["days"]]
        report["through"] = max(days) if days else ""
    except Exception as trouble:        # un rêve qui échoue s'arrête, il ne s'empile pas
        report["error"] = str(trouble)[:200]
    save(state_dir, report)
    return report


def save(state_dir, report):
    folder = state_dir / "dreams"
    storage.private_dir(folder)
    storage.private_write(folder / "last.json", json.dumps(report, ensure_ascii=False, indent=1))
    lines = ["## %s" % report["at"],
             "%d sujet(s) relu(s), %d retenu(s) pour examen." % (report["looked"], report["candidates"])]
    lines += ["+ %s  (%s)" % (text, why) for text, why in report["kept"]]
    lines += ["~ %s  →  %s" % (old, new) for old, new in report["replaced"]]
    lines += ["- %s  (%s)" % (text, reason) for text, reason in report["rejected"][:10]]
    if report.get("error"):
        lines.append("! rêve interrompu : " + report["error"])
    storage.append_journal(state_dir / "dreams.md", "\n".join(lines) + "\n", "")


def undo(state_dir, memory_path):
    """Annule le dernier rêve : le carnet d'avant revient. Vrai si quelque chose a été remis."""
    previous = last(state_dir)
    backup = previous.get("backup")
    if not backup:
        return False
    source = Path(backup)
    if not source.exists():
        return False
    shutil.copy2(source, memory_path)
    memory_path.chmod(0o600)
    previous["undone"] = True
    storage.private_write(state_dir / "dreams" / "last.json", json.dumps(previous, ensure_ascii=False, indent=1))
    return True


if __name__ == "__main__":   # auto-vérification (sans modèle : `ask` est simulé)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        state = Path(d)
        notes_dir, carnet = state / "memory", state / "memory.json"
        for day in (12, 13, 15):
            when = datetime.datetime(2026, 9, day, 10, 0)
            notes.note(notes_dir, "user", "la régulation de la wallbox monte trop vite", when)
            notes.note(notes_dir, "assistant", "on limite à un ampère par minute", when)
        notes.note(notes_dir, "user", "il pleut sur la ville", datetime.datetime(2026, 9, 13, 11, 0))
        today = datetime.date(2026, 9, 18)

        found = clusters(notes_dir, today)
        assert any(len(c["days"]) == 3 for c in found), found
        kept, refused = gated(found)
        assert kept and kept[0]["score"] >= MIN_SCORE
        # Une phrase dite une seule fois n'est même pas un sujet : elle n'arrive jamais au modèle.
        assert not [c for c in found if "pleut" in c["words"]]
        # Un sujet d'un seul jour, mais remonté plusieurs fois par la MÊME question, passe la porte
        # de récurrence et tombe sur celle de la diversité.
        once = {"words": set("alpha beta gamma delta".split()),
                "lines": [{"date": "2026-09-17", "time": "10:00", "text": "x", "answer": "",
                           "words": set(), "n": 3, "q": 0}]}
        assert gated([scored(once, today)])[1][0][1] == "diversity"
        # Ce qu'elle sait déjà ne revient pas.
        assert not gated(found, ["la wallbox régule à un ampère par minute"])[0]

        answer = ('[{"text": "la wallbox monte d\'un ampère par minute", "topic": "home", '
                  '"replaces": "", "why": "revient souvent"}]')
        report = run(state, carnet, notes_dir, lambda _: answer, now=datetime.datetime(2026, 9, 18, 3, 0))
        assert report["kept"] and report["kept"][0][0].startswith("la wallbox"), report
        assert memory.load(carnet)[0]["source"] == "dream"
        assert "## 2026-09-18" in (state / "dreams.md").read_text()
        assert not due(state, notes_dir, datetime.datetime(2026, 9, 18, 4, 0))   # trop tôt
        assert undo(state, carnet) and memory.load(carnet) == []

        # Un modèle qui délire ou qui répond à côté ne casse rien.
        assert run(state, carnet, notes_dir, lambda _: "je ne sais pas",
                   now=datetime.datetime(2026, 9, 19, 3, 0))["kept"] == []
        # Un secret proposé est refusé.
        secret = '[{"text": "son mot de passe est toto", "topic": "me", "replaces": "", "why": "x"}]'
        out = run(state, carnet, notes_dir, lambda _: secret, now=datetime.datetime(2026, 9, 20, 3, 0))
        assert out["kept"] == [] and ["son mot de passe est toto", "secret"] in out["rejected"]
    print("dream ok")
