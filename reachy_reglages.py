#!/usr/bin/env python3
"""Les réglages du corps du robot : une liste FERMÉE, décrite une seule fois ici (11/10/2026).

Spec `docs/superpowers/specs/2026-10-11-reachy-page-reglages.md` (lots 0 et 1). Une seule source de vérité :
le fichier de réglages du corps (`vivant.json` sur la machine du robot), décrit par `REGLAGES`. Chaque réglage dit sa
clé, son type, ses bornes, son unité, sa rubrique, son niveau (essentiel ou expert), son intitulé et son
explication — la page de réglages (`reachy_page.py`) n'affiche et n'écrit RIEN d'autre.

Valeur d'origine = la constante du code (`reachy.py`, `reachy_vue.py`), lue au moment où on la demande :
sans fichier, ou clé absente, le corps fait EXACTEMENT ce qu'il faisait avant. Les clés qui existaient déjà
dans `vivant.json` (gestes, voix, dodo…) n'ont pas de valeur d'origine : ce sont les choix de la machine.

Dans le fichier, une valeur est écrite dans l'unité de la page (minutes, %, degrés) ; `facteur` la convertit
dans l'unité du code (secondes, fraction). Ex. `person_again: 10` (minutes) = `PERSON_AGAIN` 600 s.

Écriture (lot 1) : validée ici, ancienne version copiée dans `reglages-historique/` (les 20 dernières),
fichier temporaire puis renommage (600). Aucune dépendance : bibliothèque standard.
"""
import importlib
import json
import os
import threading
import time
from pathlib import Path

RUBRIQUES = ("live", "voir", "entendre", "parler", "toucher", "bouger", "piece", "personnes", "cameras", "maison")
HISTORIQUE = "reglages-historique"
GARDER = 20                        # versions gardées dans l'historique
SECTEURS_MAX = 8                   # directions ignorées au plus


def _r(cle, type_, rubrique, niveau, intitule, aide, **autres):
    entree = {"cle": cle, "type": type_, "rubrique": rubrique, "niveau": niveau,
              "intitule": intitule, "aide": aide, "a_chaud": True, "facteur": 1.0}
    entree.update(autres)
    return entree


# Les rubriques et les groupes suivent la maquette validée le 11/10 (8 rubriques, cet ordre ; « Parler » ajoutée le 11/10 après sa maquette). Ce qui ne
# doit pas être touché (cadences internes, constantes de mesure) n'est PAS ici : on ne peut pas l'écrire.
# `constante` = (module, nom[, clé]) : la valeur d'origine. `origine` : la même chose pour une clé neuve sans
# constante. `existante` : une clé qui existait déjà dans vivant.json (« absente = coupée »), sans origine.
# `brut` : lue telle quelle par le code qui s'en sert (`Hush`), pas par `Reglages`. `affiche` : multiplicateur
# d'affichage seulement (fraction montrée en %).
REGLAGES = [
    _r("accord_requis", "interrupteur", "personnes", "essentiel", "Demander l'accord avant d'apprendre",
       "Actif : l'accord de la personne est noté (qui, quand) avant d'apprendre son visage ou sa voix. Coupé : "
       "le robot apprend sans le demander (usage familial, tout reste sur la machine).", origine=True),
    # --- Caméras de la maison (11/10) : le collecteur de la machine du robot les lit -----
    _r("cams_portillon", "interrupteur", "cameras", "essentiel", "Sonnette",
       "Quand la sonnette voit quelqu'un, garder les gros plans des visages pour que tu les tries. "
       "Tout reste sur la machine.", origine=True, exige="cameras"),
    _r("cams_terrasse", "interrupteur", "cameras", "essentiel", "Terrasse",
       "Pareil pour la caméra de la terrasse (visages plus petits, de plus loin).", origine=True, exige="cameras"),
    _r("cams_animaux", "interrupteur", "cameras", "essentiel", "Animaux",
       "Quand une caméra voit un animal, garder sa découpe pour que tu l'étiquettes (chien, chat…).", origine=True, exige="cameras"),
    _r("cams_vehicules", "interrupteur", "cameras", "essentiel", "Véhicules",
       "Quand la sonnette voit un véhicule, garder sa découpe pour que tu l'étiquettes (ta voiture, le facteur…). "
       "Une voiture garée peut être ignorée pour de bon.", origine=True, exige="cameras"),
    _r("cams_plaques", "interrupteur", "cameras", "essentiel", "Plaques",
       "Lire la plaque des véhicules (au moins 3 images d'accord) : une plaque connue donne le nom à coup sûr. "
       "Le texte d'une plaque inconnue reste ici, effacé avec le passage ; il ne part jamais dans Home Assistant.",
       origine=True, exige="cameras"),
    _r("cams_robot", "interrupteur", "cameras", "essentiel", "Robot (salon)",
       "Les visages que le robot voit sans les reconnaître arrivent aussi ici, pour que tu dises qui c'est.",
       origine=True, exige="cameras"),
    _r("cams_garder", "nombre", "cameras", "essentiel", "Garder les images à trier",
       "Après ce délai, un passage que tu n'as pas trié est effacé. Une image triée est effacée tout de suite : "
       "seule l'empreinte apprise reste.", min=1, max=30, pas=1, unite="jours", origine=7, exige="cameras"),
    # 15/10 : mémoire de la maison (un service de mémoire de la machine du robot, lu dans vivant.json ; absent = actif)
    _r("memoire", "interrupteur", "cameras", "essentiel", "Mémoire de la maison",
       "Garde un journal en texte de qui est passé, où et quand (jamais d'image, jamais de plaque), pour "
       "répondre à « qui est passé hier soir ? » ou « quand est-ce que cette personne est passée ? ». Coupé : rien n'est noté.",
       origine=True, exige="cameras"),
    _r("memoire_garder", "nombre", "cameras", "essentiel", "Durée de la mémoire",
       "Au-delà, un souvenir est effacé.", min=1, max=90, pas=1, unite="jours", origine=30, exige="cameras"),
    # --- Voir ---------------------------------------------------------------------------------------
    _r("suivre", "interrupteur", "voir", "essentiel", "Suivre une personne du regard",
       "La tête suit doucement la personne vue quand le robot est au repos.", origine=True, exige="regard"),
    _r("reconnaitre", "interrupteur", "voir", "essentiel", "Reconnaître les visages",
       "Met un prénom sur une personne enregistrée. Ne sert jamais à autoriser une action.",
       origine=True, exige="visages"),
    _r("mains", "interrupteur", "voir", "essentiel", "Répondre à un coucou",
       "Un coucou : il répond par un geste silencieux. Une main levée : il écoute.",
       existante=True, exige="regard"),
    _r("mains_observer", "interrupteur", "voir", "essentiel", "Observer les gestes sans réagir",
       "Le détecteur de gestes tourne, mais le robot ne répond pas : chaque geste vu est gardé (image et mesures, "
       "100 au plus, sur le robot seulement) pour corriger les fausses alertes.", origine=False, exige="regard"),
    _r("track_lost", "nombre", "voir", "essentiel", "Revenir au centre après",
       "Durée sans personne visible avant que la tête revienne au centre.",
       min=2, max=15, pas=1, unite="s", constante=("reachy", "TRACK_LOST")),
    _r("fps", "nombre", "voir", "expert", "Images analysées",
       "Plus d'images = suivi plus vif, mais plus de calcul.", groupe="Suivi",
       min=1, max=5, pas=1, unite="par s", constante=("reachy_vue", "FPS")),
    _r("track_dead", "nombre", "voir", "expert", "Zone sans mouvement",
       "En dessous de cet écart, la tête ne bouge pas : évite les tremblements.", groupe="Suivi",
       min=1, max=10, pas=0.5, unite="°", constante=("reachy", "TRACK_DEAD")),
    _r("track_gain", "nombre", "voir", "expert", "Viser un peu court",
       "Part du chemin parcourue à chaque mouvement, pour ne jamais dépasser la cible.", groupe="Suivi",
       min=50, max=100, pas=5, unite="%", facteur=0.01, constante=("reachy", "TRACK_GAIN")),
    _r("face_limit", "nombre", "voir", "expert", "Rotation maximale de la tête",
       "De chaque côté. Le robot accepte au plus 65°.", groupe="Suivi",
       min=20, max=65, pas=1, unite="°", constante=("reachy", "FACE_LIMIT")),
    _r("who_min", "nombre", "voir", "expert", "Ressemblance minimale",
       "Mesuré au canapé : la même personne obtient 0,63 à 0,85.", groupe="Reconnaissance des visages",
       min=0.30, max=0.80, pas=0.01, unite="", constante=("reachy_vue", "WHO_MIN")),
    _r("who_gap", "nombre", "voir", "expert", "Avance sur la personne suivante",
       "Évite de confondre deux personnes qui se ressemblent.", groupe="Reconnaissance des visages",
       min=0.05, max=0.30, pas=0.01, unite="", constante=("reachy_vue", "WHO_GAP")),
    _r("face_sure", "nombre", "voir", "expert", "Netteté minimale du visage",
       "En dessous (profil, flou), le robot n'essaie pas de reconnaître.", groupe="Reconnaissance des visages",
       min=0.60, max=0.95, pas=0.01, unite="", constante=("reachy_vue", "FACE_SURE")),
    _r("person_again", "nombre", "voir", "expert", "Ne pas réannoncer la même personne avant",
       "À 3 m, un visage apparaît et disparaît souvent.", groupe="Reconnaissance des visages",
       min=1, max=60, pas=1, unite="min", facteur=60.0, constante=("reachy", "PERSON_AGAIN")),
    # --- Entendre -----------------------------------------------------------------------------------
    _r("voix", "interrupteur", "entendre", "essentiel", "Se tourner vers une voix",
       "Au repos, le robot regarde d'où vient une voix, même sans mot d'éveil.", existante=True),
    _r("tourner_ecoute", "interrupteur", "entendre", "essentiel", "Se tourner vers toi pendant que tu parles",
       "Pendant l'écoute, il suit ta voix en tournant la tête. Coupé : il garde la tête immobile pendant que tu "
       "parles (ses moteurs sont à côté de ses micros).", origine=True),
    _r("voice_step", "nombre", "entendre", "expert", "Se retourner si la voix s'est déplacée de",
       "En dessous, il garde le regard : évite de tourner la tête sans arrêt.", groupe="Direction de la voix",
       min=4, max=30, pas=1, unite="°", constante=("reachy", "VOICE_STEP")),
    _r("voice_min", "nombre", "entendre", "expert", "Écouter avant de se tourner",
       "Nombre de mesures de parole (0,2 s chacune) avant de croire une direction.",
       groupe="Direction de la voix", min=1, max=5, pas=1, unite="mesures", constante=("reachy", "VOICE_MIN")),
    # --- Parler (11/10) : la voix du soir vient d'« Entendre » ; le volume lui-même passe par `reachy_son` ---
    # Les sons de l'assistant vocal (machine du robot : LVA). Le corps pointe deux fichiers fixes vers le son choisi
    # (`exige="sons"` : le dossier des sons, absent chez Alison = réglage grisé).
    _r("son_eveil", "choix", "parler", "essentiel", "Son quand il t'entend",
       "Joué dès qu'il entend « salut Alison », avant que tu parles.", groupe="Ses sons", exige="sons",
       origine="origine", ecouter="eveil",
       options=[["origine", "Celui d'origine"], ["a", "A · Gouttes"], ["b", "B · Robot curieux"], ["c", "C · Carillon"]]),
    _r("son_reflexion", "choix", "parler", "essentiel", "Son pendant qu'il réfléchit",
       "Pendant qu'il prépare sa réponse ; sa réponse le coupe (12 s au plus).", groupe="Ses sons", exige="sons",
       origine="origine", ecouter="reflexion",
       options=[["origine", "Celui d'origine"], ["a", "A · Bulles"], ["b", "B · Ronron"], ["c", "C · Tic doux"],
                ["aucun", "Aucun"]]),
    # 13/10 : lu par un outil de la machine du robot, qui joue `modes/mode-<mode>.wav` du dossier des sons ; le corps n'y touche pas.
    _r("son_modes", "interrupteur", "parler", "essentiel", "Un son à chaque changement de mode",
       "Quand la machine change de mode (jeu, Steam, rétro, PC, serveur, bureau), il joue un petit air propre "
       "à ce mode. Le soir, plus doucement.", groupe="Ses sons", exige="sons", origine=True),
    _r("mimique_incompris", "choix", "parler", "essentiel", "Sa mimique quand il n'a pas compris",
       "Quand sa réponse est « Heuuu… pas compris ! », il la joue avec une émotion de Pollen au lieu de hocher la tête.",
       groupe="Quand il n'a pas compris", origine="confused1", voir=True,
       options=[["confused1", "Perplexe"], ["incomprehensible2", "Perdu"], ["aucune", "Aucune (il hoche la tête)"]]),
    _r("chuchote", "interrupteur", "parler", "essentiel", "Voix plus douce le soir",
       "Le soir, sa voix baisse si la pièce est calme, et redevient normale s'il y a du bruit.", existante=True, groupe="Le soir"),
    _r("chuchote.de", "heure", "parler", "essentiel", "Le soir commence à",
       "Début de la plage horaire où la voix peut baisser.", depend="chuchote", brut=True,
       constante=("reachy", "HUSH_DEFAULT", "de"), groupe="Le soir"),
    _r("chuchote.a", "heure", "parler", "essentiel", "Et finit à",
       "Fin de la plage horaire (le lendemain matin si elle est plus tôt).", depend="chuchote", brut=True,
       constante=("reachy", "HUSH_DEFAULT", "a"), groupe="Le soir"),
    # La voix du soir est lue TELLE QUELLE par `Hush` (et par le corps de la machine du robot) : le fichier garde la
    # fraction (0,65), la page l'affiche en % (`affiche`).
    _r("chuchote.doux", "nombre", "parler", "expert", "Voix douce", "Pièce calme.", groupe="Voix du soir",
       min=0.3, max=1.0, pas=0.05, unite="%", affiche=100, depend="chuchote", brut=True,
       constante=("reachy", "HUSH_DEFAULT", "doux")),
    _r("chuchote.chuchote", "nombre", "parler", "expert", "Voix chuchotée", "Pièce très calme.",
       groupe="Voix du soir", min=0.2, max=0.8, pas=0.05, unite="%", affiche=100, depend="chuchote", brut=True,
       constante=("reachy", "HUSH_DEFAULT", "chuchote")),
    _r("chuchote.calme", "nombre", "parler", "expert", "Pièce calme en dessous de",
       "Bruit de fond mesuré au micro. Nuit télé éteinte : 51 ; télé allumée : 200 à 350.",
       groupe="Voix du soir", min=60, max=400, pas=10, unite="", depend="chuchote", brut=True,
       constante=("reachy", "HUSH_DEFAULT", "calme")),
    _r("chuchote.tres_calme", "nombre", "parler", "expert", "Pièce très calme en dessous de",
       "Même échelle que ci-dessus.", groupe="Voix du soir", min=20, max=200, pas=5, unite="",
       depend="chuchote", brut=True, constante=("reachy", "HUSH_DEFAULT", "tres_calme")),
    _r("garde_haut_parleur", "interrupteur", "parler", "expert", "Garder le haut-parleur au maximum",
       "Le réglage interne de sa puce son (PCM,1) retombe à -20 dB quand le robot est rebranché : il est remis "
       "à 100 % chaque minute. À couper seulement pour un essai.", groupe="Haut-parleur", origine=True),
    # --- Toucher ------------------------------------------------------------------------------------
    _r("antennes", "interrupteur", "toucher", "essentiel", "Réagir quand on touche une antenne",
       "Une caresse le rend content, une tape le fait sursauter.", origine=True),
    _r("appui_long", "interrupteur", "toucher", "essentiel", "Antenne tenue = couper le micro",
       "Tenir une antenne écartée coupe le micro ; recommencer le rétablit. Antennes baissées tant qu'il "
       "est coupé.", origine=True),
    _r("touch_long", "nombre", "toucher", "essentiel", "Tenir pendant", "Durée de l'appui long sur une antenne.",
       min=1.5, max=5, pas=0.5, unite="s", depend="appui_long", constante=("reachy", "TOUCH_LONG")),
    _r("toucher", "interrupteur", "toucher", "essentiel", "Sentir une main sur la tête ou le corps",
       "D'après ses 7 moteurs : caresse, tête poussée, corps tourné. Seulement quand il ne bouge pas.",
       existante=True),
    # lot 6/7 (11/10) : toucher silencieux. Coupé (origine) = geste silencieux ; activé = émotion de Pollen (sonore).
    _r("toucher_son", "interrupteur", "toucher", "expert", "Réaction sonore de Pollen",
       "Coupé : une caresse ou une tape fait un geste silencieux. Activé : il joue une émotion enregistrée "
       "de Pollen, avec du son, même la nuit.", groupe="Antennes", origine=False),
    # Appuyé à 2° au moins : en dessous, il n'y a plus d'écart avec le relâché (TOUCH_RELEASE 1,5°).
    _r("touch_press", "nombre", "toucher", "expert", "Antenne touchée à partir de",
       "Un doigt écarte l'antenne d'environ 5°. Bruit mesuré : 0,6°.", groupe="Antennes",
       min=2, max=8, pas=0.5, unite="°", constante=("reachy", "TOUCH_PRESS")),
    _r("touch_hard_degrees", "nombre", "toucher", "expert", "Tape au-delà de",
       "Caresses mesurées : 4 à 7° ; tapes : 17 à 35°.", groupe="Antennes",
       min=6, max=30, pas=1, unite="°", constante=("reachy", "TOUCH_HARD_DEGREES")),
    _r("touch_hard_speed", "nombre", "toucher", "expert", "Ou plus vite que",
       "Caresses : environ 32°/s ; tapes : jusqu'à 227°/s.", groupe="Antennes",
       min=30, max=200, pas=5, unite="°/s", constante=("reachy", "TOUCH_HARD_SPEED")),
    _r("touch_cooldown", "nombre", "toucher", "expert", "Attente entre deux touchers",
       "Un nouveau toucher n'est pas compté avant ce délai.", groupe="Antennes",
       min=1, max=10, pas=0.5, unite="s", constante=("reachy", "TOUCH_COOLDOWN")),
    _r("body_press", "nombre", "toucher", "expert", "Main posée à partir de",
       "Écart sur un moteur. Bruit : 0,09° ; main posée : 0,8 à 1°.", groupe="Tête et corps",
       min=0.2, max=2, pas=0.1, unite="°", constante=("reachy", "BODY_PRESS")),
    _r("body_push", "nombre", "toucher", "expert", "Poussée au-delà de",
       "En dessous : une caresse. Tête poussée mesurée : 2 à 8°.", groupe="Tête et corps",
       min=0.8, max=5, pas=0.1, unite="°", constante=("reachy", "BODY_PUSH")),
    _r("body_cooldown", "nombre", "toucher", "expert", "Attente entre deux contacts",
       "Un nouveau contact n'est pas compté avant ce délai.", groupe="Tête et corps",
       min=1, max=10, pas=0.5, unite="s", constante=("reachy", "BODY_COOLDOWN")),
    # --- Bouger -------------------------------------------------------------------------------------
    _r("gestes", "interrupteur", "bouger", "essentiel", "Petits gestes au repos",
       "Un coup d'œil, la tête penchée, les antennes… toujours silencieux. Son humeur choisit le geste.",
       existante=True),
    _r("life_every", "plage", "bouger", "essentiel", "Un geste toutes les",
       "Tiré au hasard entre ces deux durées.", min=10, max=120, pas=5, unite="s", depend="gestes",
       constante=("reachy", "LIFE_EVERY")),
    _r("dodo", "nombre", "bouger", "essentiel", "S'endormir quand personne n'est là depuis",
       "Ni vu ni entendu. Une voix, un visage ou un toucher le réveille. 0 = jamais.",
       min=0, max=60, pas=1, unite="min", existante=True),
    _r("eco", "nombre", "bouger", "essentiel", "En mode éco, s'endormir après",
       "Quand le mode éco est actif. 0 = comme d'habitude.", min=0, max=30, pas=1, unite="min", existante=True),
    # 18/10 : endormi, il a la tête posée et ne voit plus la pièce — seuls une voix ou un toucher le
    # réveillaient. Le capteur de présence de la pièce lui sert de troisième sens (constat en test :
    # « il se met à dormir même s'il y a du monde dans la pièce »).
    _r("presence_piece", "interrupteur", "bouger", "essentiel", "Rester éveillé si la maison voit quelqu'un",
       "Le capteur de présence de la pièce compte comme une présence : il ne s'endort plus tant que "
       "quelqu'un est là, et il se réveille quand on entre — même sans voir de visage.",
       origine=True, groupe="La maison le réveille"),
    _r("presence_de", "heure", "bouger", "essentiel", "À partir de",
       "Avant cette heure, le capteur de la pièce est ignoré : il ne se réveille pas la nuit.",
       depend="presence_piece", origine="07:00", groupe="La maison le réveille"),
    _r("presence_a", "heure", "bouger", "essentiel", "Jusqu'à",
       "Après cette heure, le capteur de la pièce est ignoré (le lendemain matin si elle est plus tôt).",
       depend="presence_piece", origine="23:30", groupe="La maison le réveille"),
    _r("nod_pitch", "nombre", "bouger", "expert", "Hochement de respiration",
       "Amplitude du lent mouvement de tête au repos.", groupe="Repos",
       min=0, max=12, pas=1, unite="°", constante=("reachy", "NOD_PITCH")),
    _r("breath_seconds", "nombre", "bouger", "expert", "Respirer pendant",
       "Puis il se tient immobile jusqu'au prochain événement.", groupe="Repos",
       min=0, max=10, pas=0.5, unite="min", facteur=60.0, constante=("reachy", "BREATH_SECONDS")),
    _r("sway_master", "nombre", "bouger", "expert", "Ampleur des mouvements quand il parle",
       "La tête suit le volume de sa voix.", groupe="Repos",
       min=0, max=2.5, pas=0.1, unite="×", constante=("reachy", "SWAY_MASTER")),
    _r("antenna_rest", "nombre", "bouger", "expert", "Antennes écartées au repos",
       "À 0°, elles tremblent (doc Pollen).", groupe="Antennes",
       min=5, max=30, pas=1, unite="°", constante=("reachy", "ANTENNA_REST")),
    _r("antenna_mute", "nombre", "bouger", "expert", "Antennes baissées quand le micro est coupé",
       "Bien visibles, loin de la position de sommeil (175°).", groupe="Antennes",
       min=60, max=150, pas=5, unite="°", constante=("reachy", "ANTENNA_MUTE")),
    _r("mood_half", "nombre", "bouger", "expert", "Retour au calme de l'humeur",
       "Temps pour que son humeur perde la moitié de son intensité.", groupe="Humeur",
       min=1, max=30, pas=1, unite="min", facteur=60.0, constante=("reachy", "MOOD_HALF")),
    _r("mood_strength", "nombre", "bouger", "expert", "Influence de l'humeur sur les gestes",
       "0 = gestes tirés au hasard.", groupe="Humeur",
       min=0, max=3, pas=0.1, unite="", constante=("reachy", "MOOD_STRENGTH")),
    _r("eco_life", "nombre", "bouger", "expert", "En mode éco, gestes plus rares",
       "Multiplie l'intervalle entre deux gestes.", groupe="Humeur",
       min=1, max=4, pas=0.5, unite="×", constante=("reachy", "ECO_LIFE")),
    # --- Pièce (affichée ; l'ajout et le retrait arrivent avec l'assistant Pièce, lot 4) -------------
    _r("ignorer", "secteurs", "piece", "essentiel", "Directions ignorées",
       "Ni les voix ni les visages de ces directions ne comptent (degrés, repère du socle ; négatif = à sa "
       "droite).", min=-180, max=180, pas=1, unite="°", existante=True),
    # --- Lot 4 : écrits par les assistants de calibrage (pièce, gestes) ------------------------------
    # Les repères de la pièce : où sont le canapé et la télé, mesurés par l'assistant « Pièce ». Ils ne
    # changent rien au comportement du corps (affichage, et le script de Home Assistant qui les relit).
    _r("repere_canape", "secteurs", "piece", "expert", "Repère : le canapé",
       "Direction où l'on parle depuis le canapé (mesurée par l'assistant Pièce), repère du socle.",
       groupe="Repères", min=-180, max=180, pas=1, unite="°", existante=True),
    _r("repere_tele", "secteurs", "piece", "expert", "Repère : la télé",
       "Direction d'où vient le son de la télé (mesurée par l'assistant Pièce), repère du socle.",
       groupe="Repères", min=-180, max=180, pas=1, unite="°", existante=True),
    # Les deux seuils de la règle « bras levé » (calibrée le 11/10), en largeurs d'épaules.
    _r("main_coude", "nombre", "voir", "expert", "Bras levé : coude au-dessus de l'épaule de",
       "Mesuré le 11/10 : postures pièges 0,27 au plus, bras levés 0,42 à 0,78 (en largeurs d'épaules).",
       groupe="Gestes de la main", min=0.15, max=0.8, pas=0.01, unite="épaule", constante=("reachy_vue", "ELBOW_UP")),
    _r("main_poignet", "nombre", "voir", "expert", "Bras levé : poignet au-dessus du nez de",
       "Mesuré le 11/10 : postures pièges 0,29 au plus, bras levés 0,76 à 1,29 (en largeurs d'épaules).",
       groupe="Gestes de la main", min=0.2, max=1.2, pas=0.01, unite="épaule",
       constante=("reachy_vue", "WRIST_OVER_NOSE")),
]
PAR_CLE = {r["cle"]: r for r in REGLAGES}
# Les clés de premier niveau du fichier que décrit le schéma (« chuchote.doux » vit dans « chuchote »).
RACINES = tuple(dict.fromkeys(r["cle"].split(".")[0] for r in REGLAGES))


def _decimales(pas):
    texte = repr(float(pas))
    return 0 if float(pas).is_integer() else len(texte.split(".")[1])


def _arrondi(valeur, entree):
    d = _decimales(entree.get("pas", 1))
    return int(round(valeur)) if d == 0 else round(float(valeur), d)


def origine_code(cle):
    """La valeur d'origine dans l'unité du CODE (secondes, fraction…), lue maintenant ; None s'il n'y en a pas."""
    entree = PAR_CLE[cle]
    if "constante" not in entree:
        return entree.get("origine")
    module, nom, *dedans = entree["constante"]
    valeur = getattr(importlib.import_module(module), nom)
    for k in dedans:
        valeur = valeur[k]
    return list(valeur) if isinstance(valeur, (tuple, list)) else valeur


def origine(cle):
    """La valeur d'origine dans l'unité de la PAGE (celle du fichier), ou None."""
    entree, valeur = PAR_CLE[cle], origine_code(cle)
    if valeur is None or entree["type"] in ("interrupteur", "heure", "choix"):
        return valeur
    if entree["type"] == "plage":
        return [_arrondi(v / entree["facteur"], entree) for v in valeur]
    return _arrondi(valeur / entree["facteur"], entree)


def _nombre(valeur, entree):
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur != valeur:
        raise ValueError(f"{entree['intitule']} : un nombre est attendu")
    if not entree["min"] <= valeur <= entree["max"]:
        raise ValueError(f"{entree['intitule']} : entre {entree['min']} et {entree['max']}")
    return _arrondi(valeur, entree)


def valider(cle, valeur):
    """La valeur normalisée (unité de la page), ou ValueError avec un message en français."""
    entree = PAR_CLE.get(cle)
    if entree is None:
        raise ValueError(f"réglage inconnu : {cle}")
    kind = entree["type"]
    if kind == "interrupteur":
        if not isinstance(valeur, bool):
            raise ValueError(f"{entree['intitule']} : actif ou coupé")
        return valeur
    if kind == "nombre":
        return _nombre(valeur, entree)
    if kind == "plage":
        if not isinstance(valeur, (list, tuple)) or len(valeur) != 2:
            raise ValueError(f"{entree['intitule']} : deux durées")
        a, b = (_nombre(v, entree) for v in valeur)
        if a > b:
            raise ValueError(f"{entree['intitule']} : la première durée doit être la plus courte")
        return [a, b]
    if kind == "choix":                                     # 11/10 : une option de la liste FERMÉE `options`
        if valeur not in [cle for cle, _ in entree["options"]]:
            raise ValueError(f"{entree['intitule']} : choix inconnu")
        return valeur
    if kind == "heure":
        try:
            heures, minutes = str(valeur).split(":")
            if len(heures) == 2 and len(minutes) == 2 and 0 <= int(heures) <= 23 and 0 <= int(minutes) <= 59:
                return f"{int(heures):02d}:{int(minutes):02d}"
        except ValueError:
            pass
        raise ValueError(f"{entree['intitule']} : une heure HH:MM")
    if kind == "secteurs":
        if not isinstance(valeur, list) or len(valeur) > SECTEURS_MAX:
            raise ValueError(f"{entree['intitule']} : au plus {SECTEURS_MAX} directions")
        secteurs = []
        for secteur in valeur:
            if not isinstance(secteur, (list, tuple)) or len(secteur) != 2:
                raise ValueError(f"{entree['intitule']} : chaque direction va d'un angle à un autre")
            a, b = sorted(_nombre(v, entree) for v in secteur)
            secteurs.append([a, b])
        return secteurs
    raise ValueError(f"réglage inconnu : {cle}")


def brut(alive, cle):
    """La valeur telle qu'écrite dans le fichier (`alive`), ou None si absente."""
    racine, *sous = cle.split(".")
    valeur = (alive or {}).get(racine)
    if sous:
        return valeur.get(sous[0]) if isinstance(valeur, dict) else None
    return valeur


def lu(alive, cle):
    """La valeur affichée par la page, unité de la page. Clé absente : sa valeur d'origine ; pour une clé qui
    existait déjà, ce que fait le corps sans elle (coupé, 0, aucune direction)."""
    entree, valeur = PAR_CLE[cle], brut(alive, cle)
    if cle == "chuchote":                                  # objet ou false ; {"actif": false} = coupé, réglages gardés
        return valeur not in (None, False) and not (isinstance(valeur, dict) and valeur.get("actif") is False)
    if entree["type"] == "interrupteur" and entree.get("existante"):
        return bool(valeur)                                # `toucher: "mesure"` est actif
    if valeur is None:
        defaut = origine(cle)
        if defaut is None and entree.get("existante"):
            return [] if entree["type"] == "secteurs" else 0
        return defaut
    try:
        return valider(cle, valeur)
    except ValueError:
        return valeur if entree.get("existante") or entree.get("brut") else origine(cle)


class Reglages:
    """Les valeurs du moment, dans l'unité du CODE : celles du fichier validées, sinon la constante d'origine.
    Un seul objet par corps, partagé par ses parties (toucher, attention, humeur…) : le recharger le change pour
    toutes à la fois. Sans fichier : `Reglages()` rend les constantes d'aujourd'hui."""

    def __init__(self, alive=None):
        self.valeurs = {}
        self.rejetes = []
        if alive:
            self.charger(alive)

    def charger(self, alive):
        """Relit `alive` (le contenu du fichier). → les clés dont la valeur a changé. Une valeur invalide est
        ignorée (la valeur d'origine reste) et notée dans `rejetes`."""
        valeurs, rejetes = {}, []
        for entree in REGLAGES:
            cle = entree["cle"]
            if entree.get("existante") or entree.get("brut"):
                continue                                   # lues par le corps lui-même, comme avant
            valeur = brut(alive, cle)
            if valeur is None:
                continue
            try:
                valeur = valider(cle, valeur)
            except ValueError:
                rejetes.append(cle)
                continue
            if entree["type"] == "plage":
                valeurs[cle] = tuple(v * entree["facteur"] for v in valeur)
            elif entree["type"] == "nombre":
                valeurs[cle] = valeur * entree["facteur"]
            else:
                valeurs[cle] = valeur
        changes = sorted(k for k in set(valeurs) | set(self.valeurs) if valeurs.get(k) != self.valeurs.get(k))
        self.valeurs, self.rejetes = valeurs, rejetes
        return changes

    def __call__(self, cle):
        if cle in self.valeurs:
            return self.valeurs[cle]
        valeur = origine_code(cle)
        return tuple(valeur) if isinstance(valeur, list) else valeur


# --- Lot 1 : lire et écrire le fichier --------------------------------------------------------------------
VERROU = threading.Lock()


def lire(fichier):
    """Le contenu du fichier : un dict ; absent = {} ; illisible = ValueError (on n'écrase pas une erreur de
    frappe faite à la main, on la signale)."""
    try:
        texte = Path(fichier).read_text()
    except FileNotFoundError:
        return {}
    contenu = json.loads(texte)
    if not isinstance(contenu, dict):
        raise ValueError("le fichier de réglages n'est pas un objet JSON")
    return contenu


def appliquer(alive, changements):
    """Un nouveau contenu : `alive` avec les `changements` {clé: valeur ou None}. None = revenir à la valeur
    d'origine (la clé est retirée du fichier). Tout est validé AVANT de changer quoi que ce soit."""
    nouveau = json.loads(json.dumps(alive))                # copie profonde, et rien que du JSON
    prets = []
    for cle, valeur in changements.items():
        entree = PAR_CLE.get(cle)
        if entree is None:
            raise ValueError(f"réglage inconnu : {cle}")
        if valeur is None:
            if origine(cle) is None:
                raise ValueError(f"{entree['intitule']} : pas de valeur d'origine")
            prets.append((cle, None))
        else:
            prets.append((cle, valider(cle, valeur)))
    for cle, valeur in prets:
        racine, *sous = cle.split(".")
        if cle == "chuchote":                              # coupé = {"actif": false} : les réglages du soir restent
            actuel = nouveau.get("chuchote")
            objet = dict(actuel) if isinstance(actuel, dict) else {}
            if valeur:
                objet.pop("actif", None)
            else:
                objet["actif"] = False
            nouveau["chuchote"] = objet
        elif cle == "toucher" and valeur and nouveau.get("toucher"):
            pass                                           # déjà actif (`"mesure"` compris) : on n'y touche pas
        elif sous:
            actuel = nouveau.get(racine)
            objet = dict(actuel) if isinstance(actuel, dict) else ({"actif": False} if actuel is False else {})
            if valeur is None:
                objet.pop(sous[0], None)
            else:
                objet[sous[0]] = valeur
            nouveau[racine] = objet
        elif valeur is None:
            nouveau.pop(cle, None)
        else:
            nouveau[cle] = valeur
    return nouveau


def sauvegarder(fichier):
    """Copie la version actuelle dans `reglages-historique/` (700, copies 600) ; garde les GARDER dernières."""
    fichier = Path(fichier)
    if not fichier.exists():
        return None
    dossier = fichier.parent / HISTORIQUE
    dossier.mkdir(mode=0o700, exist_ok=True)
    dossier.chmod(0o700)
    copie = dossier / f"{fichier.stem}-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**9:09d}.json"
    ecrire_atomique(copie, fichier.read_bytes())
    for vieux in sorted(dossier.glob(f"{fichier.stem}-*.json"))[:-GARDER]:
        vieux.unlink(missing_ok=True)
    return copie


def ecrire_atomique(fichier, donnees):
    """Fichier temporaire (600) dans le même dossier, puis renommage : jamais de fichier à moitié écrit."""
    fichier = Path(fichier)
    temporaire = fichier.with_name(f".{fichier.name}.{os.getpid()}.tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descripteur, "wb") as sortie:
            sortie.write(donnees if isinstance(donnees, bytes) else donnees.encode())
            sortie.flush()
            os.fsync(sortie.fileno())
        os.chmod(temporaire, 0o600)
        os.replace(temporaire, fichier)
    except BaseException:
        temporaire.unlink(missing_ok=True)
        raise


def ecrire(fichier, changements):
    """Valide, sauvegarde l'ancienne version, écrit. → le nouveau contenu. Un seul écrivain à la fois."""
    with VERROU:
        nouveau = appliquer(lire(fichier), changements)
        sauvegarder(fichier)
        ecrire_atomique(fichier, json.dumps(nouveau, ensure_ascii=False, indent=2) + "\n")
        return nouveau


def schema_public():
    """Le schéma tel que la page le lit : sans les noms de constantes du code, avec la valeur d'origine."""
    sortie = []
    for entree in REGLAGES:
        public = {k: v for k, v in entree.items() if k not in ("constante", "facteur", "brut")}
        public["origine"] = origine(entree["cle"])
        sortie.append(public)
    return sortie
