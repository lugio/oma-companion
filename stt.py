#!/usr/bin/env python3
"""Serveur de transcription persistant du Compagnon (modèle chargé une fois).

Deux moteurs derrière le même protocole (spec 2026-10-09-transcription-parakeet.md) :
  parakeet  Parakeet TDT 0.6B v3 int8 par sherpa-onnx — PAR DÉFAUT. Mesuré le 09/10 sur la vraie voix
            de test : 0,20-0,39 s par commande, 0 faute (Whisper : 2,2-2,5 s, 3 fautes).
  whisper   faster-whisper `small` int8 — le REPLI, automatique si sherpa-onnx ou le modèle manque.
Choix : COMPANION_STT_ENGINE (réglage `sttEngine`). L'événement `ready` dit lequel tourne.

Protocole JSON-lines sur stdin / stdout :
  -> {"file": "/chemin/vers.wav", "id": 7}
  -> {"quit": true}
  <- {"event": "ready", "model": "parakeet-v3"}       (ou "small", ou "small (repli)")
  <- {"event": "text", "id": 7, "text": "…", "seconds": 1.9}
  <- {"event": "error", "id": 7, "text": "…"}

Whisper avait été choisi le 12/09 après mesure sur un portable de test (i5 4 cœurs, phrases françaises domotiques) :
  voxtype base   3,0 s/phrase, 11 % d'erreurs — transcriptions inutilisables
  voxtype small  8,5 s/phrase,  2 %           — trop lent
  faster-whisper small int8  2,2 s/phrase, 0 % — retenu (modèle gardé en mémoire)
"""
import json
import os
import wave
from pathlib import Path
import re
import sys
import time

import texts

# Langue de l'écoute : posée par le Compagnon au lancement (COMPANION_STT_LANG), français par défaut.
LANG = texts.lang_of({"language": os.environ.get("COMPANION_STT_LANG", "fr")})
MODEL = os.environ.get("COMPANION_STT_MODEL", "small")
# Commit fixé du modèle mesuré (Systran/faster-whisper-small) ; un autre modèle choisi à la main suit sa branche.
MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120" if MODEL == "small" else None
THREADS = int(os.environ.get("COMPANION_STT_THREADS", "4"))
ENGINE = os.environ.get("COMPANION_STT_ENGINE", "parakeet")
DATA = os.environ.get("COMPANION_DATA_HOME", os.path.expanduser("~/.local/share/omarchy-companion"))
PARAKEET = Path(DATA) / "models" / "parakeet-v3"     # posé par download_models.py, empreintes vérifiées
# Vocabulaire du contexte : pilotage de la maison et du bureau, par langue.
PROMPTS = {
    "fr": ("Assistant domotique en français. Allume, éteins, ouvre, ferme, monte, baisse, volet, "
           "lumière, interrupteur, prise, chauffage, couloir, salon, chambre, cuisine, entrée, bureau, "
           "terrasse, carport, Home Assistant, Omarchy, Hyprland, mode code, mode maison, conversation, "
           "Opus, Sonnet, Haiku, Fable, thème, volume, luminosité."),
    "en": ("Home assistant in English. Turn on, turn off, open, close, raise, lower, blind, light, "
           "switch, plug, heating, hallway, living room, bedroom, kitchen, entrance, office, terrace, "
           "carport, Home Assistant, Omarchy, Hyprland, code mode, home mode, conversation, "
           "Opus, Sonnet, Haiku, Fable, theme, volume, brightness."),
}
PROMPT = PROMPTS[LANG]


def emit(event, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


# Formules issues des sous-titres d'entraînement, que Whisper produit sur du silence ou un
# fond sonore. On ne retire QUE celles-là : tout le reste est de la parole réelle, même si
# elle ne s'adresse pas à l'assistant (on parle aussi à son chien devant le micro).
# Chaque candidat est déjà UNE phrase (découpée ci-dessous) : la formule court jusqu'au bout, point
# intérieur compris — « Sous-titres réalisés par la communauté d'Amara.org » passait à cause du « .org ».
NOISE = {
    "fr": re.compile(r"^\s*(sous-titr\w+[^!?]*|merci d'avoir regardé[^!?]*|abonnez-vous[^!?]*|"
                     r"amara\.org[^!?]*|♪+|\.{3,})\s*[.!…]?\s*$", re.IGNORECASE),
    "en": re.compile(r"^\s*(subtitles?\b[^!?]*|thanks? (you )?for watching[^!?]*|thank you\.?|"
                     r"(please )?(like|subscribe)[^!?]*|amara\.org[^!?]*|♪+|\.{3,})\s*[.!…]?\s*$", re.IGNORECASE),
}


def drop_noise(text, lang=None):
    """Retire les formules de sous-titrage inventées sur le silence. Rien d'autre."""
    pattern = NOISE.get(lang or LANG, NOISE["fr"])
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    kept = [p for p in parts if not pattern.match(p)]
    return " ".join(kept).strip()


# Réglages de transcription, partagés avec le banc d'essai (tests/bench/bench_stt_confidence.py).
# vad_filter : retire les silences avant transcription, ce qui évite que Whisper « comble » un
# blanc par une formule de sous-titre. `speech_pad_ms` garde une marge autour de la parole pour
# ne jamais rogner un début ou une fin de phrase.
# 🛑 `log_prob_threshold` et `temperature` décident du COÛT, pas seulement de la qualité : sous le
# seuil, faster-whisper recommence tout à température croissante, jusqu'à six passes. Mesuré le
# 20/09 sur le même extrait de 0,8 s : 6,32 s avec les six passes, 3,16 s avec trois, 1,81 s sans —
# et le texte rendu est le MÊME. Dans un journal réel, toutes les transcriptions lentes (6,4 s,
# 7,0 s, 9,85 s) ont un logprob sous −1,0 et toutes les rapides sont au-dessus : la corrélation est
# parfaite. Un logprob bas sur une phrase courte et murmurée est normal ici, il ne veut pas dire
# que le texte est faux. On garde le garde-fou qui compte vraiment — `compression_ratio_threshold`,
# qui attrape les boucles de répétition — et on borne le pire cas à trois passes.
TRANSCRIBE_OPTIONS = dict(language=LANG, beam_size=1, initial_prompt=PROMPT, vad_filter=True,
                          vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
                          condition_on_previous_text=False, no_speech_threshold=0.6,
                          compression_ratio_threshold=2.2, log_prob_threshold=-2.0,
                          temperature=[0.0, 0.2, 0.4])


def confidence(segments):
    """Confiance moyenne de Whisper, pondérée par la durée de chaque segment.

    `logprob` : log-probabilité moyenne des mots (0 = certain, -1 = très incertain).
    `no_speech` : probabilité que le segment ne soit pas de la parole.
    """
    total = sum(max(0.0, s.end - s.start) for s in segments)
    if not segments or total <= 0:
        return {"logprob": 0.0, "no_speech": 1.0}
    weight = lambda s: max(0.0, s.end - s.start) / total  # noqa: E731
    return {"logprob": round(sum(s.avg_logprob * weight(s) for s in segments), 3),
            "no_speech": round(sum(s.no_speech_prob * weight(s) for s in segments), 3)}


def load_whisper():
    """faster-whisper `small` : rend une fonction fichier -> (texte, détails du journal)."""
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=THREADS,
                         revision=MODEL_REVISION,  # commit fixé : jamais un autre modèle que celui mesuré
                         download_root=os.path.join(DATA, "models", "faster-whisper"))

    def transcribe(path):
        segments = list(model.transcribe(path, **TRANSCRIBE_OPTIONS)[0])
        return " ".join(segment.text for segment in segments).strip(), confidence(segments)
    return transcribe


def load_parakeet():
    """Parakeet v3 par sherpa-onnx. Pas d'indicateurs de confiance : ceux de Whisper ne servaient
    qu'au journal, qui écrit le nom du moteur à la place. Le silence rend "" (mesuré)."""
    import sherpa_onnx
    files = {name: PARAKEET / f"{name}.int8.onnx" for name in ("encoder", "decoder", "joiner")}
    if not all(path.is_file() for path in files.values()) or not (PARAKEET / "tokens.txt").is_file():
        raise FileNotFoundError(f"modèle Parakeet absent de {PARAKEET}")
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(files["encoder"]), decoder=str(files["decoder"]), joiner=str(files["joiner"]),
        tokens=str(PARAKEET / "tokens.txt"), num_threads=THREADS, model_type="nemo_transducer")

    def transcribe(path):
        import numpy
        with wave.open(path, "rb") as handle:
            rate, width, channels = handle.getframerate(), handle.getsampwidth(), handle.getnchannels()
            frames = handle.readframes(handle.getnframes())
        if width != 2:
            raise ValueError("son attendu en 16 bits")
        samples = numpy.frombuffer(frames, numpy.int16).astype(numpy.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        stream = recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip(), {"moteur": "parakeet"}
    return transcribe


def load():
    """Le moteur demandé, sinon l'autre : une Alison sans transcription n'est jamais une option."""
    order = (("parakeet", "parakeet-v3", load_parakeet), ("whisper", MODEL, load_whisper))
    if ENGINE == "whisper":
        order = order[::-1]
    failures = []
    for rank, (name, label, loader) in enumerate(order):
        try:
            return loader(), label + (" (repli)" if rank else "")
        except Exception as error:  # noqa: BLE001
            failures.append(f"{name} : {str(error)[:120]}")
    raise RuntimeError(" ; ".join(failures))


def main():
    try:
        transcribe, label = load()
    except Exception as error:  # noqa: BLE001
        emit("error", id=0, text=texts.t(LANG, "err.stt_unavailable") + str(error)[:200])
        sys.exit(1)
    emit("ready", model=label)
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("quit"):
            break
        path = message.get("file")
        ident = message.get("id", 0)
        if not path:
            continue
        try:
            started = time.monotonic()
            text, details = transcribe(path)
            emit("text", id=ident, text=drop_noise(text), seconds=round(time.monotonic() - started, 2), **details)
        except Exception as error:  # noqa: BLE001
            emit("error", id=ident, text=str(error)[:200])


if __name__ == "__main__":
    main()
