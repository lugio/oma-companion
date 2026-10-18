import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Code.js" as Code

// Bloc de code dans le fil : langage, coloration sobre aux jetons du thème, copier, ouvrir dans
// l'éditeur, et repliage automatique au-delà de vingt lignes pour ne pas noyer la conversation.
Rectangle {
    id: block
    required property var app
    required property string lang
    required property string body
    readonly property int lineCount: Code.lines(block.body)
    property bool folded: block.lineCount > Code.FOLD_LINES

    implicitHeight: column.implicitHeight
    radius: block.app.rounded(6)
    color: Color.menu.background
    border.width: Style.normalBorderWidth
    border.color: Util.alpha(Color.menu.text, 0.18)

    ColumnLayout {
        id: column
        anchors.fill: parent
        spacing: 0

        // En-tête : ce que c'est, et quoi en faire.
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Style.space(6)
            spacing: Style.space(8)
            Text {
                text: block.lang !== "" ? block.lang : block.app.tr.code_plain
                color: Color.accent
                opacity: 0.85
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
            }
            Text {
                text: block.app.t("code_lines", block.lineCount)
                color: Color.menu.text
                opacity: 0.4
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
            }
            Item { Layout.fillWidth: true }
            Button {
                visible: block.lineCount > Code.FOLD_LINES
                text: block.folded ? block.app.tr.code_unfold : block.app.tr.code_fold
                focusable: true
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                fontSize: Style.font.caption
                onClicked: block.folded = !block.folded
            }
            Button {
                text: copied.running ? block.app.tr.copied : block.app.tr.copy
                focusable: true
                foreground: copied.running ? Color.accent : Color.menu.text
                fontFamily: Style.font.menuFamily
                fontSize: Style.font.caption
                onClicked: { block.app.copyText(block.body); copied.restart(); }
            }
            Button {
                text: block.app.tr.code_open
                focusable: true
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                fontSize: Style.font.caption
                onClicked: block.app.openCode(block.lang, block.body)
            }
            Timer { id: copied; interval: 1400 }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Color.menu.text
            opacity: 0.12
        }

        // Replié : une ligne qui dit ce qu'on cache, et qui déplie au clic.
        Text {
            visible: block.folded
            Layout.fillWidth: true
            Layout.margins: Style.space(8)
            text: "▸ " + block.app.t("code_folded", block.lineCount)
            color: Color.menu.text
            opacity: 0.5
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: block.folded = false
            }
        }

        TextEdit {
            visible: !block.folded
            Layout.fillWidth: true
            Layout.margins: Style.space(8)
            // Les couleurs viennent du thème : le catalogue de coloration n'en connaît aucune.
            text: Code.highlight(block.body, block.lang,
                                 { keyword: String(Color.menu.text),
                                   literal: String(Color.accent),
                                   comment: String(Color.muted) })
            textFormat: TextEdit.RichText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            color: Color.menu.text
            selectionColor: Style.selectionFill
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
        }
    }
}
