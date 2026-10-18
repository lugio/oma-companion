"""Textes du moteur, en français et en anglais. La langue vient du réglage `language`.

Chaque clé existe dans les deux langues (vérifié par les tests). `t(lang, clé, **valeurs)` ;
une langue inconnue retombe sur le français. Le panneau a son propre catalogue (I18n.js), avec les
mêmes règles. Les messages destinés à l'AGENT (refus, contexte) restent en français : il les lit,
l'utilisateur non.
"""
import json
import os
from pathlib import Path
import re

LANGUAGES = ("fr", "en")      # remplacé au chargement des fichiers de langue (load_languages)

# Modèles de voix par langue : synthèse Piper, mot d'éveil Vosk, phrase d'éveil par défaut.
VOICE = {
    "fr": {"tts": "fr_FR-siwis-medium.onnx", "vosk": "vosk-model-small-fr-0.22", "wake": "salut alison"},
    "en": {"tts": "en_US-lessac-medium.onnx", "vosk": "vosk-model-small-en-us-0.15", "wake": "hey alison"},
}

# Réponse de l'agent qui signifie « ce n'était pas pour moi » (les deux langues sont toujours acceptées).
IGNORE_MARKERS = ("[ignoré]", "[ignore]", "[ignored]")

# Ce qui peut entourer une commande dite à la voix, sans la changer : l'appel, la politesse.
# Le reste doit être la commande et rien d'autre — « explique-moi le mode code d'Omarchy » a
# basculé en mode Code pendant l'audit du 19/09, coffre ouvert compris.
COMMAND_LEAD = {
    "fr": r"^(?:(?:hey|ok|salut|dis)\s+)?(?:{name}[,!:]?\s+)?(?:s'il te pla[îi]t\s+)?(?:tu peux\s+)?",
    "en": r"^(?:(?:hey|ok|hi)\s+)?(?:{name}[,!:]?\s+)?(?:please\s+)?(?:can you\s+)?",
}
COMMAND_TAIL = {
    "fr": r"(?:\s+(?:s'il te pla[îi]t|stp|maintenant))?[\s.!?]*$",
    "en": r"(?:\s+(?:please|now))?[\s.!?]*$",
}


def lead(lang="fr", name="Alison"):
    """Ce qui peut précéder une commande sans en faire partie : « salut », son nom, « tu peux »."""
    return COMMAND_LEAD[base(lang)].replace("{name}", re.escape(name.casefold()))


def whole_phrase(pattern, lang="fr", name="Alison"):
    """Le motif, mais seulement s'il couvre TOUTE la phrase (appel et politesse mis à part).

    🛑 C'est LA règle qui a coûté le plus cher (« explique-moi le mode code » basculait en mode
    Code, coffre ouvert ; « ouvre la page Wikipedia sur Paris » était avalée par le raccourci
    « ouvre le lien »). Elle était écrite de cinq façons différentes selon la grammaire, dont une
    qui ne l'écrivait pas du tout — « fais un rêve de code propre, dis-moi comment tu
    refactoriserais » déclenchait le vrai rêve (audit du 20/09). Toutes les grammaires passent
    désormais par ici. La seule exception est la mémoire, qui doit au contraire capturer la fin de
    la phrase (« retiens que… ») : elle réutilise `lead()` et s'arrête là.
    """
    return lead(lang, name) + "(?:" + pattern + ")" + COMMAND_TAIL[base(lang)]


# Commandes méta à la voix ou au clavier : (motif, clé de réglage, valeur, clé de confirmation).
# Un motif doit couvrir TOUTE la phrase (voir `whole_phrase`) : il décrit donc la commande
# entière, verbe compris, et pas seulement les deux mots qui la caractérisent.
SWITCH = r"(?:(?:passe|mets[- ]toi|va|bascule|reviens) en\s+|active le\s+|mets le\s+)?"
SWITCH_EN = r"(?:(?:switch|go|come back) to\s+|enable\s+|turn on\s+)?(?:the\s+)?"
CONTROL = {
    "fr": [
        (SWITCH + r"mode\s+code", "mode", "code", "reply.mode_code"),
        (SWITCH + r"mode\s+(?:assistant|normal|simple)", "mode", "assistant", "reply.mode_assistant"),
        (SWITCH + r"mode\s+(?:discussion|bavardage)", "mode", "chat", "reply.mode_chat"),
        (SWITCH + r"mode\s+lecture", "mode", "read", "reply.mode_read"),
        # Reconnu pour être REFUSÉ (backend.intercept_control) : sinon la phrase partait à l'agent.
        (SWITCH + r"mode\s+autonome", "mode", "auto", "reply.mode_auto_click"),
        (r"(?:active|lance|d[ée]marre|passe en|ouvre)\s+(?:le\s+|l['’]\s*)?(?:mode\s+|acc[èe]s\s+)?(?:maison|ha|home\s*assistant)",
         "home", True, "reply.home_on"),
        (r"(?:d[ée]sactive|coupe|quitte|arr[êe]te|ferme)\s+(?:le\s+|l['’]\s*)?(?:mode\s+|acc[èe]s\s+)?(?:maison|ha|home\s*assistant)",
         "home", False, "reply.home_off"),
        (r"(?:active|lance|passe en|d[ée]marre)\s+(?:la\s+|le\s+)?(?:mode\s+)?conversation",
         "conversation", True, "reply.conv_on"),
        (r"(?:d[ée]sactive|coupe|arr[êe]te|quitte)\s+(?:la\s+|le\s+)?(?:mode\s+)?conversation",
         "conversation", False, "reply.conv_off"),
        (r"(?:active|mets|remets)\s+(?:la\s+)?voix", "voice", True, "reply.voice_on"),
        (r"(?:d[ée]sactive|coupe|enl[èe]ve)\s+(?:la\s+)?voix", "voice", False, "reply.voice_off"),
        (r"(?:utilise|passe (?:sur|[àa])|prends|mod[èe]le)\s+(?:le\s+)?(?:mod[èe]le\s+)?(?:claude\s+)?fable",
         "model", "fable", "reply.model"),
        (r"(?:utilise|passe (?:sur|[àa])|prends|mod[èe]le)\s+(?:le\s+)?(?:mod[èe]le\s+)?(?:claude\s+)?opus",
         "model", "opus", "reply.model"),
        (r"(?:utilise|passe (?:sur|[àa])|prends|mod[èe]le)\s+(?:le\s+)?(?:mod[èe]le\s+)?(?:claude\s+)?sonnet",
         "model", "sonnet", "reply.model"),
        (r"(?:utilise|passe (?:sur|[àa])|prends|mod[èe]le)\s+(?:le\s+)?(?:mod[èe]le\s+)?(?:claude\s+)?haiku",
         "model", "haiku", "reply.model"),
    ],
    "en": [
        (SWITCH_EN + r"code\s+mode", "mode", "code", "reply.mode_code"),
        (SWITCH_EN + r"(?:assistant|normal|simple)\s+mode", "mode", "assistant", "reply.mode_assistant"),
        (SWITCH_EN + r"chat\s+mode", "mode", "chat", "reply.mode_chat"),
        (SWITCH_EN + r"read(?:ing)?\s+mode", "mode", "read", "reply.mode_read"),
        (SWITCH_EN + r"auto(?:nomous)?\s+mode", "mode", "auto", "reply.mode_auto_click"),
        (r"(?:enable|turn on|switch to|activate|open)\s+(?:the\s+)?(?:home|house|ha|home\s*assistant)(?:\s+(?:mode|access))?",
         "home", True, "reply.home_on"),
        (r"(?:disable|turn off|leave|quit|stop|close)\s+(?:the\s+)?(?:home|house|ha|home\s*assistant)(?:\s+(?:mode|access))?",
         "home", False, "reply.home_off"),
        (r"(?:enable|start|turn on|switch to)\s+(?:the\s+)?conversation(?:\s+mode)?",
         "conversation", True, "reply.conv_on"),
        (r"(?:disable|stop|turn off|end|quit)\s+(?:the\s+)?conversation(?:\s+mode)?",
         "conversation", False, "reply.conv_off"),
        (r"(?:enable|turn on|unmute)\s+(?:the\s+)?voice", "voice", True, "reply.voice_on"),
        (r"(?:disable|turn off|mute)\s+(?:the\s+)?voice", "voice", False, "reply.voice_off"),
        (r"(?:use|switch to|model)\s+(?:the\s+)?(?:claude\s+)?fable", "model", "fable", "reply.model"),
        (r"(?:use|switch to|model)\s+(?:the\s+)?(?:claude\s+)?opus", "model", "opus", "reply.model"),
        (r"(?:use|switch to|model)\s+(?:the\s+)?(?:claude\s+)?sonnet", "model", "sonnet", "reply.model"),
        (r"(?:use|switch to|model)\s+(?:the\s+)?(?:claude\s+)?haiku", "model", "haiku", "reply.model"),
    ],
}
# Rôles : « prends le rôle de la compta », « redeviens toi-même ». Les noms de rôles ne peuvent pas
# vivre dans CONTROL — ce sont des dossiers que l'utilisateur dépose, donc ils changent. On capture
# ce qui suit et le moteur le rapproche des rôles réellement trouvés.
ROLE = {
    "fr": {
        # Le mot « rôle » est OBLIGATOIRE : sans lui, « prends une note » ou « deviens sérieuse »
        # seraient lus comme des changements de rôle et n'arriveraient jamais à l'agent.
        "take": r"(?:prends|prend|passe en|active|mets[- ]toi en|endosse|enfile)\s+(?:le\s+|la\s+|ton\s+)?"
                r"r[ôo]le\s+(?:de\s+la\s+|de\s+l'|du\s+|de\s+|d')?(.+)",
        "drop": r"(?:redeviens|reviens|repasse en)\s+(?:toi(?:[- ]m[êe]me)?|{name}|normale?)"
                r"|(?:quitte|abandonne|sors\s+du|arr[êe]te)\s+(?:le\s+|ce\s+)?r[ôo]le",
    },
    "en": {
        "take": r"(?:take|switch to|put on|use)\s+(?:the\s+|your\s+)?role\s+(?:of\s+)?(?:the\s+)?(.+)",
        "drop": r"(?:be|become)\s+(?:yourself|{name})\s*again|(?:drop|leave|exit|quit|stop)\s+(?:the\s+|this\s+)?role",
    },
}


def role_command(text, lang="fr", name="Alison"):
    """Commande de rôle dans CETTE phrase : "" pour redevenir elle-même, le nom demandé sinon,
    None si ce n'en est pas une. Le motif doit couvrir toute la phrase, comme les autres."""
    table = ROLE[base(lang)]
    lowered = " ".join(str(text).split()).casefold()
    if re.match(whole_phrase(table["drop"], lang, name), lowered, re.IGNORECASE):
        return ""
    found = re.match(whole_phrase(table["take"], lang, name), lowered, re.IGNORECASE)
    if not found:
        return None
    wanted = next((group for group in found.groups() if group), "").strip(" .!?,;:")
    return wanted or None


# « Retiens que… » / « oublie… » : (motif, opération) ; le nom d'Alison en tête est toléré ({name}).
# Ancrés en début de phrase : « n'oublie pas de… » ou « tu te souviens de… » ne déclenchent rien.
MEMORY = {
    "fr": [
        (r"(?:retiens|souviens-toi|rappelle-toi|mémorise|note|garde en mémoire)\s+(?:bien\s+)?(?:que\s+|qu['’]\s*)?(.+)$", "remember"),
        (r"(?:oublie|efface de ta mémoire|retire de ta mémoire)\s+(?!pas\b)(?:que\s+|qu['’]\s*|ça\s*:\s*)?(.+)$", "forget"),
    ],
    "en": [
        (r"(?:remember|keep in mind|note|memorize)\s+(?:that\s+)?(.+)$", "remember"),
        (r"forget\s+(?:that\s+|about\s+)?(.+)$", "forget"),
    ],
}


# « Fais un rêve » : le tri de la mémoire, demandé à la voix ou au clavier.
DREAM = {
    "fr": r"fais un r[êe]ve|r[êe]ve un peu|range ta m[ée]moire|fais le tri dans ta m[ée]moire",
    "en": r"dream|have a dream|tidy your memory|sort your memory",
}


# « Montre-moi la page » / « ferme l'aperçu » : la fenêtre posée à côté du panneau.
PREVIEW = {
    "fr": [(r"montre[- ]moi (?:la page|le lien|le site|[çc]a)|ouvre l'aper[çc]u|affiche la page", True),
           (r"ferme l'aper[çc]u|ferme la fen[êe]tre|cache la page", False)],
    "en": [(r"show me (?:the page|the link|it)|open the preview", True),
           (r"close the preview|close the window|hide the page", False)],
}


def preview_command(text, lang="fr", name="Alison"):
    """True = ouvrir l'aperçu, False = le fermer, None = ce n'est pas cette commande."""
    phrase = " ".join(text.split()).casefold()
    for pattern, opening in PREVIEW[base(lang)]:
        if re.match(whole_phrase(pattern, lang, name), phrase, re.IGNORECASE):
            return opening
    return None


def dream_command(text, lang="fr", name="Alison"):
    """Vrai si la phrase demande à Alison de ranger sa mémoire."""
    pattern = whole_phrase(DREAM[base(lang)], lang, name)
    return bool(re.match(pattern, " ".join(text.split()).casefold(), re.IGNORECASE))


def memory_command(text, lang="fr", name="Alison"):
    """(opération, texte) si la phrase est une commande de mémoire, sinon None."""
    phrase = " ".join(text.split())
    for pattern, operation in MEMORY[base(lang)]:
        found = re.match(lead(lang, name) + pattern, phrase.casefold(), re.IGNORECASE)
        if found:
            # Le texte est repris dans la phrase d'origine (casse conservée), à la même position.
            return operation, phrase[found.start(1):found.end(1)].strip(" .!?")
    return None



# Couper la parole : les mots qui arrêtent Alison quand elle parle. Ils sont écoutés par le service
# du mot d'éveil, avec la même grammaire Vosk fermée — et seulement PENDANT qu'elle parle.
# Un mot doit être dit SEUL : le micro entend aussi les haut-parleurs, et une phrase d'Alison qui
# contiendrait « arrête » la ferait se couper elle-même.
# Mesuré au banc (tests/bench/bench_barge.py, 19/09) : « chut » est écarté — Vosk l'isole
# proprement quand Alison commence une phrase par là (« Chut, je plaisante. » la coupait), et
# c'est de toute façon la façon la moins naturelle d'interrompre quelqu'un. Même raison pour
# « quiet » et « hush » seuls en anglais.
BARGE = {
    "fr": ["stop", "arrête", "tais-toi"],
    "en": ["stop", "shut up", "be quiet"],
}


def barge_words(lang="fr"):
    return BARGE[base(lang)]


# Valider une carte à la voix, quand une action attend. VOLONTAIREMENT ASYMÉTRIQUE : autoriser
# demande un mot délibéré, refuser en accepte beaucoup. « Oui » est écarté — c'est le mot le plus
# prononcé d'une pièce, et une carte attend deux minutes. Refuser par erreur ne coûte qu'un
# « recommence » ; autoriser par erreur exécute quelque chose.
APPROVE = {
    # « Vas-y » est écarté après mesure : le lexique Vosk le connaît entier, mais mis à côté de sa
    # forme découpée il rend « vas » + inconnu, et n'est jamais reconnu. Trois mots suffisent.
    "fr": ["valide", "j'autorise"],
    "en": ["approve", "go ahead", "allow it"],
}
REFUSE = {
    "fr": ["non", "refuse", "annule", "laisse", "surtout pas"],
    "en": ["no", "refuse", "cancel", "leave it", "don't"],
}


def decision_words(lang="fr"):
    """(mots qui autorisent, mots qui refusent) pour la langue."""
    return (APPROVE[base(lang)], REFUSE[base(lang)])


# « Ouvre le lien » : le dernier lien de sa réponse, sans passer par l'agent. La phrase doit être
# CELLE-LÀ et rien d'autre : « ouvre la page Wikipédia sur Paris » est une demande, pas un rappel du
# lien précédent — et elle se faisait avaler en silence (trouvé dans un journal réel, 19/09).
OPEN_LINK = {
    "fr": r"ouvre[sz]?\s+(?:le|ce|la)\s+(?:lien|page|site)(?:\s+(?:web|internet))?",
    "en": r"open\s+(?:the|that|this)\s+(?:link|page|site)",
}


def open_link_command(text, lang="fr", name="Alison"):
    """Vrai si la phrase demande d'ouvrir le lien de la dernière réponse, et rien d'autre."""
    phrase = " ".join(text.split()).casefold()
    pattern = OPEN_LINK[base(lang)]
    return bool(re.match(whole_phrase(pattern, lang, name), phrase, re.IGNORECASE))
# « Lance Firefox » : lancement direct d'une application du catalogue, sans passer par l'agent.
LAUNCH = {
    "fr": re.compile(r"(?:lance|ouvre|démarre)\s+(.+?)[.!]?", re.IGNORECASE),
    "en": re.compile(r"(?:launch|open|start|run)\s+(.+?)[.!]?", re.IGNORECASE),
}


# ---------------------------------------------------------------------------
# Commandes du bureau : ce qu'Alison fait ELLE-MÊME, sans réveiller l'agent.
#
# Chaque motif est ancré en début de phrase (le nom d'Alison, « hey » et « s'il te plaît » sont
# tolérés) et doit couvrir TOUTE la phrase : « je me demande ce que fait le presse-papier » ne
# déclenche rien. L'ordre compte — « annule mes rappels » est essayé avant « mes rappels ».
DESK = {
    "fr": [
        ("reminders_clear", r"(?:annule|efface|supprime|enl[èe]ve|vide)\s+(?:tous\s+)?(?:mes|les)\s+rappels"),
        ("reminders", r"(?:quels\s+sont\s+|liste\s+|montre[- ]moi\s+)?(?:mes|les)\s+rappels"),
        ("reminder", r"rappelle[- ]?(?:moi|nous)\s+(?!pourquoi|comment|quand|qui\b|o[ùu]\b|ce que|ce qu|si\b)(?P<rest>.+)"),
        ("note", r"(?:note|ajoute|[ée]cris)\s+(?:[çc]a\s+)?dans\s+(?:obsidian|mon\s+coffre|mes\s+notes)\s*[:,]?\s*(?P<rest>.+)"),
        ("clipboard", r"(?:ouvre|montre|affiche)?\s*(?:le\s+|mon\s+)?presse[- ]papiers?(?:\s+d'omarchy)?"),
        ("emoji", r"(?:ouvre|montre|affiche|donne[- ]moi)?\s*(?:les\s+|des\s+)?[ée]moji(?:s|es)?"),
        ("share", r"(?:partage|envoie)\s+(?:le\s+|mon\s+)?presse[- ]papiers?|partage\s+[çc]a"),
        ("screen", r"(?:regarde|vois|lis)\s+(?:mon\s+|l')?[ée]cran(?!\s+de\s)\s*(?P<rest>.*)"
                    r"|(?:est-ce que\s+)?tu\s+(?:vois|regardes)\s+(?:mon|l')\s*[ée]cran\s*[?]?"
                    r"|qu'est[- ]ce\s+qu'il\s+y\s+a\s+[àa]\s+l'[ée]cran"
                    r"|qu'est[- ]ce\s+que\s+tu\s+vois\s+([àa]\s+l'[ée]cran|sur\s+mon\s+[ée]cran)"),
        ("capture", r"(?:fais|prends|prend)(?:[- ]moi)?\s+(?:une\s+)?capture(?:\s+d'[ée]cran)?|capture\s+d'[ée]cran"),
        ("workspace", r"(?:va|passe|bascule)\s+(?:au|sur le|vers le)\s+bureau\s+(?P<index>\d{1,2})|bureau\s+(?P<index2>\d{1,2})"),
    ],
    "en": [
        ("reminders_clear", r"(?:cancel|clear|delete|remove|drop)\s+(?:all\s+)?(?:my|the)\s+reminders"),
        ("reminders", r"(?:what\s+are\s+|list\s+|show\s+me\s+)?(?:my|the)\s+reminders"),
        ("reminder", r"remind\s+(?:me|us)\s+(?!why|how|when|who\b|where\b|what\b|if\b)(?P<rest>.+)"),
        ("note", r"(?:note|add|write)\s+(?:this\s+)?(?:in|to)\s+(?:obsidian|my\s+vault|my\s+notes)\s*[:,]?\s*(?P<rest>.+)"),
        ("clipboard", r"(?:open|show)?\s*(?:the\s+|my\s+)?clipboard(?:\s+history)?"),
        ("emoji", r"(?:open|show|give\s+me)?\s*(?:the\s+|some\s+)?emojis?"),
        ("share", r"(?:share|send)\s+(?:the\s+|my\s+)?clipboard|share\s+this"),
        ("screen", r"(?:look\s+at|read|check)\s+(?:my\s+|the\s+)?screen(?!\s+of\s)\s*(?P<rest>.*)"
                    r"|(?:can\s+)?you\s+see\s+(?:my|the)\s+screen\s*[?]?"
                    r"|what(?:'s| is)\s+on\s+(?:my|the)\s+screen"
                    r"|what\s+do\s+you\s+see\s+on\s+(?:my|the)\s+screen"),
        ("capture", r"(?:take|grab|make)\s+(?:a\s+)?(?:screenshot|screen\s+capture|capture)"),
        ("workspace", r"(?:go|switch|move)\s+to\s+(?:desktop|workspace)\s+(?P<index>\d{1,2})|(?:desktop|workspace)\s+(?P<index2>\d{1,2})"),
    ],
}

# « dans 20 minutes », « dans 1h30 », « à 15h30 » : les formes d'un délai, par langue. Les nombres
# dits à l'oral (« dans une heure ») arrivent en lettres : la transcription n'écrit pas « 1 ».
DESK_NUMBERS = {
    "fr": {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
           "huit": 8, "neuf": 9, "dix": 10, "douze": 12, "quinze": 15, "vingt": 20, "trente": 30,
           "quarante": 40, "quarante-cinq": 45, "cinquante": 50, "soixante": 60},
    "en": {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20,
           "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60},
}
# (motif, genre) — « hm » = heures et minutes, « m » = minutes, « h » = heures, « at » = heure fixe.
DESK_DELAY = {
    "fr": [(r"\b(?:dans|d['’]ici)\s+(\d{1,2})\s*h(?:eures?)?\s*(\d{1,2})\b", "hm"),
           (r"\b(?:dans|d['’]ici)\s+([\w-]+)\s*(?:minutes?|min|mn)\b", "m"),
           (r"\b(?:dans|d['’]ici)\s+([\w-]+)\s*(?:heures?|h)\b", "h"),
           (r"\b(?:[àa]|vers)\s+(\d{1,2})\s*(?:h|:|heures?)\s*(\d{2})?\b", "at")],
    "en": [(r"\bin\s+(\d{1,2})\s*h(?:ours?)?\s*(\d{1,2})\b", "hm"),
           (r"\bin\s+([\w-]+)\s*(?:minutes?|mins?)\b", "m"),
           (r"\bin\s+([\w-]+)\s*(?:hours?|h)\b", "h"),
           (r"\bat\s+(\d{1,2})\s*(?::|h)?\s*(\d{2})?\s*(am|pm)?\b", "at")],
}
# Liaisons à retirer devant le texte du rappel : « rappelle-moi dans 20 min DE sortir le gâteau ».
DESK_STRIP = {
    "fr": r"^(?:de\s+|d['’]\s*|que\s+|qu['’]\s*|pour\s+|[àa]\s+|:\s*|,\s*)+",
    "en": r"^(?:to\s+|that\s+|about\s+|:\s*|,\s*)+",
}


def desk_command(text, lang="fr", name="Alison"):
    """Commande du bureau : un dictionnaire {"kind": …} avec ses valeurs, ou None.

    La phrase doit ÊTRE la commande : un motif trouvé au milieu d'une question ne compte pas.
    """
    phrase = " ".join(text.split())
    for kind, pattern in DESK[base(lang)]:
        found = re.match(whole_phrase(pattern, lang, name), phrase.casefold(), re.IGNORECASE)
        if not found:
            continue
        command = {"kind": kind}
        groups = found.groupdict()
        if groups.get("rest"):
            # Le texte est repris dans la phrase d'origine, casse comprise, à la même position.
            command["rest"] = phrase[found.start("rest"):found.end("rest")].strip(" .!?")
        index = groups.get("index") or groups.get("index2")
        if index:
            command["index"] = int(index)
        return command
    return None

# ----- Les textes viennent de FICHIERS DE LANGUE, plus jamais du code (demande du 21/09 :
# « prévoir des fichiers .lang pour une interface internationale »). Une langue = `lang/<code>.json`
# livré avec le plugin, et le même format dans ~/.config/omarchy-companion/lang/<code>.json pour une
# langue ajoutée ou corrigée par l'utilisateur (ses clés passent par-dessus). Un fichier porte :
#   {"code": "fr", "name": "Français", "wake": "salut alison", "panel": {...}, "engine": {...}}
# Le panneau lit `panel` (LangLoader.qml), le moteur lit `engine`. L'anglais bouche les trous clé
# par clé, et le journal dit au démarrage combien de textes manquent. Les grammaires de la voix
# (commandes, mots d'arrêt) restent dans le code en fr/en : une autre langue retombe sur l'anglais.
PLUGIN_DIR = Path(__file__).resolve().parent
USER_LANG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "omarchy-companion/lang"
BASE = ("fr", "en")
CODE_OK = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")
TEXTS = {}        # code -> textes du moteur
PANEL = {}        # code -> textes du panneau (pour les tests et le décompte des manques)
LANG_META = {}    # code -> {"name", "wake"}


def load_languages():
    """Relit tous les fichiers de langue : ceux du plugin, puis ceux de l'utilisateur par-dessus."""
    TEXTS.clear(); PANEL.clear(); LANG_META.clear()
    for folder in (PLUGIN_DIR / "lang", USER_LANG_DIR):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            code = path.stem.lower()
            if not CODE_OK.match(code):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            TEXTS.setdefault(code, {}).update({str(k): str(v) for k, v in (data.get("engine") or {}).items()})
            PANEL.setdefault(code, {}).update({str(k): str(v) for k, v in (data.get("panel") or {}).items()})
            meta = LANG_META.setdefault(code, {"name": code, "wake": ""})
            if data.get("name"):
                meta["name"] = str(data["name"])
            if data.get("wake"):
                meta["wake"] = str(data["wake"]).strip().lower()
    global LANGUAGES
    LANGUAGES = tuple(c for c in BASE if c in TEXTS) + tuple(sorted(c for c in TEXTS if c not in BASE))


load_languages()


def base(lang):
    """La langue des GRAMMAIRES (commandes, mots d'arrêt) : fr ou en, l'anglais pour toute autre."""
    return lang if lang in BASE else "en"


def languages():
    """Les langues disponibles, pour le sélecteur des Réglages : [{code, name, wake}]."""
    return [{"code": code, "name": LANG_META.get(code, {}).get("name", code),
             "wake": LANG_META.get(code, {}).get("wake", "")} for code in LANGUAGES]


def missing(lang):
    """Les clés que cette langue n'a pas (l'anglais est alors utilisé) — pour le journal."""
    if lang == "en" or "en" not in TEXTS:
        return []
    return sorted([k for k in TEXTS["en"] if k not in TEXTS.get(lang, {})]
                  + [k for k in PANEL.get("en", {}) if k not in PANEL.get(lang, {})])


def lang_of(config):
    """Langue d'un réglage (dict) : un code dont le fichier existe, français par défaut."""
    value = str((config or {}).get("language", "fr")).lower()
    return value if value in LANGUAGES else "fr"


def t(lang, key, **values):
    """Le texte dans cette langue ; sinon en anglais ; sinon en français. Une clé inconnue partout
    lève KeyError : c'est une faute de code, pas une traduction manquante."""
    text = (TEXTS.get(lang) or {}).get(key)
    if text is None:
        text = TEXTS.get("en", {}).get(key)
    if text is None:
        text = TEXTS["fr"][key]
    return text.format(**values) if values else text


def variants(lang, key):
    """Toutes les variantes d'une phrase : les clés `<key>.01`, `<key>.02`… de la langue (sinon de
    l'anglais, sinon du français). Une clé = une phrase, comme partout dans les fichiers de langue."""
    for table in (TEXTS.get(lang) or {}, TEXTS.get("en", {}), TEXTS["fr"]):
        found = [table[name] for name in sorted(table) if name.startswith(key + ".") and name[len(key) + 1:].isdigit()]
        if found:
            return found
    raise KeyError(key)


def wake_phrase(config):
    """Phrase d'éveil : celle du réglage, sinon celle de la langue."""
    phrase = str((config or {}).get("wakePhrase", "")).strip().lower()
    lang = lang_of(config)
    return phrase or LANG_META.get(lang, {}).get("wake") or VOICE[base(lang)]["wake"]
