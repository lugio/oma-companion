.pragma library

// Le formatage des textes à trous du panneau : {0}, {1}, {2}. Les textes eux-mêmes ne sont plus
// ici : une langue = un fichier `lang/<code>.json` (chargé par LangLoader.qml), et le même format
// dans ~/.config/omarchy-companion/lang/ pour une langue ajoutée ou corrigée par l'utilisateur.
// Le moteur a la même règle (texts.py). Aucun texte en dur nulle part.

function format(text, a, b, c) {
    return String(text === undefined ? "" : text).replace("{0}", a === undefined ? "" : a)
                                                 .replace("{1}", b === undefined ? "" : b)
                                                 .replace("{2}", c === undefined ? "" : c);
}
