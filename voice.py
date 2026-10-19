#!/usr/bin/env python3
"""Serveur de voix persistant du Compagnon (tourne dans le venv, modèle Piper chargé une fois).

Protocole JSON-lines sur stdin / stdout :
  -> {"say": "texte", "id": 3, "target": "sortie"}   ajoute du texte à l'énoncé 3 (phrase par
                                 phrase) ; `target` = sortie de la voix, "" = celle du système
  -> {"end": 3}                  plus rien à venir pour l'énoncé 3
  -> {"stop": true}              coupe tout immédiatement (lecture et file d'attente)
  -> {"quit": true}
  <- {"event": "ready"}
  <- {"event": "start", "id": 3}     premier son joué
  <- {"event": "done", "id": 3}      énoncé entièrement joué
  <- {"event": "level", "value": 0.42}  volume de ce qui sort du haut-parleur, 20 fois par seconde
  <- {"event": "stopped"}
  <- {"event": "error", "text": ...}

Le son sort en flux brut vers pw-play : le premier mot part dès que la première
phrase est synthétisée, sans attendre la fin de la réponse.
"""
import array
import collections
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import texts

LANG = texts.lang_of({"language": os.environ.get("COMPANION_LANG", "fr")})
MODEL = Path(os.environ.get("COMPANION_TTS_MODEL",
                            str(Path.home() / ".local/share/omarchy-companion/models" / texts.VOICE[texts.base(LANG)]["tts"])))
lock = threading.Lock()
SLICE = 0.05       # tranche d'écriture et de mesure du volume, en secondes
LEAD = 0.25        # avance maximale du son écrit sur le son joué : garde le volume calé sur la voix
LATENCY = 0.08     # délai estimé entre l'écriture vers pw-play et la sortie du haut-parleur
LOUD = 9000        # RMS calé sur Piper Siwis (mesuré le 13/09 : médiane 0,45, 90e centile 0,85)


def emit(event, **data):
    with lock:
        print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def slice_levels(audio, rate):
    """Découpe un son brut s16 mono en tranches de SLICE secondes : [(octets, volume 0..1)]."""
    step = max(2, int(rate * SLICE) * 2)
    result = []
    for offset in range(0, len(audio), step):
        chunk = audio[offset:offset + step]
        samples = array.array("h", chunk[:len(chunk) // 2 * 2])
        rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))
        result.append((chunk, round(min(1.0, rms / LOUD), 3)))
    return result


class Speaker:
    def __init__(self):
        from piper import PiperVoice
        self.voice = PiperVoice.load(str(MODEL))
        self.jobs = queue.Queue()          # ("say", id, text) | ("end", id)
        self.player = None
        self.target = ""                    # sortie de la voix (réglage `sortie`), "" = celle du système
        self.current = None
        self.generation = 0
        self.started = False
        self.play_at = None                 # heure de sortie du prochain échantillon écrit
        self.levels = collections.deque()   # (heure de sortie, volume) à annoncer au panneau
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.announce_levels, daemon=True).start()

    def announce_levels(self):
        """Annonce le volume au moment où le son sort, pas quand il est écrit."""
        speaking = False
        while True:
            time.sleep(SLICE / 2)
            now, value = time.monotonic(), None
            while self.levels and self.levels[0][0] <= now:
                try:
                    value = self.levels.popleft()[1]
                except IndexError:
                    break
            if value is not None:
                emit("level", value=value)
                speaking = True
            elif speaking and not self.levels and (self.play_at is None or self.play_at <= now):
                emit("level", value=0.0)   # fin du son : bouche fermée
                speaking = False

    def write_audio(self, audio, generation):
        """Écrit le son par tranches, sans prendre plus de LEAD d'avance sur ce qui est joué."""
        rate = self.voice.config.sample_rate
        for chunk, level in slice_levels(audio, rate):
            if generation != self.generation:
                return False
            now = time.monotonic()
            if self.play_at is None or self.play_at < now:
                self.play_at = now + LATENCY   # tampon vide : ce son sortira après la latence
            # `stop()` (une coupure de parole) remet `play_at` à None depuis un autre fil, en plein
            # milieu de cette boucle : « unsupported operand type(s) for -: 'NoneType' and 'float' »
            # s'affichait en rouge dans le panneau (recette du 21/09). On lit une copie, et None
            # veut dire « coupé » : on rend la main sans bruit.
            while True:
                due = self.play_at
                if due is None or generation != self.generation:
                    return False
                if due - time.monotonic() <= LEAD:
                    break
                time.sleep(0.01)
            self.player.stdin.write(chunk)
            self.player.stdin.flush()
            due = self.play_at
            if due is None:
                return False
            self.levels.append((due, level))
            self.play_at = due + len(chunk) / 2 / rate
        return True

    def open_player(self):
        rate = self.voice.config.sample_rate
        target = ["--target", self.target] if self.target else []
        self.player = subprocess.Popen(["pw-play", "--raw", f"--rate={rate}", "--channels=1", "--format=s16"] + target + ["-"],
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close_player(self, wait):
        player, self.player = self.player, None
        if not player:
            return
        try:
            if wait:
                player.stdin.close()
                player.wait(timeout=120)
            else:
                player.kill()
                player.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                player.kill()
            except OSError:
                pass

    def worker(self):
        while True:
            kind, ident, text = self.jobs.get()
            generation = self.generation
            if kind == "say":
                if self.current != ident:
                    self.close_player(wait=True)
                    self.current, self.started = ident, False
                try:
                    for chunk in self.voice.synthesize(text):
                        if generation != self.generation:
                            break
                        if self.player is None:
                            self.open_player()
                        if not self.started:
                            self.started = True
                            emit("start", id=ident)
                        try:
                            if not self.write_audio(chunk.audio_int16_bytes, generation):
                                break
                        except (BrokenPipeError, OSError):
                            break
                except Exception as error:  # noqa: BLE001 — la voix ne doit jamais tuer le serveur
                    emit("error", text=str(error)[:200])
            elif kind == "end" and ident == self.current and generation == self.generation:
                self.close_player(wait=True)
                if generation == self.generation:
                    emit("done", id=ident)
                self.current = None
            elif kind == "end" and generation == self.generation:
                # Énoncé clos sans aucun texte prononçable : il est quand même terminé. Sans ce
                # « done », le Compagnon croirait la voix encore en cours et garderait le micro fermé.
                emit("done", id=ident)

    def stop(self):
        self.generation += 1
        while not self.jobs.empty():
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break
        self.close_player(wait=False)
        self.current = None
        self.levels.clear()
        self.play_at = None
        emit("level", value=0.0)
        emit("stopped")


def main():
    try:
        speaker = Speaker()
    except Exception as error:  # noqa: BLE001
        emit("error", text=texts.t(LANG, "err.voice_unavailable") + str(error)[:200])
        sys.exit(1)
    emit("ready")
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("quit"):
            speaker.stop()
            break
        if message.get("stop"):
            speaker.stop()
        elif "say" in message:
            # Vérifiée par le moteur (elle existe, sinon ""), appliquée à l'ouverture du prochain son.
            speaker.target = str(message.get("target") or "")
            speaker.jobs.put(("say", message.get("id", 0), str(message["say"])))
        elif "end" in message:
            speaker.jobs.put(("end", message["end"], None))


if __name__ == "__main__":
    main()
