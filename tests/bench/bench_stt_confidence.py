"""Confiance de Whisper sur les voix proches et les voix « télé », mêmes réglages que stt.py.

Question : peut-on écarter une transcription de la pièce (télé, conversation lointaine) avant
de l'envoyer à Alison, sans jeter la parole de l'utilisateur ?

    ~/.local/share/omarchy-companion/.venv/bin/python tests/bench/bench_stt_confidence.py
"""
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import stt  # noqa: E402

CLIPS = Path(__file__).resolve().parent / "clips"


def main():
    from faster_whisper import WhisperModel
    model = WhisperModel(stt.MODEL, device="cpu", compute_type="int8", cpu_threads=stt.THREADS,
                         download_root=str(Path.home() / ".local/share/omarchy-companion/models/faster-whisper"))
    rows = {"proche": [], "tele": []}
    for path in sorted(CLIPS.glob("*.wav")):
        segments, _ = model.transcribe(str(path), **stt.TRANSCRIBE_OPTIONS)
        segments = list(segments)
        text = " ".join(s.text for s in segments).strip()
        score = stt.confidence(segments)
        kind = "tele" if path.stem.endswith("tele") else "proche"
        rows[kind].append(score["logprob"])
        print(f"{path.stem:24} logprob {score['logprob']:6.2f}  silence {score['no_speech']:.2f}  «{text[:60]}»")
    for kind, values in rows.items():
        print(f"\n{kind:6} min {min(values):.2f}  médiane {statistics.median(values):.2f}  max {max(values):.2f}")


if __name__ == "__main__":
    main()
