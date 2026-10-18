import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Code.js" as Code

// Fil de la conversation, sur toute la hauteur libre. Quatre sortes de lignes :
//   assistant : bulle teintée, mise en forme rendue (gras, listes, code), bouton copier au survol ;
//   user      : bulle au contour fin, alignée à droite ;
//   tools     : outils lancés d'affilée, regroupés sur une ligne repliable (« 2 outils ») ;
//   ignored   : phrase de la pièce écartée, en italique atténué, sans bulle.
// L'heure s'affiche à côté du nom quand elle est connue. Jamais de bordure latérale colorée.
ListView {
    id: list
    required property var app
    clip: true
    spacing: Style.spacing.lg
    boundsBehavior: Flickable.StopAtBounds
    model: app.messageModel
    function scrollToEnd() {
        Qt.callLater(function () { list.positionViewAtEnd(); });
    }
    function clock(at) {
        return at > 0 ? Qt.formatTime(new Date(at * 1000), "HH:mm") : "";
    }
    // Markdown de l'agent, SANS images : une image distante chargée à l'affichage ferait partir une
    // adresse choisie par l'agent. Les images deviennent des vignettes « Afficher » sous la bulle,
    // téléchargées par le moteur au clic seulement.
    readonly property var imagePattern: /!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?[^)]*\)/g
    // Vérifié sur Qt 6.11 (banc hors shell, 13/09) : le Markdown de TextEdit JETTE le HTML brut, sans
    // requête réseau, mais avale aussi le texte qui ressemble à une balise (« agent <nom> ») ; et la
    // couleur des liens ne se règle pas (palette ignorée : bleu illisible sur fond sombre). Donc, hors
    // code : `<` échappé, lien Markdown réduit à « titre ↗ », adresse nue à « site ↗ ». Les liens
    // s'ouvrent par les pastilles sous la bulle.
    function markdown(text) {
        return text.replace(new RegExp(imagePattern.source, "g"), "").split(/(```[\s\S]*?```|`[^`\n]*`)/).map(function (part, i) {
            if (i % 2 === 1)
                return part;   // code : laissé tel quel
            return part
                .replace(/\[([^\]]+)\]\(\s*<?(https?:\/\/[^)\s>]+)>?[^)]*\)/g, "$1 ↗")
                .replace(/(^|[^(\[<\w])(https?:\/\/[^\s)\]>"'«»]+)/g, function (all, before, url) {
                    return before + host(url.replace(/[.,;:!?]+$/, "")) + " ↗";
                })
                .replace(/</g, "\\<");
        }).join("");
    }
    function showAllImages() {
        for (var i = 0; i < count; i++) {
            var item = app.messageModel.get(i);
            if (item.role === "assistant")
                imagesOf(item.text).forEach(function (image) { if (!app.images[image.url]) app.showImage(image.url); });
        }
    }
    function host(url) {
        var m = /^https?:\/\/([^\/?#:]+)/i.exec(url);
        return m ? m[1].toLowerCase() : "";
    }
    function imagesOf(text) {
        var found = [], m, re = new RegExp(imagePattern.source, "g");
        while ((m = re.exec(text)) !== null)
            if (/^https:\/\//i.test(m[2]) && found.every(function (i) { return i.url !== m[2]; }))
                found.push({ url: m[2], alt: m[1], host: host(m[2]) });
        return found.slice(0, 4);
    }
    // Liens web de la réponse (Markdown puis adresses nues), sans doublon ni image : quatre au plus.
    // { url, label } : le titre du lien s'il en a un, sinon le site.
    function linksOf(text) {
        var plain = text.replace(new RegExp(imagePattern.source, "g"), "");
        var found = [], m;
        var md = /\[([^\]]+)\]\(\s*<?(https?:\/\/[^)\s>]+)>?[^)]*\)/g;
        while ((m = md.exec(plain)) !== null)
            found.push({ url: m[2], label: m[1].replace(/[*_`]/g, "").trim() });
        var bare = /(^|[^(\[<\w])(https?:\/\/[^\s)\]>"'«»]+)/g;
        var rest = plain.replace(md, "");
        while ((m = bare.exec(rest)) !== null) {
            var url = m[2].replace(/[.,;:!?]+$/, "");
            found.push({ url: url, label: host(url) });
        }
        return found.filter(function (link, i) {
            return found.findIndex(function (other) { return other.url === link.url; }) === i;
        }).slice(0, 4);
    }
    // Fil collé en bas tant que tu n'as pas remonté : une bulle mise en forme ou une image qui
    // s'agrandit après coup ne cache plus la fin de la conversation.
    property bool stickToEnd: true
    onMovementEnded: stickToEnd = atYEnd
    onContentHeightChanged: if (stickToEnd) scrollToEnd()
    onCountChanged: { stickToEnd = true; scrollToEnd(); }
    QQC.ScrollBar.vertical: QQC.ScrollBar {}

    delegate: Item {
        id: line
        required property int index
        required property string role
        required property string text
        required property real at
        required property int count
        required property bool open
        readonly property bool mine: role === "user"
        readonly property bool isTools: role === "tools"
        readonly property bool isIgnored: role === "ignored"
        readonly property bool isMemory: role === "memory"
        readonly property bool isRecall: role === "recall"
        readonly property bool isPreview: role === "preview"
        readonly property bool isMessage: !isTools && !isIgnored && !isMemory && !isRecall && !isPreview
        // Bulle en cours de flux : les pastilles de liens et d'images attendent la fin de la
        // réponse, sinon elles sont recalculées sur tout le texte à chaque morceau reçu.
        readonly property bool inFlight: list.app.streaming && index === list.count - 1
        width: list.width - Style.space(12)
        height: isTools ? tools.implicitHeight
                        : (isIgnored ? ignoredText.implicitHeight
                                     : (isMemory ? memoryRow.implicitHeight
                                                 : (isRecall ? recallText.implicitHeight
                                                             : (isPreview ? previewRow.implicitHeight : message.implicitHeight))))

        // ---- Outils regroupés ----
        Column {
            id: tools
            visible: line.isTools
            width: parent.width
            spacing: Style.space(3)
            Text {
                id: toolsLabel
                text: (line.open ? "⌄ " : "› ") + line.count + (line.count > 1 ? list.app.tr.tools_many : list.app.tr.tools_one)
                color: toolsLabel.activeFocus ? Color.accent : Color.menu.text
                opacity: toolsMouse.containsMouse || toolsLabel.activeFocus ? 0.85 : 0.55
                activeFocusOnTab: true
                Keys.onReturnPressed: list.app.messageModel.setProperty(line.index, "open", !line.open)
                Keys.onEnterPressed: list.app.messageModel.setProperty(line.index, "open", !line.open)
                Keys.onSpacePressed: list.app.messageModel.setProperty(line.index, "open", !line.open)
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
                MouseArea {
                    id: toolsMouse
                    anchors.fill: parent
                    anchors.margins: -Style.space(4)
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: list.app.messageModel.setProperty(line.index, "open", !line.open)
                }
                Accessible.role: Accessible.Button
                Accessible.name: (line.open ? list.app.tr.tools_collapse : list.app.tr.tools_expand) + line.count + list.app.tr.tools_many
            }
            Repeater {
                model: line.open ? line.text.split("\n") : []
                Text {
                    required property string modelData
                    width: tools.width
                    leftPadding: Style.space(14)
                    text: modelData
                    elide: Text.ElideRight
                    color: Color.menu.text
                    opacity: 0.5
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.caption
                }
            }
        }

        // ---- Phrase de la pièce écartée ----
        Text {
            id: ignoredText
            visible: line.isIgnored
            width: parent.width
            text: list.app.t("ignored_line", line.text)
            wrapMode: Text.Wrap
            color: Color.muted
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
            font.italic: true
        }

        // ---- Conversation passée relue (lot C) ----
        Text {
            id: recallText
            visible: line.isRecall
            width: parent.width
            text: list.app.t("recall_used", line.text)
            wrapMode: Text.Wrap
            color: Color.menu.text
            opacity: 0.5
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
        }

        // ---- Fenêtre d'aperçu ouverte ----
        RowLayout {
            id: previewRow
            visible: line.isPreview
            width: parent.width
            spacing: Style.space(8)
            Text {
                Layout.fillWidth: true
                text: "◧ " + list.app.t("preview_open", line.text)
                wrapMode: Text.Wrap
                color: Color.accent
                opacity: 0.85
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
            }
            Button {
                visible: list.app.previewHost !== ""
                text: list.app.tr.preview_close
                focusable: true
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                fontSize: Style.font.caption
                onClicked: list.app.send("close_preview")
            }
        }

        // ---- Souvenir retenu ou retiré ----
        RowLayout {
            id: memoryRow
            visible: line.isMemory
            width: parent.width
            spacing: Style.space(8)
            Text {
                Layout.fillWidth: true
                text: line.isMemory ? list.app.t(line.text.charAt(0) === "+" ? "memory_kept" : "memory_removed", line.text.substring(1)) : ""
                wrapMode: Text.Wrap
                color: Color.accent
                opacity: 0.85
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
            }
            Button {
                visible: line.isMemory && line.text.charAt(0) === "+"
                text: list.app.tr.memory_undo
                focusable: true
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                fontSize: Style.font.caption
                onClicked: list.app.send("forget_memory", line.text.substring(1))
            }
        }

        // ---- Message ----
        Column {
            id: message
            visible: line.isMessage
            width: parent.width
            spacing: Style.space(5)
            RowLayout {
                width: parent.width
                layoutDirection: line.mine ? Qt.RightToLeft : Qt.LeftToRight
                spacing: Style.space(8)
                Text {
                    text: line.mine ? list.app.tr.you : list.app.speaker.toUpperCase()
                    color: line.mine ? Color.menu.text : Color.accent
                    opacity: line.mine ? 0.6 : 1
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 1
                }
                Text {
                    text: list.clock(line.at)
                    visible: text !== ""
                    color: Color.menu.text
                    opacity: 0.45
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.caption
                    font.features: { "tnum": 1 }
                }
                Item { Layout.fillWidth: true }
            }
            Rectangle {
                id: bubble
                anchors.right: line.mine ? parent.right : undefined
                // Ta bulle épouse ton texte (largeur naturelle mesurée, sans boucle de liaison), 85 % au plus.
                readonly property real mineWidth: Math.min(parent.width * 0.85, natural.advanceWidth + Style.space(30))
                width: line.mine ? mineWidth : parent.width
                height: body.implicitHeight + (line.mine ? Style.space(14) : Style.space(22))
                radius: list.app.rounded(9)
                color: line.mine ? "transparent" : Style.normalFill
                border.width: line.mine ? Style.normalBorderWidth : 0
                border.color: Util.alpha(Color.menu.text, 0.22)
                HoverHandler { id: bubbleHover }
                TextMetrics {
                    id: natural
                    text: line.mine ? line.text : ""
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.body
                }
                // Le message, découpé : le texte en Markdown, les clôtures ``` en blocs de code
                // colorés, repliables et copiables (Code.js). Ta bulle, elle, reste du texte brut.
                Column {
                    id: body
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: Style.space(13)
                    anchors.rightMargin: Style.space(13)
                    anchors.topMargin: line.mine ? Style.space(7) : Style.space(11)
                    spacing: Style.space(7)
                    Repeater {
                        model: Code.segments(line.text, line.mine)
                        Item {
                            id: segment
                            required property var modelData
                            readonly property bool isCode: segment.modelData.type === "code"
                            width: body.width
                            implicitHeight: segment.isCode ? codeBlock.implicitHeight : segmentText.implicitHeight
                            height: implicitHeight
                            TextEdit {
                                id: segmentText
                                visible: !segment.isCode
                                width: parent.width
                                text: line.mine ? segment.modelData.body : list.markdown(segment.modelData.body)
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextEdit.Wrap
                                textFormat: line.mine ? TextEdit.PlainText : TextEdit.MarkdownText
                                horizontalAlignment: line.mine ? TextEdit.AlignRight : TextEdit.AlignLeft
                                color: Color.menu.text
                                selectionColor: Style.selectionFill
                                font.family: Style.font.menuFamily
                                font.pixelSize: Style.font.body
                            }
                            CodeBlock {
                                id: codeBlock
                                visible: segment.isCode
                                width: parent.width
                                app: list.app
                                lang: segment.modelData.lang
                                body: segment.modelData.body
                            }
                        }
                    }
                }
                // Copier la réponse (texte brut de l'agent), au survol.
                Rectangle {
                    visible: !line.mine && (bubbleHover.hovered || copyMouse.containsMouse) && line.text !== ""
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: Style.space(6)
                    width: copyLabel.implicitWidth + Style.space(12)
                    height: copyLabel.implicitHeight + Style.space(4)
                    radius: list.app.rounded(5)
                    color: Color.menu.background
                    border.width: Style.normalBorderWidth
                    border.color: Util.alpha(Color.menu.text, 0.25)
                    Text {
                        id: copyLabel
                        anchors.centerIn: parent
                        text: copied.running ? list.app.tr.copied : list.app.tr.copy
                        color: copied.running ? Color.accent : Color.menu.text
                        opacity: copied.running ? 1 : 0.7
                        font.family: Style.font.menuFamily
                        font.pixelSize: Style.font.caption
                    }
                    MouseArea {
                        id: copyMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { list.app.copyText(line.text); copied.restart(); }
                    }
                    Timer { id: copied; interval: 1400 }
                    Accessible.role: Accessible.Button
                    Accessible.name: list.app.tr.copy_reply
                }
            }

            // ---- Liens à ouvrir ----
            Flow {
                width: parent.width
                visible: !line.mine && linkRepeater.count > 0
                spacing: Style.space(6)
                Repeater {
                    id: linkRepeater
                    model: line.mine || line.inFlight ? [] : list.linksOf(line.text)
                    Rectangle {
                        id: linkChip
                        required property var modelData
                        implicitHeight: Style.space(24)
                        implicitWidth: Math.min(linkText.implicitWidth + Style.space(18), message.width)
                        radius: list.app.rounded(12)
                        color: linkMouse.containsMouse ? Util.alpha(Color.accent, 0.14) : Style.normalFill
                        border.width: Style.normalBorderWidth
                        border.color: linkMouse.containsMouse ? Util.alpha(Color.accent, 0.55) : Util.alpha(Color.menu.text, 0.22)
                        Text {
                            id: linkText
                            anchors.centerIn: parent
                            width: Math.min(implicitWidth, message.width - Style.space(18))
                            elide: Text.ElideRight
                            // L'hôte reste toujours visible : c'est lui qui recevra la visite.
                            text: "↗ " + (linkChip.modelData.label.length > 36
                                          ? linkChip.modelData.label.substring(0, 35) + "…" : linkChip.modelData.label)
                                  + (linkChip.modelData.label.toLowerCase().indexOf(list.host(linkChip.modelData.url)) >= 0
                                     ? "" : " · " + list.host(linkChip.modelData.url))
                            color: linkMouse.containsMouse ? Color.accent : Color.menu.text
                            opacity: linkMouse.containsMouse ? 1 : 0.75
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.caption
                        }
                        MouseArea {
                            id: linkMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: list.app.openUrl(linkChip.modelData.url)
                        }
                        PanelToolTip {
                            visible: linkMouse.containsMouse
                            text: list.app.t("open_in_browser", linkChip.modelData.url)
                        }
                        Accessible.role: Accessible.Link
                        Accessible.name: list.app.t("open_link", modelData.url)
                    }
                }
                // Aperçu : la première page de la réponse, dans une fenêtre posée à côté du panneau.
                Rectangle {
                    id: previewChip
                    visible: linkRepeater.count > 0
                    implicitHeight: Style.space(24)
                    implicitWidth: previewText.implicitWidth + Style.space(18)
                    radius: list.app.rounded(12)
                    color: previewMouse.containsMouse ? Util.alpha(Color.accent, 0.14) : Style.normalFill
                    border.width: Style.normalBorderWidth
                    border.color: previewMouse.containsMouse ? Util.alpha(Color.accent, 0.55) : Util.alpha(Color.menu.text, 0.22)
                    Text {
                        id: previewText
                        anchors.centerIn: parent
                        text: "◧ " + list.app.tr.preview_chip
                        color: previewMouse.containsMouse ? Color.accent : Color.menu.text
                        opacity: previewMouse.containsMouse ? 1 : 0.75
                        font.family: Style.font.menuFamily
                        font.pixelSize: Style.font.caption
                    }
                    MouseArea {
                        id: previewMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var links = list.linksOf(line.text);
                            if (links.length > 0)
                                list.app.send("preview_url", links[0].url);
                        }
                    }
                    PanelToolTip {
                        visible: previewMouse.containsMouse
                        text: list.app.tr.preview_tip
                    }
                    Accessible.role: Accessible.Button
                    Accessible.name: list.app.tr.preview_chip
                }
            }

            // ---- Images, au clic ----
            Repeater {
                model: line.mine || line.inFlight ? [] : list.imagesOf(line.text)
                Rectangle {
                    id: picture
                    required property var modelData
                    readonly property var info: list.app.images[modelData.url] || null
                    readonly property bool ready: info !== null && info.path !== undefined
                    width: Math.min(message.width, Style.space(380))
                    height: ready ? shown.height + Style.space(8) : placeholder.implicitHeight + Style.space(16)
                    radius: list.app.rounded(9)
                    color: ready ? "transparent" : Style.normalFill
                    border.width: ready ? 0 : Style.normalBorderWidth
                    border.color: Util.alpha(Color.menu.text, 0.22)
                    RowLayout {
                        id: placeholder
                        visible: !picture.ready
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: Style.space(12)
                        anchors.rightMargin: Style.space(8)
                        spacing: Style.space(8)
                        Text {
                            Layout.fillWidth: true
                            // Adresse complète visible avant le clic : c'est elle qui partira sur le réseau.
                            elide: Text.ElideMiddle
                            text: picture.info && picture.info.error
                                  ? list.app.t("image_refused", picture.info.error)
                                  : (picture.modelData.alt ? picture.modelData.alt + " · " : list.app.tr.image_word + " · ") + picture.modelData.url
                            color: picture.info && picture.info.error ? Color.urgent : Color.menu.text
                            opacity: picture.info && picture.info.error ? 1 : 0.75
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.caption
                        }
                        Button {
                            visible: !(picture.info && picture.info.error)
                            text: picture.info && picture.info.loading ? list.app.tr.image_loading : list.app.tr.image_show
                            focusable: true
                            enabled: !(picture.info && picture.info.loading)
                            bordered: true
                            foreground: Color.menu.text
                            fontFamily: Style.font.menuFamily
                            fontSize: Style.font.caption
                            tooltipText: list.app.t("image_show_tip", picture.modelData.url)
                            onClicked: list.app.showImage(picture.modelData.url)
                        }
                    }
                    Image {
                        id: shown
                        visible: picture.ready
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.topMargin: Style.space(4)
                        width: parent.width
                        height: status === Image.Ready && implicitWidth > 0
                                ? Math.min(Style.space(280), width * implicitHeight / implicitWidth) : 0
                        source: picture.ready ? Util.fileUrl(picture.info.path) : ""   // espaces et accents du chemin encodés
                        fillMode: Image.PreserveAspectFit
                        horizontalAlignment: Image.AlignLeft
                        asynchronous: true
                        sourceSize.width: Style.space(760)
                        MouseArea {
                            id: pictureMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: list.app.openUrl(picture.modelData.url)
                        }
                        PanelToolTip {
                            visible: pictureMouse.containsMouse
                            text: (picture.modelData.alt || list.app.tr.image_word) + list.app.t("image_open", picture.modelData.url)
                        }
                    }
                }
            }
        }
    }

    footer: Item {
        // Indicateur d'attente tant qu'aucun mot n'est arrivé.
        readonly property bool shown: list.app.mood === "thinking" && !list.app.streaming
        width: list.width
        height: shown ? Style.space(28) : 0
        Text {
            visible: parent.shown
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: list.app.t("thinking_footer", list.app.speaker)
            color: Color.menu.text
            opacity: 0.6
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.bodySmall
            font.italic: true
        }
    }

    // Fondu en haut du fil : un message qui remonte s'efface au lieu d'être tranché net.
    Rectangle {
        parent: list
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Style.space(34)
        visible: !list.atYBeginning
        z: 2
        gradient: Gradient {
            GradientStop { position: 0; color: Color.menu.background }
            GradientStop { position: 1; color: Util.alpha(Color.menu.background, 0) }
        }
    }

    Text {
        anchors.centerIn: parent
        width: parent.width * 0.9
        visible: list.count === 0
        text: list.app.tr.hello
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        color: Color.menu.text
        opacity: 0.8
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.body
    }
}
