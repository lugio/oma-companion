"""Combien de temps le micro reste-t-il ouvert, selon ce qui se passe dans la pièce ?

    python3 tests/bench/bench_ecoute.py

Rejoue la décision de fin d'écoute de `Companion.capture()` sur des scènes synthétiques, et compare
la règle d'avant le 19/09 (sans plafond) à celle d'aujourd'hui. Le niveau qui compte est le RMS d'un
bloc de 100 ms, comme dans le vrai code.

Mesure de référence : Whisper `small` int8 décode à **0,4× le temps réel** sur ce portable
(4 s d'audio en 1,6 s). Une écoute de 25 s, c'est donc 10 s d'attente avant la première réponse —
c'est ce qu'on voyait dans un journal réel le 19/09 au soir.
"""
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import backend  # noqa: E402

BLOCK = 0.1


def ecoute(blocs, plafond=None, abandon=8.0, end_silence=0.7, dur=None, dense=None):
    """Rejoue la décision. `plafond` = plafond souple, `dur` = plafond dur, `dense` = la densité
    de parole au-dessus de laquelle on considère qu'il parle encore vraiment."""
    floor, seen, speech, silence, began, recent = None, [], 0.0, 0.0, None, []
    for i, rms in enumerate(blocs):
        elapsed = (i + 1) * BLOCK
        threshold = 150 if floor is None else max(150, floor * 1.5)
        if floor is None:
            seen.append(rms)
            if elapsed >= 0.3:
                floor = sorted(seen)[len(seen) // 2]
        recent = recent[-29:] + [rms > threshold]
        if rms > threshold:
            speech += BLOCK
            silence = 0
            if began is None:
                began = elapsed
        else:
            silence += BLOCK
        trop_long = (plafond and began is not None and elapsed - began > plafond
                     and (dense is None or elapsed - began > (dur or plafond)
                          or sum(recent) / max(1, len(recent)) <= dense))
        if (speech > 0.25 and silence > end_silence) or (speech == 0 and elapsed > abandon) \
                or trop_long or elapsed > 60:
            return elapsed
    return len(blocs) * BLOCK


def scene(fond, voix, rafale=4000, densite=0.22, parole=3.0, apres=30.0, hp=0.0, graine=1):
    """`densite` = part des blocs où la pièce parle ; `hp` = secondes de SA voix encore audible."""
    r = random.Random(graine)
    bruit = lambda niveau: max(0.0, r.gauss(niveau, niveau * 0.35 + 8))
    vivant = lambda: bruit(rafale) if r.random() < densite else bruit(fond)
    out = [bruit(voix * 0.55) for _ in range(int(hp / BLOCK))]
    out += [vivant() for _ in range(int(0.4 / BLOCK))]
    out += [vivant() if k % 5 == 4 else bruit(voix) for k in range(int(parole / BLOCK))]
    out += [vivant() for _ in range(int(apres / BLOCK))]
    return out


CAS = [
    ("pièce calme", dict(fond=60, voix=5400, densite=0.0)),
    ("voix parasite discrète", dict(fond=60, voix=5400, rafale=1500)),
    ("télé à l'autre bout", dict(fond=90, voix=5400, rafale=3000)),
    ("quelqu'un parle à côté", dict(fond=120, voix=5200, rafale=5000)),
    ("conversation continue à côté", dict(fond=120, voix=5200, rafale=5000, densite=0.5)),
    ("sa voix dans les HP + télé", dict(fond=90, voix=5400, rafale=3000, hp=1.5)),
]


def main():
    plafond = backend.Companion.SPEECH_WINDOW
    print(f"Parole de 3 s → l'idéal est 4,1 s. Plafond en vigueur : {plafond:.0f} s.\n")
    print(f"{'ce qui se passe dans la pièce':32} {'avant':>15} {'aujourd’hui':>15}")
    print(f"{'':32} {'médiane  pire':>15} {'médiane  pire':>15}")
    for nom, kw in CAS:
        avant = [ecoute(scene(graine=g, **kw)) for g in range(12)]
        apres = [ecoute(scene(graine=g, **kw), plafond=plafond,
                        abandon=backend.Companion.SILENT_GIVEUP,
                        dur=backend.Companion.SPEECH_HARD,
                        dense=backend.Companion.SPEECH_DENSE) for g in range(12)]
        print(f"{nom:32} {statistics.median(avant):6.1f}s {max(avant):5.1f}s"
              f" {statistics.median(apres):6.1f}s {max(apres):5.1f}s")
    print("\nÀ multiplier par 0,4 pour l'attente ajoutée par la transcription.\n")
    # Le cas qui a fait relever le plafond : une VRAIE phrase longue, dans une pièce calme.
    longue = scene(fond=60, voix=5400, densite=0.0, parole=12.0)
    sec = ecoute(longue, plafond=plafond, abandon=backend.Companion.SILENT_GIVEUP,
                 dur=backend.Companion.SPEECH_HARD, dense=backend.Companion.SPEECH_DENSE)
    print(f"Sa propre phrase de 12 s, pièce calme : {sec:.1f}s enregistrées"
          + ("  ← COUPÉE" if sec < 12.5 else "  (entière)"))


if __name__ == "__main__":
    main()
