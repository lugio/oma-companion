"""Mot d'éveil français, traité en local. L'audio n'est jamais écrit ni envoyé.

Grammaire Vosk `[phrase, "[unk]"]` (≈ 1,6 % d'un cœur) + CONFIANCE PAR MOT : le réveil exige
les mots du mot d'éveil côte à côte, chacun avec une confiance ≥ MIN_CONFIDENCE. Sans ce seuil,
la grammaire ramenait des phrases de télé proches (« Salut à tous », « Salut Alain ») au mot
d'éveil. Mesures du 13/09/2026 dans tests/bench (extraits Piper et enregistrements passés par
les haut-parleurs et le micro du portable) : voir le message de commit.
Écartée après mesure : la confirmation par écoute libre, fiable sur du son propre mais qui
comprenait « salut à Dijon » ou « salaire amusant » sur du vrai son.
"""
import array
import json
import math
import os
from pathlib import Path
import select
import subprocess
import wave
import sys
import time
from backend import ROOT, SHELL_JSON, STATE, mic_argv, mic_is_clean, settings
import storage
import texts

# Confiance minimale de CHAQUE mot du mot d'éveil. Vrai « Salut Alison » : 1,0 partout (son
# synthétique et vrai son). Pièges : « Salut Alain » 0,74 (vrai son), « Salut les amis » 0,89.
MIN_CONFIDENCE = 0.95
# Couper la parole : un seuil un peu plus bas. Se tromper coûte peu (elle se tait alors qu'on ne
# l'a pas demandé, on relance), ne pas entendre coûte cher (on répète « stop » en haussant le ton).
BARGE_CONFIDENCE = 0.90
# Couper la parole SANS mot-clé : possible seulement avec un micro sans écho (réglage `micro`,
# PipeWire module-echo-cancel). Mesuré le 20/09 : la voix d'Alison y tombe à un niveau de 10 à 27
# (crête 380) alors qu'une voix de la pièce traverse intacte. Au-dessus de ce seuil pendant assez
# longtemps, ce n'est donc pas elle — c'est quelqu'un qui parle.
OPEN_LEVEL = 1200
# Durée de parole continue exigée. 0,35 s était trop long : mesuré le 20/09, « Non. »
# monte à 3788 (le bruit de la pièce est à 73, le seuil à 1200) mais ne dure que deux blocs — elle
# ne le coupait pas. Un mot court, c'est justement ce qu'on dit pour couper quelqu'un.
# Se tromper ne coûte rien : elle se tait, on reprend. Ne pas entendre coûte la conversation.
OPEN_VOICE = 0.2
# Ce qu'on garde de son (avant la coupure) pour le donner au moteur. C'est LE service qui entend
# la phrase qui coupe — c'est comme ça qu'il détecte — et le moteur n'ouvre son micro qu'après.
# Sans ce tampon, une interruption courte était perdue : elle se taisait, mais n'avait rien entendu
# (constaté le 20/09 à 00 h 55 : « voix 1121 » puis rien).
KEEP_SECONDS = 2.5
KEEP_BYTES = int(KEEP_SECONDS * 16000 * 2)


def hand_over(blocks):
    """Écrit les dernières secondes entendues dans un fichier que le moteur reprendra. Retourne son
    chemin, ou une chaîne vide."""
    try:
        path = STATE / "coupure.wav"
        storage.private_dir(STATE)
        with wave.open(str(path), "wb") as handle:
            handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            handle.writeframes(b"".join(blocks))
        path.chmod(0o600)
        return str(path)
    except (OSError, wave.Error):
        return ""


def level(block):
    """Niveau sonore d'un bloc de 16 bits mono, comme la capture du moteur."""
    samples = array.array("h", block[:len(block) // 2 * 2])
    return math.sqrt(sum(x * x for x in samples) / len(samples)) if samples else 0.0


def emit(event, **data):
    print(json.dumps({"event": event, **data}), flush=True)


def journal(line, look="normal"):
    """Trace dans le journal du Compagnon : chaque réveil, et chaque candidat écarté."""
    try:
        storage.append_journal(STATE / "journal.log", line, f"reveil/{look}")
    except OSError:
        pass


def wake_decision(result, phrase, min_confidence=MIN_CONFIDENCE):
    """À partir d'un résultat Vosk (avec `result` mot par mot), dit s'il faut se réveiller.

    Deux conditions : le mot d'éveil OUVRE ce que Vosk a entendu, et chacun de ses mots a une
    confiance ≥ min_confidence. Un vrai « Salut Alison » arrive toujours en tête (seul, ou suivi de
    la demande) ; les pièges qui passaient la confiance avaient un mot parasite devant
    (« salut salut alison », « [unk] salut alison »). Contrepartie : marquer une courte pause
    avant de dire le mot d'éveil.

    Renvoie (réveil, confiances des mots en tête, ou None si le mot d'éveil n'y est pas).
    """
    target = phrase.lower().split()
    spoken = [(w.get("word", ""), w.get("conf", 0.0)) for w in result.get("result", [])]
    head = spoken[:len(target)]
    if [word for word, _ in head] != target:
        return False, None
    confs = [round(conf, 2) for _, conf in head]
    return min(confs) >= min_confidence, confs


def drain(recorder):
    """Jette l'audio déjà dans le tuyau. Au changement de grammaire il contient la fin de ce qu'on
    ne voulait justement plus écouter — la fin de son annonce « dis valide ou non », par exemple,
    qui serait livrée telle quelle au détecteur de décision (audit du 19/09 au soir)."""
    while True:
        ready, _, _ = select.select([recorder.stdout], [], [], 0)
        if not ready or not recorder.stdout.read1(65536):
            return


def forms(entry):
    """L'écriture d'un mot composé pour la grammaire : trait d'union en espace.

    Mesuré le 19/09 : mettre les DEUX formes (« tais-toi » ET « tais toi ») fait perdre les deux —
    Vosk rend alors « tais » suivi d'un inconnu. Une seule forme, découpée, et le banc remonte de
    8 à 10 ordres sur 10. C'est aussi pour ça que « vas-y » n'est pas dans la liste : lui n'existe
    dans le lexique qu'avec son trait d'union."""
    return [entry.replace("-", " ")]


def grammar_json(entries):
    """Grammaire Vosk : du JSON NON échappé. `json.dumps` écrit « arr\\u00eate » par défaut, et Vosk
    répond « Ignoring word missing in vocabulary » — le mot n'entre jamais dans la grammaire, en
    silence (trouvé au banc du 19/09 : « arrête » n'était jamais entendu)."""
    words = [form for entry in entries for form in forms(entry)]
    return json.dumps(list(dict.fromkeys(words)) + ["[unk]"], ensure_ascii=False)


def breath(word):
    """Un « [unk] » de quelques centièmes : le souffle de fin d'un mot, pas une parole. Sans durée
    dans le résultat, on ne suppose rien et on le garde (plus strict)."""
    start, end = word.get("start"), word.get("end")
    return (word.get("word") == "[unk]" and start is not None and end is not None
            and end - start < 0.08)


def barge_decision(result, words, min_confidence=BARGE_CONFIDENCE):
    """Dit si ce que Vosk a entendu est un ordre d'arrêt — et lequel.

    Règle volontairement stricte : le mot d'arrêt doit être TOUT ce qui a été entendu. Pendant
    qu'Alison parle, le micro capte les haut-parleurs ; « j'arrête le service » ou « arrête-toi
    là » dans SA réponse la ferait se couper elle-même. Quelqu'un qui coupe la parole dit « stop »
    et s'arrête là — il n'enchaîne pas.

    Renvoie (mot d'arrêt, confiances) ou (None, confiances) .
    """
    # Un « [unk] » de trente millisecondes est un souffle de fin de mot, pas une parole : mesuré au
    # banc, « Arrête. » sort en [arrête, [unk] 29 ms] et l'égalité stricte le rejetait.
    spoken = [(w.get("word", ""), w.get("conf", 0.0)) for w in result.get("result", []) if not breath(w)]
    heard = [word for word, _ in spoken]
    confs = [round(conf, 2) for _, conf in spoken]
    for word in words:
        if not confs or min(confs) < min_confidence:
            continue
        if any(heard == form.lower().split() for form in forms(word.lower())):
            return word, confs
    return None, confs


class WakeDetector:
    """Alimenté bloc par bloc ; renvoie les confiances au moment du réveil, sinon None."""

    def __init__(self, grammar, phrase, on_rejected=lambda confs: None):
        grammar.SetWords(True)
        self.grammar = grammar
        self.phrase = phrase
        self.on_rejected = on_rejected

    def feed(self, block):
        if not self.grammar.AcceptWaveform(block):
            return None
        wake, confs = wake_decision(json.loads(self.grammar.Result()), self.phrase)
        if wake:
            return confs
        if confs is not None:
            self.on_rejected(confs)
        return None


class WordDetector:
    """Même micro, même modèle, autre grammaire : un mot de commande dit SEUL.

    Sert deux fois — les mots qui arrêtent sa parole, et ceux qui décident d'une carte.

    Deuxième verrou, mesuré au banc du 19/09 : la confiance ne sépare RIEN. « Arrête-toi là, je
    m'en occupe. » dite par Alison produit un second morceau entendu « stop » à 0,97, quand un vrai
    « tais-toi » ne monte qu'à 0,91. Ce qui les sépare, c'est ce qu'il y a AVANT : la voix d'Alison
    tombe en « [unk] » sauf quand elle prononce justement un de ces mots. Un morceau qui contient
    un mot d'arrêt sans être seulement lui, c'est elle qui parle — le morceau suivant ne compte pas.
    """

    def __init__(self, grammar, words):
        grammar.SetWords(True)
        self.grammar = grammar
        self.words = words
        self.vocabulary = {part for word in words for form in forms(word) for part in form.lower().split()}
        self.armed = True

    def hers(self, result, exact):
        """Ce morceau est de la parole d'Alison qui frôle un mot d'arrêt sans en être un.

        Il faut un mot d'arrêt ET autre chose autour : un morceau qui ne contient QUE des morceaux
        de la grammaire (« tais » puis « tais toi ») est un ordre en train d'être découpé, pas une
        phrase d'Alison — le désarmer faisait rater « Tais-toi » au banc.
        """
        heard = {w.get("word", "") for w in result.get("result", [])}
        return not exact and bool(heard & self.vocabulary) and bool(heard - self.vocabulary)

    def feed(self, block):
        if not self.grammar.AcceptWaveform(block):
            return None
        result = json.loads(self.grammar.Result())
        word, _ = barge_decision(result, self.words)
        armed, self.armed = self.armed, not self.hers(result, bool(word))
        return word if (word and armed) else None


class Watched:
    """Relit un fichier seulement quand sa date de modification change."""

    def __init__(self, path, loader, default):
        self.path = Path(path)
        self.loader = loader
        self.value = default
        self.stamp = None

    def get(self):
        try:
            stamp = os.stat(self.path).st_mtime_ns
        except FileNotFoundError:
            stamp = None
        if stamp != self.stamp:
            try:
                self.value = self.loader()
            except (OSError, ValueError, KeyError):
                return self.value   # lecture ratée : la date n'est pas notée, on réessaiera
            self.stamp = stamp
        return self.value


def spoke_again(state, barged_at):
    """Vrai si l'état « parle » a été publié APRÈS la dernière coupure : une nouvelle phrase, à
    couper si on parle par-dessus. Faux tant que c'est l'ancien état qui traîne."""
    return float((state or {}).get("time", 0) or 0) > barged_at


def main():
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    model = None
    model_lang = None
    recorder = None
    detector = None
    built = None       # (mode, phrase) du détecteur en place
    cooldown = 0       # repos du mot d'éveil seulement
    quiet = 0          # repos après une coupure ou une décision, tous modes confondus
    voice = 0.0        # parole continue entendue, en secondes (écoute ouverte)
    heard = 0.0        # niveau le plus fort entendu pendant qu'elle parlait (diagnostic)
    kept = []          # dernières secondes entendues, à donner au moteur quand il la coupe
    config = Watched(SHELL_JSON, settings, settings())
    activity = Watched(STATE / "activity.json", lambda: json.loads((STATE / "activity.json").read_text()), {})
    barged_at = 0.0
    try:
        while True:
            current = config.get()
            state = activity.get()
            # Un état périmé = un moteur mort ou bloqué : on retombe sur le mot d'éveil plutôt
            # que de rester sourd. « Parle » ne dure jamais trente secondes ; « réfléchit » peut
            # durer des minutes en mode Code, d'où deux délais.
            age = time.time() - state.get("time", 0) if state else 1e9
            engine = state.get("state", "idle") if state else "idle"
            fresh = age < (30 if engine == "speaking" else 240)
            if not fresh:
                engine = "idle"
            # Après une coupure, on ne recoupe pas tant que le moteur n'a pas REPUBLIÉ son état :
            # sinon un état « parle » resté à l'ancienne date faisait recouper à chaque son (six
            # fois en quatorze secondes le 21/09), et personne n'écoutait entre-temps.
            if engine == "speaking" and not spoke_again(state, barged_at):
                engine = "idle"
            # À quoi sert ce micro, selon ce que fait le moteur. AU REPOS : le mot d'éveil.
            # PENDANT QU'ELLE PARLE : les mots qui la coupent. UNE CARTE ATTEND : les mots qui
            # décident. QUAND ELLE RÉFLÉCHIT : rien à entendre, mais on GARDE le micro ouvert avec
            # la grammaire d'arrêt déjà en place — ouvrir pw-record au moment où elle commence à
            # parler prend plus de temps que ses réponses de deux secondes, et « stop » arrivait
            # toujours trop tard (constaté le 19/09).
            # Seul moment où on relâche vraiment : quand le MOTEUR enregistre, le micro est à lui
            # (et l'entendre parler la ferait se répondre à elle-même, régression du 12/09).
            # `mute` : le moteur prévient que la phrase en cours contient elle-même un mot d'arrêt
            # (« j'arrête le service ») — le micro l'entendrait et la couperait. Elle sait ce
            # qu'elle dit ; c'est plus sûr que n'importe quelle règle acoustique.
            # Un micro sans écho change tout : sa voix n'arrive plus au micro (mesuré : 73, le
            # bruit de la pièce). Les parades contre l'écho n'ont plus lieu d'être.
            clean = mic_is_clean(current)
            mode = "wake"
            release = False
            if engine == "waiting" and current.get("voiceDecide", False):
                mode = "decide"
            elif engine in ("speaking", "thinking", "acting"):
                # `mute` (sa phrase contient un mot d'arrêt) ne vaut QUE sur un micro brut : là,
                # elle s'entendrait le prononcer. Avec l'annulation d'écho, ce verrou l'a rendue
                # ininterruptible pile quand elle expliquait comment l'interrompre (20/09, 00 h 52).
                if current.get("barge", True) and (clean or not (fresh and state.get("mute"))):
                    mode = "barge"
                else:
                    # Elle parle et on n'a PAS à l'écouter : on ferme le micro. Retomber sur le mot
                    # d'éveil le laissait ouvert alors que la documentation promettait l'inverse
                    # (audit du 19/09 au soir).
                    release = True
            engine_has_mic = engine in ("listening", "transcribing")
            active = current["wakeword"] and not engine_has_mic and not release
            # Deux repos : celui du mot d'éveil (huit secondes, pour ne pas se re-déclencher) ne
            # doit pas rendre sourd à « stop » ; celui d'après une coupure ou une décision vaut
            # pour tout le monde, sinon un mot répété décidait de deux cartes d'affilée.
            if not active or time.monotonic() < quiet \
                    or (mode == "wake" and time.monotonic() < cooldown):
                if recorder:
                    recorder.terminate(); recorder.wait(timeout=3); recorder = None
                    built = None
                    emit("listening", value=False)
                time.sleep(0.4)
                continue
            lang = texts.lang_of(current)
            if model is None or model_lang != lang:
                # Un modèle par langue ; changer de langue dans les Réglages recharge le bon.
                model, model_lang = Model(str(ROOT / "models" / texts.VOICE[texts.base(lang)]["vosk"])), lang
                if recorder:
                    recorder.terminate(); recorder.wait(timeout=3); recorder = None
                built = None
            phrase = texts.wake_phrase(current)
            if built != (mode, phrase):
                # Changer de grammaire ne coupe PAS le micro : passer du mot d'éveil aux mots
                # d'arrêt arrive à chaque phrase qu'elle prononce, on ne va pas rouvrir pw-record
                # à chaque fois.
                built = (mode, phrase)
                if recorder:
                    drain(recorder)
                if mode in ("barge", "decide"):
                    words = (texts.barge_words(lang) if mode == "barge"
                             else texts.decision_words(lang)[0] + texts.decision_words(lang)[1])
                    detector = WordDetector(KaldiRecognizer(model, 16000, grammar_json(words)), words)
                else:
                    detector = WakeDetector(
                        KaldiRecognizer(model, 16000, grammar_json([phrase])), phrase,
                        on_rejected=lambda confs: journal(texts.t(lang, "journal.wake_rejected", confs=confs), "bruit"))
            if not recorder:
                recorder = subprocess.Popen(["pw-record", "--raw", "--rate=16000", "--channels=1", "--format=s16"]
                                            + mic_argv(current) + ["-"],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                emit("listening", value=True)
            ready, _, _ = select.select([recorder.stdout], [], [], 0.5)
            if not ready:
                continue
            data = recorder.stdout.read1(4000)
            if not data:
                recorder.wait(); recorder = None
                emit("error", text=texts.t(lang, "err.wake_mic"))
                cooldown = time.monotonic() + 10
                continue
            # Micro sans écho + elle parle : plus besoin de mot-clé. Tout ce qui dépasse le
            # niveau, c'est quelqu'un — sa voix à elle a été soustraite du signal.
            if mode == "barge" and engine == "speaking" and clean:
                rms = level(data)
                heard = max(heard, rms)
                kept.append(data)
                while sum(len(b) for b in kept) > KEEP_BYTES:
                    kept.pop(0)
                # La vraie durée du bloc : `read1` peut en rendre moins que demandé, et un bloc
                # plein fait 0,125 s, pas 0,1 — compter faux rallongeait encore l'exigence.
                voice = voice + len(data) / 2 / 16000 if rms > OPEN_LEVEL else 0.0
                if voice >= OPEN_VOICE:
                    voice = 0.0
                    journal(texts.t(lang, "journal.barge", word="parole"), "normal")
                    emit("barge", word="", file=hand_over(kept))
                    kept = []
                    barged_at = time.time()
                    quiet = time.monotonic() + 2
                continue
            if heard and engine != "speaking":
                # Diagnostic : ce que le micro a entendu de plus fort pendant qu'elle parlait.
                # Sans ce chiffre, « elle ne m'entend pas » ne se distingue pas de « le seuil est
                # trop haut » ni de « le service n'écoutait pas ».
                journal(texts.t(lang, "journal.barge_level", level=round(heard), seuil=OPEN_LEVEL), "bruit")
                heard = 0.0
            found = detector.feed(data)
            # « Stop » pendant qu'elle réfléchit : rien à couper. Le moteur l'ignorerait de toute
            # façon, on ne l'envoie même pas.
            if found and mode == "barge" and engine != "speaking":
                found = None
            if found and mode == "decide":
                allow = found in texts.decision_words(lang)[0]
                journal(texts.t(lang, "journal.voice_decision", word=found), "normal")
                emit("decide", value="allow" if allow else "deny", word=found, card=int(state.get("card", 0) or 0))
                quiet = time.monotonic() + 2
            elif found and mode == "barge":
                journal(texts.t(lang, "journal.barge", word=found), "normal")
                emit("barge", word=found)
                barged_at = time.time()
                quiet = time.monotonic() + 2
            elif found:
                journal(texts.t(lang, "journal.wake", confs=found))
                emit("wake")
                cooldown = time.monotonic() + 8
    finally:
        if recorder:
            recorder.terminate(); recorder.wait(timeout=3)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit("error", text=str(error))
        sys.exit(1)
