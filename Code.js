.pragma library

// Blocs de code du fil : découpage des clôtures Markdown et coloration sobre.
//
// Pas de bibliothèque : une passe d'expressions régulières par langage, et seulement trois
// familles — mot-clé, chaîne ou nombre, commentaire. Les couleurs viennent du thème (passées par
// le panneau), jamais écrites ici.

var FOLD_LINES = 20;        // au-delà, le bloc arrive replié

var KEYWORDS = {
    python: "def class return if elif else for while in not and or is None True False import from as try except finally raise with lambda yield pass break continue global assert del",
    lua: "local function return if then elseif else end for while do in not and or nil true false repeat until break require",
    bash: "if then elif else fi for while do done case esac function return local export source echo cd exit set unset trap read",
    javascript: "const let var function return if else for while do class new this import from export default try catch finally throw async await typeof instanceof null true false undefined",
    qml: "property readonly signal function return if else for while var let const import true false null onCompleted anchors",
    json: "true false null",
};
KEYWORDS.js = KEYWORDS.javascript;
KEYWORDS.py = KEYWORDS.python;
KEYWORDS.sh = KEYWORDS.bash;
KEYWORDS.shell = KEYWORDS.bash;
KEYWORDS.zsh = KEYWORDS.bash;

// Commentaires selon le langage : # (python, bash), // et /* */ (js, qml), -- (lua).
var COMMENTS = {
    python: /#[^\n]*/, bash: /#[^\n]*/, lua: /--(?!\[)[^\n]*/,
    javascript: /\/\/[^\n]*|\/\*[\s\S]*?\*\//, qml: /\/\/[^\n]*|\/\*[\s\S]*?\*\//,
};
COMMENTS.js = COMMENTS.javascript;
COMMENTS.py = COMMENTS.python;
COMMENTS.sh = COMMENTS.bash;
COMMENTS.shell = COMMENTS.bash;
COMMENTS.zsh = COMMENTS.bash;

function known(lang) {
    return String(lang || "").toLowerCase().replace(/^\s+|\s+$/g, "");
}

// ---- découpage -------------------------------------------------------------

// Un message = une suite de morceaux { type: "text" | "code", lang, body }. Une clôture ouverte
// (l'agent écrit encore) est rendue en code aussi : le bloc se colore au fil de la frappe.
function segments(text, plain) {
    var source = String(text || "");
    if (plain)
        return [{ type: "text", lang: "", body: source }];
    var out = [], rest = source, guard = 0;
    while (guard++ < 60) {
        var open = rest.indexOf("```");
        if (open < 0)
            break;
        if (open > 0)
            out.push({ type: "text", lang: "", body: rest.substring(0, open) });
        var after = rest.substring(open + 3);
        var newline = after.indexOf("\n");
        var lang = newline < 0 ? after : after.substring(0, newline);
        var body = newline < 0 ? "" : after.substring(newline + 1);
        if (!/^[a-zA-Z0-9_+-]{0,15}$/.test(lang)) {      // ce n'était pas une clôture de code
            lang = "";
            body = after;
        }
        var close = body.indexOf("```");
        out.push({ type: "code", lang: known(lang),
                   body: (close < 0 ? body : body.substring(0, close)).replace(/\n+$/, "") });
        rest = close < 0 ? "" : body.substring(close + 3);
    }
    if (rest)
        out.push({ type: "text", lang: "", body: rest });
    return out.filter(function (part) { return part.type === "code" || part.body.replace(/\s/g, "") !== ""; });
}

// ---- coloration ------------------------------------------------------------

function escape(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function span(text, color, bold, italic) {
    var style = "color:" + color;
    if (bold)
        style += ";font-weight:bold";
    if (italic)
        style += ";font-style:italic";
    return "<span style=\"" + style + "\">" + escape(text) + "</span>";
}

// colors : { keyword, literal, comment } — jetons du thème, fournis par le panneau.
function highlight(code, lang, colors) {
    var key = known(lang);
    var words = KEYWORDS[key];
    var comment = COMMENTS[key];
    var parts = [];
    if (comment)
        parts.push("(" + comment.source + ")");
    parts.push("(\"(?:[^\"\\\\\\n]|\\\\.)*\"|'(?:[^'\\\\\\n]|\\\\.)*')");
    if (words)
        parts.push("\\b(" + words.split(" ").join("|") + ")\\b");
    parts.push("\\b(\\d+(?:\\.\\d+)?)\\b");
    var pattern = new RegExp(parts.join("|"), "g");
    var out = "", last = 0, found;
    while ((found = pattern.exec(code)) !== null) {
        if (found.index > last)
            out += escape(code.substring(last, found.index));
        var token = found[0];
        if (comment && found[1] !== undefined)
            out += span(token, colors.comment, false, true);
        else if (token.charAt(0) === "\"" || token.charAt(0) === "'")
            out += span(token, colors.literal);
        else if (words && /^[A-Za-z_]/.test(token))
            out += span(token, colors.keyword, true);
        else
            out += span(token, colors.literal);
        last = found.index + token.length;
        if (token.length === 0)
            pattern.lastIndex++;
    }
    out += escape(code.substring(last));
    return "<pre style=\"white-space:pre-wrap\">" + out + "</pre>";
}

function lines(code) {
    return String(code || "").split("\n").length;
}
