"""Compare l'ancienne règle (grammaire forcée seule) et la nouvelle (grammaire + confiance par mot),
sur les mêmes extraits, avec le temps de calcul de chaque méthode.

    ~/.local/share/omarchy-companion/.venv/bin/python tests/bench/bench_wake_rule.py          # extraits Piper
    ~/.local/share/omarchy-companion/.venv/bin/python tests/bench/bench_wake_rule.py boucle   # vrai son
"""
import json
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vosk import Model, KaldiRecognizer, SetLogLevel  # noqa: E402
import wakeword  # noqa: E402

SetLogLevel(-1)
CLIPS = Path(__file__).resolve().parent / "clips"
MODEL = Path.home() / ".local/share/omarchy-companion/models/vosk-model-small-fr-0.22"
PHRASE = "salut alison"


def blocks(path):
    with wave.open(str(path)) as wav:
        data = wav.readframes(wav.getnframes()) + b"\x00\x00" * 16000
    return [data[i:i + 4000] for i in range(0, len(data), 4000)]


def old_rule(model, chunks):
    rec = KaldiRecognizer(model, 16000, json.dumps([PHRASE, "[unk]"]))
    for block in chunks:
        if rec.AcceptWaveform(block) and json.loads(rec.Result()).get("text") == PHRASE:
            return True
    return False


def new_rule(model, chunks):
    detector = wakeword.WakeDetector(KaldiRecognizer(model, 16000, json.dumps([PHRASE, "[unk]"])), PHRASE)
    return any(detector.feed(block) for block in chunks)


def main():
    model = Model(str(MODEL))
    folder = CLIPS / sys.argv[1] if len(sys.argv) > 1 else CLIPS
    clips = sorted(folder.glob("*.wav"))
    table = {}
    for name, rule in (("ancienne", old_rule), ("nouvelle", new_rule)):
        started = time.process_time()
        false_wake = missed = 0
        for path in clips:
            fired = rule(model, blocks(path))
            expected = path.name.startswith("wake")
            if fired and not expected:
                false_wake += 1; print(f"  [{name}] faux réveil : {path.stem}")
            if expected and not fired:
                missed += 1; print(f"  [{name}] manqué : {path.stem}")
        table[name] = (false_wake, missed, time.process_time() - started)
    total_audio = sum(len(b) for p in clips for b in blocks(p)) / 32000
    wake = sum(p.name.startswith("wake") for p in clips)
    print(f"\n{len(clips)} extraits ({wake} avec le mot d'éveil, {len(clips) - wake} de télé), {total_audio:.0f} s d'audio")
    for name, (fw, mi, cpu) in table.items():
        print(f"{name:9} faux réveils {fw}/{len(clips) - wake}  manqués {mi}/{wake}  "
              f"calcul {cpu:.1f} s ({100 * cpu / total_audio:.0f} % d'un cœur)")


if __name__ == "__main__":
    main()
