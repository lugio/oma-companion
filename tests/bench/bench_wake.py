"""Banc d'essai du mot d'éveil : fait passer chaque extrait dans le détecteur, par blocs de
4000 octets comme le service réel, et relève ce que chaque méthode aurait décidé.

    ~/.local/share/omarchy-companion/.venv/bin/python tests/bench/bench_wake.py
"""
import json
from pathlib import Path
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vosk import Model, KaldiRecognizer, SetLogLevel  # noqa: E402

SetLogLevel(-1)
CLIPS = Path(__file__).resolve().parent / "clips"
MODEL = Path.home() / ".local/share/omarchy-companion/models/vosk-model-small-fr-0.22"
PHRASE = "salut alison"


def run(model, path):
    grammar = KaldiRecognizer(model, 16000, json.dumps([PHRASE, "[unk]"]))
    grammar.SetWords(True)
    free = KaldiRecognizer(model, 16000)
    triggers, free_texts = [], []
    with wave.open(str(path)) as wav:
        data = wav.readframes(wav.getnframes())
    silence = b"\x00\x00" * 16000
    data += silence
    for i in range(0, len(data), 4000):
        block = data[i:i + 4000]
        if free.AcceptWaveform(block):
            free_texts.append(json.loads(free.Result()).get("text", ""))
        if grammar.AcceptWaveform(block):
            result = json.loads(grammar.Result())
            if result.get("text") == PHRASE:
                triggers.append([round(w["conf"], 2) for w in result.get("result", [])])
    free_texts.append(json.loads(free.FinalResult()).get("text", ""))
    return triggers, " | ".join(t for t in free_texts if t)


def main():
    model = Model(str(MODEL))
    for path in sorted(CLIPS.glob("*.wav")):
        triggers, heard = run(model, path)
        expected = path.name.startswith("wake")
        mark = "OK " if bool(triggers) == expected else "!! "
        print(f"{mark}{path.stem:24} déclenche={bool(triggers)!s:5} conf={triggers}  libre=«{heard}»")


if __name__ == "__main__":
    main()
