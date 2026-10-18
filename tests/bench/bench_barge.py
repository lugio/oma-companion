"""Banc de « couper la parole » : les mots d'arrêt tenus-ils sur du son, et les phrases d'Alison
qui contiennent le mot la coupent-elles par erreur ?

    ~/.local/share/omarchy-companion/.venv/bin/python tests/bench/bench_barge.py

Voix Piper (Siwis), 16 kHz mono comme le micro, en version proche et en version atténuée+bruitée
(« haut-parleurs »). Limite assumée, la même qu'au banc du mot d'éveil : une seule voix, de
synthèse ; le seuil se confirme en vrai.
"""
import json
from pathlib import Path
import sys
import wave

import numpy as np
from piper import PiperVoice, SynthesisConfig
from vosk import Model, KaldiRecognizer, SetLogLevel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import backend      # noqa: E402
import texts        # noqa: E402
import wakeword     # noqa: E402

SetLogLevel(-1)
VOICE = Path.home() / ".local/share/omarchy-companion/models/fr_FR-siwis-medium.onnx"
VOSK = Path.home() / ".local/share/omarchy-companion/models/vosk-model-small-fr-0.22"
OUT = Path(__file__).resolve().parent / "clips" / "barge"

# Ce qu'on dit pour la couper.
ORDERS = ["Stop.", "Arrête.", "Tais-toi.", "Stop !", "Arrête !"]
# Limite connue et assumée : la règle exige le mot SEUL. Deux mots d'affilée ne coupent pas.
LIMITS = ["Arrête, stop.", "Stop, tais-toi."]
# Ce qu'ELLE peut dire, et qui contient le mot : rien de tout ça ne doit la couper.
HERS = [
    "J'arrête le service et je le relance.",
    "Arrête-toi là, je m'en occupe.",
    "Le conteneur est stoppé depuis hier.",
    "Tu veux que j'arrête la sauvegarde ?",
    "Il n'y a pas de bouton stop sur cette page.",
    "Chut, je plaisante.",
]


def write(path, audio, rate, gain=1.0, noise=0.0):
    data = (audio.astype(np.float32) * gain)
    if noise:
        data = data + np.random.normal(0, noise * 3000, len(data))
    with wave.open(str(path), "wb") as handle:
        handle.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        handle.writeframes(np.clip(data, -32768, 32767).astype(np.int16).tobytes())


def clips():
    # Graine fixe : sans elle, le bruit des versions « haut-parleurs » change à chaque passage et
    # le compte bougeait d'un essai à l'autre — impossible de comparer deux versions du code.
    np.random.seed(1789)
    OUT.mkdir(parents=True, exist_ok=True)
    voice = PiperVoice.load(str(VOICE))
    made = []
    for kind, phrases in (("ordre", ORDERS), ("sienne", HERS), ("limite", LIMITS)):
        for index, phrase in enumerate(phrases):
            chunks = [np.frombuffer(c.audio_int16_bytes, dtype=np.int16)
                      for c in voice.synthesize(phrase, SynthesisConfig(length_scale=1.0))]
            audio = np.concatenate(chunks)
            rate = 22050
            # 22 050 → 16 000, comme le micro.
            index16 = (np.arange(int(len(audio) * 16000 / rate)) * rate / 16000).astype(int)
            audio = audio[np.clip(index16, 0, len(audio) - 1)]
            for label, gain, noise in (("proche", 1.0, 0.0), ("hp", 0.45, 0.12)):
                path = OUT / f"{kind}-{index:02d}-{label}.wav"
                write(path, audio, 16000, gain, noise)
                made.append((kind, phrase, label, path))
    return made


def listen(model, path, words):
    grammar = KaldiRecognizer(model, 16000, wakeword.grammar_json(words))
    detector = wakeword.WordDetector(grammar, words)
    with wave.open(str(path)) as handle:
        while True:
            block = handle.readframes(2000)
            if not block:
                break
            found = detector.feed(block)
            if found:
                return found
    final = wakeword.barge_decision(json.loads(grammar.FinalResult()), words)
    return final[0]


def main():
    made = clips()
    model = Model(str(VOSK))
    words = texts.barge_words("fr")
    # Deuxième verrou, côté moteur : quand la phrase qu'elle prononce contient elle-même un mot
    # d'arrêt, le micro ne l'écoute pas du tout (activity.json `mute`). Le banc le simule.
    risky = backend.Companion.risky
    engine = type("X", (), {"lang": lambda self: "fr", "BARGE_STEM": backend.Companion.BARGE_STEM})()
    coupe = manque = faux = ok = muet = 0
    for kind, phrase, label, path in made:
        found = listen(model, path, words)
        if kind == "ordre":
            if found:
                coupe += 1
            else:
                manque += 1
                print(f"  RATÉ   {label:6} {path.name} « {phrase} »")
        elif kind == "limite":
            if found:
                print(f"  (limite levée) {label:6} « {phrase} » → {found}")
        elif risky(engine, phrase):
            muet += 1
            if found:
                print(f"  (micro fermé sur cette phrase) {label:6} « {phrase} » → {found}")
        elif found:
            faux += 1
            print(f"  COUPÉE {label:6} {path.name} « {phrase} » → {found}")
        else:
            ok += 1
    print(f"\nOrdres entendus          : {coupe}/{coupe + manque}")
    print(f"Ses phrases sans piège   : {ok} laissées passer, {faux} l'auraient coupée à tort")
    print(f"Ses phrases à mot d'arrêt: {muet} — micro fermé par le moteur, jamais écoutées")


if __name__ == "__main__":
    main()
