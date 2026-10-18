"""L'échelle des modes du Compagnon : ce qu'elle a le DROIT de faire, du plus fermé au plus ouvert.

    chat        Discussion : aucun outil, elle parle.
    read        Lecture : elle lit la machine et le web, ne change rien. Aucune carte n'existe.
    assistant   Assistant : elle agit sur le bureau, chaque action validée par une carte.
    code        Code : session de développement ; ce qui écrit, installe ou sort est validé.
    auto        Autonome : tout ce que Code peut, SANS carte. Accepté et écrit au journal.

Une seule échelle, lue par le moteur, le garde, les rôles et le panneau. Elle vit ici, dans un
module sans dépendance, parce que `roles` et `agents` en ont tous les deux besoin et qu'on ne veut
pas d'import en boucle (c'est ce qui avait forcé une copie de `roles.allows` dans `agents`).

🛑 Autonome supprime le seul contrôle humain. Ce qui ne bouge PAS dans ce cran : le garde, le mur
système, et — parce que plus personne ne relit avant — le coffre et les emplacements privés restent
FERMÉS comme en Assistant (règle d'or, 21/09 : jamais un mot de passe à l'écran). Il ne
s'ouvre qu'au clic : la voix peut descendre l'échelle, jamais monter jusqu'ici.
"""

MODES = ("chat", "read", "assistant", "code", "auto")
# Modes où une carte de validation peut apparaître.
CARD_MODES = ("assistant", "code")
# Modes où elle peut agir sur la machine (carte ou pas).
ACT_MODES = ("assistant", "code", "auto")
# Modes de développement : mêmes outils, mêmes lectures pré-autorisées.
DEV_MODES = ("code", "auto")
# Le cran sans carte. Un seul, nommé, pour que « sans validation » se lise partout de la même façon.
NO_CARD = "auto"


def known(mode, default="assistant"):
    """Un mot inconnu retombe sur Assistant, jamais sur un cran plus ouvert."""
    return mode if mode in MODES else default


def rank(mode):
    return MODES.index(known(mode))


def reaches(mode, needed):
    """Le mode atteint-il ce cran ?"""
    return rank(mode) >= rank(needed)


def narrow(allowed, mode):
    """Le mode réellement appliqué quand seuls `allowed` sont permis : on descend, jamais on ne monte.

    Si le mode demandé n'est pas permis, on retombe sur le plus OUVERT des modes permis qui reste en
    dessous. S'il n'y en a aucun en dessous, le mode demandé est déjà plus fermé que tout ce qui est
    prévu : on le garde. Dans les deux cas, choisir une restriction n'OUVRE jamais un droit.
    """
    if not allowed or mode in allowed:
        return mode
    below = [m for m in allowed if m in MODES and rank(m) <= rank(mode)]
    return max(below, key=rank) if below else mode
