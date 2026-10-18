import QtQuick
import qs.Commons

// Avatar d'Alison, dessiné d'un seul Canvas aux couleurs du thème actif (maquette validée le 13/09).
// États (`mood`) :
//   idle         au repos : respire, cligne, sourit
//   muted        micro coupé en conversation : yeux mi-clos, anneau pointillé atténué
//   listening    couronne de barres au rythme de ta voix (`level`), yeux grands ouverts
//   transcribing / thinking   arc qui tourne, regard en l'air
//   acting       regard concentré
//   waiting      attend ta validation : sourcils levés, anneau qui bat
//   speaking     bouche ouverte selon le volume RÉEL de la voix (`level`, envoyé par voice.py)
//   ignored      phrase qui ne lui était pas adressée : petit non de la tête, regard ailleurs
//   error        air inquiet, anneau en couleur d'urgence
// Et ce qu'elle FAIT pendant qu'elle travaille (`activity`, dérivé des outils de l'agent) :
//   search  balaie du regard, un point tourne sur l'anneau      (WebSearch)
//   read    parcourt une ligne, trois traits de texte défilent  (WebFetch, Read, Grep)
//   write   un curseur clignote, l'anneau se remplit            (Write/Edit sur un texte)
//   code    accolades, l'anneau se remplit                      (Write/Edit sur du code)
//   run     l'invite `>` et son curseur                         (Bash)
//   mail    une enveloppe                                       (le lecteur de courrier)
//   dream   yeux clos, des « z » qui montent                     (le rangement de la mémoire)
Item {
    id: root
    property string mood: "idle"
    // Ce qu'elle FAIT, quand elle travaille (voir en-tête). "" = rien de particulier.
    property string activity: ""
    property bool animate: true
    // Sous cette taille (barre), on ne dessine que ce qui reste lisible : anneau, yeux, bouche.
    readonly property bool tiny: width < 30
    // Couleurs : celles du menu par défaut, celles de la barre quand il y vit (sinon la tête est
    // dessinée en couleur de panneau sur le fond de la barre, et on ne voit rien).
    property color foreground: Color.menu.text
    property color background: Color.menu.background
    property real level: 0
    // Volume lissé : la bouche ne claque pas d'une tranche de 50 ms à l'autre.
    // (« eased », pas « smooth » : ce nom masquerait Item.smooth.)
    property real eased: 0
    property real clock: 0
    width: Style.space(86)
    height: width

    onLevelChanged: eased = level
    Behavior on eased { NumberAnimation { duration: 70 } }
    onMoodChanged: { if (mood === "ignored") shakeStart = clock; canvas.requestPaint(); }
    property real shakeStart: -10

    // Horloge d'animation, seulement quand l'avatar est visible.
    NumberAnimation on clock {
        running: root.visible && root.animate
        from: 0; to: 3600; duration: 3600000
        loops: Animation.Infinite
    }
    onClockChanged: canvas.requestPaint()
    onEasedChanged: if (!root.animate) canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative

        function oval(ctx, cx, cy, rx, ry) {
            ctx.beginPath();
            ctx.ellipse(cx - rx, cy - ry, rx * 2, ry * 2);
            ctx.fill();
        }

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var W = width, k = W / 64, c = W / 2, t = root.clock, m = root.mood;
            var working = m === "thinking" || m === "transcribing";
            var act = (working || m === "acting" || root.activity === "dream") ? root.activity : "";
            if (root.tiny && act !== "dream")
                act = "";   // dans la barre, seul l'anneau et le regard parlent
            var lv = Math.min(1, root.eased);
            var r = W / 2 - 4 * k;
            ctx.lineCap = "round";

            // ---- Anneau ----
            ctx.save();
            ctx.lineWidth = Math.max(1.4, 3 * k);
            ctx.strokeStyle = Color.accent;
            if (m === "listening") {
                var n = 36;
                ctx.lineWidth = Math.max(1.2, 2 * k);
                for (var i = 0; i < n; i++) {
                    var a = i / n * Math.PI * 2;
                    var l = lv * (0.55 + 0.45 * Math.sin(i * 2.7 + t * 3));
                    var r0 = r - 1.5 * k, r1 = r0 + (1.5 + l * 4.5) * k;
                    ctx.globalAlpha = 0.45 + l * 0.55;
                    ctx.beginPath();
                    ctx.moveTo(c + Math.cos(a) * r0, c + Math.sin(a) * r0);
                    ctx.lineTo(c + Math.cos(a) * r1, c + Math.sin(a) * r1);
                    ctx.stroke();
                }
            } else if (act === "dream") {
                // Respiration lente : rien ne presse, elle range.
                var souffle = 0.5 + 0.5 * Math.sin(t * 0.9);
                ctx.globalAlpha = 0.2 + souffle * 0.4;
                ctx.lineWidth = Math.max(1.2, (2 + souffle) * k);
                ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke();
            } else if (working || m === "acting") {
                var p = (t / 1.4) % 1 * Math.PI * 2;
                ctx.globalAlpha = 0.22;
                ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke();
                ctx.globalAlpha = 1;
                if (act === "write" || act === "code") {
                    // Écriture : l'anneau se remplit par segments, comme des lignes qui s'ajoutent.
                    var seg = 14, done = Math.floor((t * 3) % (seg + 4));
                    for (var w = 0; w < seg; w++) {
                        var a0 = -Math.PI / 2 + w / seg * Math.PI * 2;
                        ctx.globalAlpha = w < done ? 1 : 0.25;
                        ctx.beginPath(); ctx.arc(c, c, r, a0, a0 + Math.PI * 2 / seg * 0.55); ctx.stroke();
                    }
                } else if (act === "search") {
                    // Recherche : un point balaie l'anneau, comme un radar.
                    ctx.beginPath(); ctx.arc(c, c, r, p, p + Math.PI * 0.25); ctx.stroke();
                    ctx.beginPath();
                    ctx.arc(c + Math.cos(p) * r, c + Math.sin(p) * r, 2.2 * k, 0, Math.PI * 2);
                    ctx.fillStyle = Color.accent; ctx.fill();
                } else if (act === "read") {
                    // Lecture : deux arcs qui avancent doucement, comme des lignes parcourues.
                    for (var line = 0; line < 2; line++) {
                        var start = p * 0.5 + line * Math.PI;
                        ctx.globalAlpha = 1 - line * 0.45;
                        ctx.beginPath(); ctx.arc(c, c, r, start, start + Math.PI * 0.45); ctx.stroke();
                    }
                } else {
                    ctx.beginPath(); ctx.arc(c, c, r, p, p + Math.PI * 0.7); ctx.stroke();
                }
            } else if (m === "muted") {
                // Pointillé tracé à la main : pas de setLineDash garanti dans le Canvas QML.
                ctx.strokeStyle = Color.muted;
                ctx.globalAlpha = 0.8;
                ctx.lineWidth = Math.max(1.2, 2 * k);
                var dots = 28;
                for (var d = 0; d < dots; d++) {
                    var s0 = d / dots * Math.PI * 2;
                    ctx.beginPath(); ctx.arc(c, c, r, s0, s0 + Math.PI * 2 / dots * 0.35); ctx.stroke();
                }
            } else if (m === "waiting") {
                var beat = 0.5 + 0.5 * Math.sin(t * 4);
                ctx.globalAlpha = 0.4 + beat * 0.6;
                ctx.lineWidth = Math.max(1.4, (2.5 + beat * 1.5) * k);
                ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke();
            } else if (m === "speaking") {
                ctx.globalAlpha = 0.45 + lv * 0.55;
                ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke();
            } else if (m === "error") {
                ctx.strokeStyle = Color.urgent;
                ctx.globalAlpha = 0.95;
                ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke();
            } else {
                ctx.globalAlpha = m === "ignored" ? 0.2 : 0.32;
                ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke();
            }
            ctx.restore();

            // ---- Visage ----
            var fx = c, fy = c, scale = 1;
            if (m === "idle") scale = 1 + 0.03 * Math.sin(t * 2);
            if (m === "listening") scale = 1 + lv * 0.07;
            var shake = t - root.shakeStart;
            if (m === "ignored" && shake >= 0 && shake < 0.7)
                fx += Math.sin(shake * 26) * (0.7 - shake) * 5 * k;
            var fr = W * 0.36 * scale, dia = fr * 2, top = fy - fr;
            if (root.tiny) {
                // Dans la barre, la tête est un trait, pas un disque : les icônes voisines sont des
                // traits, un aplat crierait plus fort que tout le reste.
                ctx.strokeStyle = root.foreground;
                ctx.lineWidth = Math.max(1.2, dia * 0.07);
                ctx.beginPath(); ctx.arc(fx, fy, fr - ctx.lineWidth / 2, 0, Math.PI * 2); ctx.stroke();
            } else {
                ctx.fillStyle = root.foreground;
                ctx.beginPath(); ctx.arc(fx, fy, fr, 0, Math.PI * 2); ctx.fill();
            }

            // ---- Yeux et sourcils ----
            var blink = (t % 4.3) < 0.14 && m !== "speaking" && m !== "muted";
            var eyeY = top + dia * 0.36, eyeH = dia * 0.15, eyeDx = 0;
            if (working) { eyeY = top + dia * 0.3; eyeDx = dia * 0.05; }
            if (act === "search") { eyeY = top + dia * 0.33; eyeDx = Math.sin(t * 2.2) * dia * 0.07; }
            if (act === "read") {
                // Le regard parcourt une ligne, puis revient à gauche : une lecture, pas un balayage.
                eyeY = top + dia * 0.42;
                eyeDx = (((t * 0.9) % 1) - 0.5) * dia * 0.13;
            }
            if (act === "write" || act === "code" || act === "run") { eyeY = top + dia * 0.42; eyeDx = -dia * 0.05; }
            if (act === "mail") { eyeY = top + dia * 0.40; eyeDx = 0; }
            if (m === "listening") eyeH = dia * 0.2;
            if (m === "acting") eyeH = dia * 0.08;
            if (m === "waiting") { eyeH = dia * 0.18; eyeY = top + dia * 0.38; }
            if (m === "ignored") eyeDx = -dia * 0.07;
            var gap = dia * 0.17, eyeW = dia * 0.11;
            ctx.fillStyle = root.tiny ? root.foreground : root.background;
            ctx.strokeStyle = root.tiny ? root.foreground : root.background;
            for (var side = -1; side <= 1; side += 2) {
                var ex = fx + side * gap + eyeDx;
                if (m === "muted" || act === "dream") {
                    ctx.lineWidth = Math.max(2, dia * 0.045);
                    ctx.beginPath(); ctx.arc(ex, eyeY - dia * 0.02, eyeW * 0.6, Math.PI * 0.15, Math.PI * 0.85); ctx.stroke();
                } else {
                    canvas.oval(ctx, ex, eyeY, eyeW / 2, (blink ? eyeH * 0.12 : eyeH) / 2);
                }
                if (m === "waiting" || m === "error") {
                    ctx.lineWidth = Math.max(2, dia * 0.04);
                    var by = eyeY - eyeH / 2 - dia * (m === "waiting" ? 0.1 : 0.07);
                    ctx.beginPath();
                    if (m === "error") {
                        // Sourcils inquiets : relevés vers le milieu du front.
                        ctx.moveTo(ex - side * eyeW * 0.9, by - dia * 0.035);
                        ctx.lineTo(ex + side * eyeW * 0.9, by + dia * 0.02);
                    } else {
                        ctx.moveTo(ex - side * eyeW * 0.9, by);
                        ctx.lineTo(ex + side * eyeW * 0.9, by - dia * 0.015);
                    }
                    ctx.stroke();
                }
            }

            // ---- « z » du rêve, au-dessus de la tête ----
            if (act === "dream") {
                ctx.strokeStyle = Color.accent;
                ctx.lineWidth = Math.max(1.5, dia * 0.03);
                for (var z = 0; z < 3; z++) {
                    var montee = ((t * 0.5 + z * 0.33) % 1);
                    var zy = fy - fr * 0.75 - montee * dia * 0.45;
                    var zx = fx + fr * 0.62 + montee * dia * 0.12;
                    var zs = dia * (0.05 + z * 0.012);
                    ctx.globalAlpha = Math.min(1, (1 - montee) * 1.6) * 0.9;
                    ctx.beginPath();
                    ctx.moveTo(zx - zs / 2, zy - zs / 2);
                    ctx.lineTo(zx + zs / 2, zy - zs / 2);
                    ctx.lineTo(zx - zs / 2, zy + zs / 2);
                    ctx.lineTo(zx + zs / 2, zy + zs / 2);
                    ctx.stroke();
                }
                ctx.globalAlpha = 1;
                ctx.strokeStyle = root.background;
            }

            // ---- Bouche ----
            var mx = fx + (m === "ignored" ? -dia * 0.04 : 0), my = top + dia * 0.66, mw = dia * 0.4;
            ctx.strokeStyle = ctx.fillStyle = root.tiny ? root.foreground : root.background;
            ctx.lineWidth = Math.max(2, dia * 0.05);
            if (m === "speaking") {
                canvas.oval(ctx, mx, my + dia * 0.02, mw * 0.24, Math.max(dia * 0.015, dia * (0.02 + lv * 0.16) / 2));
            } else if (act === "dream") {
                ctx.beginPath(); ctx.arc(mx, my - dia * 0.06, mw * 0.3, Math.PI * 0.25, Math.PI * 0.75); ctx.stroke();
            } else if (act === "run") {
                // Invite de terminal : le chevron et son curseur.
                ctx.lineWidth = Math.max(2, dia * 0.06);
                ctx.beginPath();
                ctx.moveTo(mx - mw * 0.34, my - dia * 0.075); ctx.lineTo(mx - mw * 0.06, my);
                ctx.lineTo(mx - mw * 0.34, my + dia * 0.075); ctx.stroke();
                if ((t % 1) < 0.6) {
                    ctx.beginPath(); ctx.moveTo(mx + mw * 0.08, my + dia * 0.075);
                    ctx.lineTo(mx + mw * 0.36, my + dia * 0.075); ctx.stroke();
                }
            } else if (act === "code") {
                // Accolades : ce qu'elle écrit est du code, pas une phrase.
                ctx.lineWidth = Math.max(2, dia * 0.045);
                for (var br = -1; br <= 1; br += 2) {
                    var bx = mx + br * mw * 0.26, bend = br * mw * 0.1;
                    ctx.beginPath();
                    // Les pointes regardent le centre, le ventre de l'accolade vers l'extérieur.
                    ctx.moveTo(bx - bend, my - dia * 0.075);
                    ctx.quadraticCurveTo(bx + bend, my - dia * 0.042, bx + bend, my);
                    ctx.quadraticCurveTo(bx + bend, my + dia * 0.042, bx - bend, my + dia * 0.075);
                    ctx.stroke();
                }
                if ((t % 0.9) < 0.5) {
                    ctx.beginPath(); ctx.moveTo(mx, my - dia * 0.04); ctx.lineTo(mx, my + dia * 0.04); ctx.stroke();
                }
            } else if (act === "write") {
                // Curseur d'écriture qui clignote, et le début d'une ligne.
                ctx.beginPath(); ctx.moveTo(mx - mw * 0.3, my); ctx.lineTo(mx + mw * 0.05, my); ctx.stroke();
                if ((t % 0.9) < 0.5) {
                    ctx.beginPath(); ctx.moveTo(mx + mw * 0.18, my - dia * 0.05);
                    ctx.lineTo(mx + mw * 0.18, my + dia * 0.05); ctx.stroke();
                }
            } else if (act === "mail") {
                // Enveloppe : rectangle et rabat.
                var ew = mw * 0.62, eh = ew * 0.62;
                ctx.beginPath(); ctx.rect(mx - ew / 2, my - eh / 2, ew, eh); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(mx - ew / 2, my - eh / 2);
                ctx.lineTo(mx, my + eh * 0.12); ctx.lineTo(mx + ew / 2, my - eh / 2); ctx.stroke();
            } else if (act === "read") {
                // Une ligne de texte parcourue : trois traits, celui qu'elle lit est net.
                var lit = Math.floor(t * 1.2) % 3;
                for (var ln = 0; ln < 3; ln++) {
                    ctx.globalAlpha = ln === lit ? 1 : 0.3;
                    var lw = mw * (ln === 1 ? 0.5 : 0.36);
                    ctx.beginPath();
                    ctx.moveTo(mx - lw / 2, my - dia * 0.03 + ln * dia * 0.055);
                    ctx.lineTo(mx + lw / 2, my - dia * 0.03 + ln * dia * 0.055);
                    ctx.stroke();
                }
                ctx.globalAlpha = 1;
            } else if (m === "listening" || m === "acting") {
                ctx.beginPath(); ctx.moveTo(mx - mw * 0.25, my); ctx.lineTo(mx + mw * 0.25, my); ctx.stroke();
            } else if (working) {
                ctx.beginPath(); ctx.moveTo(mx - mw * 0.2, my + dia * 0.02); ctx.lineTo(mx + mw * 0.22, my - dia * 0.015); ctx.stroke();
            } else if (m === "waiting") {
                canvas.oval(ctx, mx, my + dia * 0.02, dia * 0.045, dia * 0.055);
            } else if (m === "muted") {
                ctx.beginPath(); ctx.moveTo(mx - mw * 0.14, my + dia * 0.01); ctx.lineTo(mx + mw * 0.14, my + dia * 0.01); ctx.stroke();
            } else if (m === "error") {
                ctx.beginPath(); ctx.arc(mx, my + dia * 0.12, mw * 0.32, Math.PI * 1.22, Math.PI * 1.78); ctx.stroke();
            } else {
                ctx.beginPath(); ctx.arc(mx, my - dia * 0.08, mw * (m === "ignored" ? 0.28 : 0.4), Math.PI * 0.22, Math.PI * 0.78); ctx.stroke();
            }
        }
    }
}
