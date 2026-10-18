import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Journal d'Alison, lisible et fouillable (maquette validée le 13/09). Le texte brut du moteur
// est découpé ici : une ligne par événement, regroupée par jour, heure seule en colonne, une
// famille par ligne (Échanges, Voix, Réveil, Sécurité) avec son symbole. La couleur ne sert
// qu'au sens : accent = tes échanges, urgence = refus et échecs, atténué = bruit technique.
// Filtres, recherche, copie du journal. Ouvert sur les lignes les plus récentes, en bas.
ColumnLayout {
    id: journal
    required property var app
    property string filter: "all"
    property string query: ""
    spacing: Style.spacing.md

    readonly property var families: [
        { key: "all", label: (app.tr.filter_all || ""), glyph: "" },
        { key: "echange", label: (app.tr.filter_exchanges || ""), glyph: "" },
        { key: "voix", label: (app.tr.filter_voice || ""), glyph: "" },
        { key: "reveil", label: (app.tr.filter_wake || ""), glyph: "" },
        { key: "securite", label: (app.tr.filter_security || ""), glyph: "" }
    ]
    readonly property var glyphs: ({ echange: "", voix: "", reveil: "", securite: "" })

    // [famille, aspect] : aspect = message | normal | bruit | alerte. Les lignes récentes portent
    // leur étiquette `[famille/aspect]` (posée par le moteur, quelle que soit la langue) ; cette
    // lecture du texte ne sert plus qu'aux lignes d'avant le 17/09.
    function classify(msg) {
        if (/^(REFUS |refus natif|échec après)/.test(msg) || /^proposition #\d+ REFUSÉE/.test(msg)) return ["securite", "alerte"];
        if (/^(proposition|outil|action liste blanche)/.test(msg)) return ["securite", "normal"];
        if (/^mot d'éveil écarté/.test(msg)) return ["reveil", "bruit"];
        if (/^mot d'éveil/.test(msg)) return ["reveil", "normal"];
        if (/^(transcription prête|Réglage Voxtype)/.test(msg) || /^transcription en [\d.]+s : ''$/.test(msg)) return ["voix", "bruit"];
        if (/^(transcription|voix|faster-whisper)/.test(msg)) return ["voix", "normal"];
        if (/^(demande|réponse|ignoré)/.test(msg)) return ["echange", "message"];
        return ["echange", "normal"];
    }
    // Mesures techniques sorties de la phrase en petites étiquettes ; citations 'x' en « x ».
    function split(msg) {
        var tags = [];
        msg = msg.replace(/\s*\(logprob ([-\d.]+), no_speech [\d.]+, voix (\d+), fond (\d+)\)/, function (all, lp, v, f) {
            tags.push((app.tr.tag_confidence || "") + Number(lp).toFixed(2), (app.tr.tag_voice || "") + v, (app.tr.tag_noise || "") + f);
            return "";
        });
        msg = msg.replace(/\s*\(logprob ([-\d.]+)[^)]*\)/, function (all, lp) {
            tags.push((app.tr.tag_confidence || "") + Number(lp).toFixed(2));
            return "";
        });
        msg = msg.replace(/:?\s*confiance \[([^\]]*)\]/, function (all, list) {
            tags.push((app.tr.tag_words || "") + list.split(",").map(function (x) { return x.trim(); }).join(" · "));
            return "";
        });
        msg = msg.replace(/(^|\s)'([^']*)'(?=\s|$)/g, function (all, before, inner) { return before + "« " + inner + " »"; });
        return { text: msg.replace(/\s+:\s*$/, ""), tags: tags.join("|") };
    }
    function dayLabel(day) {
        var today = Qt.formatDate(new Date(), "yyyy-MM-dd");
        var yesterday = Qt.formatDate(new Date(Date.now() - 86400000), "yyyy-MM-dd");
        var date = new Date(day + "T12:00:00");
        var name = Qt.locale(app.lang === "en" ? "en_US" : "fr_FR").toString(date, "dddd d MMMM");
        return day === today ? (app.tr.today || "") + name : (day === yesterday ? (app.tr.yesterday || "") + name : name);
    }
    function rebuild() {
        rows.clear();
        var q = query.trim().toLowerCase(), total = 0, days = {};
        var lines = (app.journalText || "").split("\n");
        for (var i = 0; i < lines.length; i++) {
            var m = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) (?:\[(\w+)\/(\w+)\] )?(.*)$/.exec(lines[i]);
            if (!m)
                continue;
            total++;
            var kind = m[3] ? [m[3], m[4]] : classify(m[5]);
            if (filter !== "all" && kind[0] !== filter)
                continue;
            if (q && m[5].toLowerCase().indexOf(q) < 0)
                continue;
            var parts = split(m[5]);
            if (!(m[1] in days))
                days[m[1]] = dayLabel(m[1]);   // un libellé (et une locale) par jour, pas par ligne
            rows.append({ day: days[m[1]], time: m[2], family: kind[0], look: kind[1], text: parts.text, tags: parts.tags });
        }
        totalLines = total;
        view.scrollToEnd();
    }
    property int totalLines: 0
    // Échap dans le journal efface d'abord la recherche ; vrai si c'est ce qu'il a fait.
    function consumeEscape() {
        if (search.text === "")
            return false;
        search.text = "";
        return true;
    }
    onFilterChanged: rebuild()
    // La recherche attend une courte pause de frappe : 300 lignes reconstruites à chaque touche.
    onQueryChanged: queryTimer.restart()
    Timer {
        id: queryTimer
        interval: 150
        onTriggered: journal.rebuild()
    }
    onVisibleChanged: if (visible) view.scrollToEnd()
    Connections {
        target: journal.app
        function onJournalTextChanged() { journal.rebuild(); }
        function onLangChanged() { journal.rebuild(); }
    }
    ListModel { id: rows }

    // ---- Filtres ----
    Flow {
        Layout.fillWidth: true
        spacing: Style.space(6)
        Repeater {
            model: journal.families
            Rectangle {
                id: pill
                required property var modelData
                readonly property bool on: journal.filter === modelData.key
                implicitHeight: Style.space(24)
                implicitWidth: pillText.implicitWidth + Style.space(20)
                radius: journal.app.rounded(12)
                color: on ? Util.alpha(Color.accent, 0.14) : (pillMouse.containsMouse ? Util.alpha(Color.menu.text, 0.06) : Style.normalFill)
                border.width: Style.controlBorderWidth(pill.activeFocus, pillMouse.containsMouse)
                border.color: pill.activeFocus ? Style.focusBorderColor : (on ? Util.alpha(Color.accent, 0.55) : Util.alpha(Color.menu.text, 0.22))
                activeFocusOnTab: true
                Keys.onReturnPressed: journal.filter = pill.modelData.key
                Keys.onEnterPressed: journal.filter = pill.modelData.key
                Keys.onSpacePressed: journal.filter = pill.modelData.key
                Text {
                    id: pillText
                    anchors.centerIn: parent
                    text: (pill.modelData.glyph ? pill.modelData.glyph + "  " : "") + pill.modelData.label
                    color: pill.on ? Color.accent : Color.menu.text
                    opacity: pill.on ? 1 : 0.7
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.caption
                    font.bold: pill.on
                }
                MouseArea {
                    id: pillMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: journal.filter = pill.modelData.key
                }
                Accessible.role: Accessible.RadioButton
                Accessible.checked: on
                Accessible.name: journal.app.t("filter_name", modelData.label)
            }
        }
    }

    // ---- Recherche et copie ----
    RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md
        // Champ du kit Omarchy : bordure, fond et anneau de focus aux jetons du thème.
        TextField {
            id: search
            Layout.fillWidth: true
            placeholderText: (journal.app.tr.journal_search || "")
            foreground: Color.menu.text
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.bodySmall
            onTextChanged: journal.query = text
        }
        Text {
            id: copyLabel
            text: copiedTimer.running ? (journal.app.tr.copied || "") : (journal.app.tr.copy || "")
            color: copiedTimer.running || copyLabel.activeFocus ? Color.accent : Color.menu.text
            opacity: copyMouse.containsMouse || copiedTimer.running || copyLabel.activeFocus ? 1 : 0.7
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
            font.underline: !copiedTimer.running
            activeFocusOnTab: true
            Keys.onReturnPressed: { journal.app.copyText(journal.app.journalText); copiedTimer.restart(); }
            Keys.onEnterPressed: { journal.app.copyText(journal.app.journalText); copiedTimer.restart(); }
            Keys.onSpacePressed: { journal.app.copyText(journal.app.journalText); copiedTimer.restart(); }
            MouseArea {
                id: copyMouse
                anchors.fill: parent
                anchors.margins: -Style.space(4)
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { journal.app.copyText(journal.app.journalText); copiedTimer.restart(); }
            }
            Timer { id: copiedTimer; interval: 1400 }
            Accessible.role: Accessible.Button
            Accessible.name: (journal.app.tr.journal_copy || "")
        }
    }

    // ---- Lignes ----
    ListView {
        id: view
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: Style.space(1)
        boundsBehavior: Flickable.StopAtBounds
        model: rows
        QQC.ScrollBar.vertical: QQC.ScrollBar {}
        function scrollToEnd() {
            Qt.callLater(function () { view.positionViewAtEnd(); });
        }

        section.property: "day"
        section.delegate: Text {
            required property string section
            width: view.width
            topPadding: Style.space(8)
            bottomPadding: Style.space(4)
            text: section.toUpperCase()
            color: Color.menu.text
            opacity: 0.5
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
            font.letterSpacing: 1
        }

        delegate: Rectangle {
            id: row
            required property string time
            required property string family
            required property string look
            required property string text
            required property string tags
            readonly property color tone: look === "alerte" ? Color.urgent : (look === "bruit" ? Color.muted : Color.menu.text)
            width: view.width - Style.space(12)
            implicitHeight: content.implicitHeight + Style.space(8)
            radius: journal.app.rounded(6)
            color: rowHover.hovered ? Util.alpha(Color.menu.text, 0.05) : "transparent"
            HoverHandler { id: rowHover }
            RowLayout {
                id: content
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(6)
                anchors.rightMargin: Style.space(6)
                spacing: Style.space(8)
                Text {
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredWidth: Style.space(62)
                    text: row.time
                    color: Color.menu.text
                    opacity: 0.45
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.bodySmall
                    font.features: { "tnum": 1 }
                }
                Text {
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredWidth: Style.space(16)
                    horizontalAlignment: Text.AlignHCenter
                    text: journal.glyphs[row.family] || ""
                    color: row.look === "message" ? Color.accent : row.tone
                    opacity: row.look === "normal" ? 0.75 : 1
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.bodySmall
                }
                // Texte sur toute la largeur, étiquettes de mesure dessous (pas de largeur
                // « naturelle » calculée sur un texte qui se replie : boucle de liaison).
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Style.space(3)
                    Text {
                        Layout.fillWidth: true
                        text: row.text
                        wrapMode: Text.Wrap
                        color: row.tone
                        opacity: row.look === "normal" ? 0.85 : 1
                        font.family: Style.font.menuFamily
                        font.pixelSize: Style.font.bodySmall
                    }
                    Flow {
                    Layout.fillWidth: true
                    visible: row.tags !== ""
                    spacing: Style.space(4)
                    Repeater {
                        model: row.tags ? row.tags.split("|") : []
                        Rectangle {
                            required property string modelData
                            implicitWidth: tagText.implicitWidth + Style.space(10)
                            implicitHeight: tagText.implicitHeight + Style.space(2)
                            radius: journal.app.rounded(4)
                            color: "transparent"
                            border.width: Math.max(1, Style.normalBorderWidth)
                            border.color: Util.alpha(Color.menu.text, 0.2)
                            Text {
                                id: tagText
                                anchors.centerIn: parent
                                text: parent.modelData
                                color: Color.menu.text
                                opacity: 0.6
                                font.family: Style.font.menuFamily
                                font.pixelSize: Style.font.caption
                            }
                        }
                    }
                    }
                }
            }
        }

        Text {
            anchors.centerIn: parent
            visible: view.count === 0
            text: journal.app.journalText === "" ? (journal.app.tr.journal_loading || "") : (journal.app.tr.journal_empty || "")
            color: Color.menu.text
            opacity: 0.6
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.bodySmall
        }
    }

    Text {
        Layout.fillWidth: true
        text: view.count + (view.count > 1 ? (journal.app.tr.journal_lines || "") : (journal.app.tr.journal_line || "")) + (journal.app.tr.journal_of || "") + journal.totalLines
        color: Color.menu.text
        opacity: 0.45
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.caption
    }
}
