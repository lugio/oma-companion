#!/usr/bin/env python3
"""Les sons de la pièce, entendus par le micro du robot (11/10/2026) — d'abord : les aboiements.

YAMNet (Google, AudioSet, 521 sons, licence Apache-2.0) par le classificateur audio officiel de MediaPipe
(déjà installé pour les gestes). Mesuré sur la machine de test le 11/10 : ~18 ms de calcul par seconde de son.
Une fenêtre d'une seconde à la fois, rien n'est enregistré ni gardé : seuls les scores servent.

FACULTATIF : rien ne tourne sans `Sons(...).start()`. Le corps décide quoi faire d'un aboiement
(`on_bark(nombre, score)`) — sur la machine du robot : par exemple un événement Home Assistant.
"""
import hashlib
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/audio_classifier/yamnet/float32/1/yamnet.tflite"
MODEL_SHA256 = "4d8b4a53282dc83ef04e3e7dbc4fbc98082e34e44ed798e16c3a0cdd4c584faf"
MODEL = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "reachy-vue" / "yamnet.tflite"
RATE = 16000
DOG = {"Dog", "Bark", "Bow-wow", "Yip", "Howl", "Growling", "Whimper (dog)"}   # les sons de chien d'AudioSet
BARK_SCORE = 0.4            # score minimal d'un son de chien dans une fenêtre d'une seconde
BARK_WINDOW = 300.0         # secondes : on compte les aboiements des 5 dernières minutes
REPORT_EVERY = 60.0         # secondes entre deux signalements


def model_path():
    """YAMNet, téléchargé une fois, vérifié par son empreinte complète."""
    if not MODEL.is_file():
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        temporary = MODEL.with_suffix(".tmp")
        with urllib.request.urlopen(MODEL_URL, timeout=60) as answer:
            temporary.write_bytes(answer.read())
        temporary.replace(MODEL)
    if hashlib.sha256(MODEL.read_bytes()).hexdigest() != MODEL_SHA256:
        MODEL.unlink(missing_ok=True)
        raise RuntimeError("modèle YAMNet altéré : effacé, il sera retéléchargé")
    return str(MODEL)


def dog_score(categories):
    """Le meilleur score d'un son de chien parmi [(nom, score), …]. Pure, testable."""
    return max((score for name, score in categories if name in DOG), default=0.0)


class Barks:
    """Compte les aboiements récents et dit quand les signaler (au plus une fois par REPORT_EVERY). Pur."""

    def __init__(self):
        self.times, self.reported = [], -1e9

    def hear(self, score, now):
        """Une seconde de son → (nombre d'aboiements sur BARK_WINDOW, faut-il le signaler maintenant ?)."""
        if score >= BARK_SCORE:
            self.times.append(now)
        self.times = [t for t in self.times if now - t <= BARK_WINDOW]
        report = score >= BARK_SCORE and now - self.reported >= REPORT_EVERY
        if report:
            self.reported = now
        return len(self.times), report


class Sons:
    """Un fil qui lit le micro (`parecord`, 16 kHz mono) et classe chaque seconde de son avec YAMNet."""

    def __init__(self, device, on_bark=lambda count, score: None, on_note=lambda text: None):
        self.device, self.on_bark, self.on_note = device, on_bark, on_note
        self.barks = Barks()
        self.running = False
        self.error = ""

    def start(self):
        self.running = True
        threading.Thread(target=self.loop, daemon=True).start()
        return self

    def stop(self):
        self.running = False

    def loop(self):
        try:
            import numpy as np
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import audio
            from mediapipe.tasks.python.components.containers import audio_data
            classifier = audio.AudioClassifier.create_from_options(audio.AudioClassifierOptions(
                base_options=mpt.BaseOptions(model_asset_path=model_path()), max_results=10))
        except Exception as trouble:          # MediaPipe ou le modèle absents : pas d'écoute, le reste marche
            self.error = f"sons indisponibles : {str(trouble)[:120]}"
            self.on_note(self.error)
            return
        size = RATE * 2                       # une seconde, 16 bits
        while self.running:
            try:
                proc = subprocess.Popen(["parecord", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le",
                                         f"--device={self.device}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                while self.running:
                    data = proc.stdout.read(size)
                    if len(data) < size:
                        break
                    x = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
                    result = classifier.classify(audio_data.AudioData.create_from_array(x, RATE))
                    cats = [(c.category_name, c.score) for r in result for c in r.classifications[0].categories]
                    score = dog_score(cats)
                    count, report = self.barks.hear(score, time.monotonic())
                    if report:
                        self.on_bark(count, score)
                proc.kill()
            except OSError as trouble:
                self.error = f"micro : {trouble}"
            time.sleep(5)
