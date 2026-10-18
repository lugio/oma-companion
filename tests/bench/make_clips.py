"""Fabrique les extraits audio du banc d'essai du mot d'éveil et de la transcription.

Voix de synthèse Piper (Siwis), rééchantillonnée en 16 kHz mono comme le micro. Chaque phrase
existe en version proche et nette, et en version « télé » : atténuée et noyée dans un bruit
de fond. Limite assumée : une seule voix, synthétique ; les seuils se confirment ensuite en vrai.

    ~/.local/share/omarchy-companion/.venv/bin/python tests/bench/make_clips.py
"""
from pathlib import Path
import wave

import numpy as np
from piper import PiperVoice, SynthesisConfig

MODEL = Path.home() / ".local/share/omarchy-companion/models/fr_FR-siwis-medium.onnx"
OUT = Path(__file__).resolve().parent / "clips"

WAKE = ["Salut Alison.", "Salut Alison, allume le salon.", "Salut Alison !", "Salut, Alison."]
# Phrases de télé, dont des pièges proches du mot d'éveil.
TV = [
    "Salut à tous, et bienvenue dans l'émission.", "Salut les amis, on se retrouve après la pub.",
    "Alice et son chat sont rentrés tard.", "Ils ont chanté à l'unisson.", "Allez, salut, à demain !",
    "Salut Alain, tu viens ce soir ?", "C'est la saison des vendanges.", "Salut, c'est Lison au téléphone.",
    "Dans la description, je vais vous montrer cette page.", "Le match reprendra dans quelques instants.",
    "Il fera beau demain sur toute la région.", "Merci d'être restés avec nous ce soir.",
    "La recette demande trois œufs et du beurre.", "Nous allons maintenant passer aux informations.",
    "Il a signé un contrat avec le club de Lyon.", "Alors, salut la compagnie !",
]


def synth(voice, text, speed):
    chunks = list(voice.synthesize(text, syn_config=SynthesisConfig(length_scale=speed)))
    audio = np.concatenate([c.audio_float_array for c in chunks])
    rate = chunks[0].sample_rate
    t_old = np.arange(len(audio)) / rate
    t_new = np.arange(int(len(audio) * 16000 / rate)) / 16000
    return np.interp(t_new, t_old, audio)


def save(path, audio):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(pcm.tobytes())


def tv_version(audio, rng):
    """Voix lointaine : atténuée, un peu d'écho, bruit de fond à ~8 dB sous la voix."""
    far = audio * 0.25
    echo = np.zeros_like(far); delay = int(0.045 * 16000)
    echo[delay:] = far[:-delay] * 0.35
    far = far + echo
    noise = rng.normal(0, 1, len(far)); noise = np.convolve(noise, np.ones(8) / 8, mode="same")
    noise *= np.sqrt(np.mean(far ** 2)) / np.sqrt(np.mean(noise ** 2)) / (10 ** (8 / 20))
    return far + noise


def main():
    OUT.mkdir(exist_ok=True)
    voice = PiperVoice.load(str(MODEL))
    rng = np.random.default_rng(12)
    pad = np.zeros(int(0.8 * 16000))
    count = 0
    for group, phrases in (("wake", WAKE), ("tv", TV)):
        for i, text in enumerate(phrases):
            for speed in (0.9, 1.15):
                clean = np.concatenate([pad, synth(voice, text, speed), pad])
                save(OUT / f"{group}-{i:02d}-{speed}-proche.wav", clean)
                save(OUT / f"{group}-{i:02d}-{speed}-tele.wav", tv_version(clean, rng))
                count += 2
    (OUT / "phrases.txt").write_text("\n".join(f"wake-{i:02d}\t{t}" for i, t in enumerate(WAKE))
                                     + "\n" + "\n".join(f"tv-{i:02d}\t{t}" for i, t in enumerate(TV)) + "\n")
    print(f"{count} extraits écrits dans {OUT}")


if __name__ == "__main__":
    main()
