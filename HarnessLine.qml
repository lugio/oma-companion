import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Pied du panneau : UNE ligne, toujours dans l'ordre des rangées du haut — QUI répond · le MODE ·
// chaque ACCÈS avec son état, et pour ce qui est fermé, par quoi. Tout vient du moteur.
// Il y avait deux lignes en deux vocabulaires (« assistant bridé · bac à sable système… » puis
// « rôle Compta · accès : … ») : la phrase du garde est maintenant dans Réglages › Mode, en
// infobulle ici. « détails » y mène. Couleur d'urgence du thème quand la lecture n'est pas
// filtrée (cerveau sans garde possible) ou en Autonome (plus de carte) — là, la ligne dit pourquoi.
ColumnLayout {
    id: line
    required property var app
    readonly property bool unsafe: app.harnessUnsafe
    readonly property bool noCard: app.mode === "auto"
    readonly property string guardText: app.harness || (app.tr.guard_none || "")
    readonly property string summary: {
        if (line.unsafe)
            return line.guardText;
        var parts = [app.speaker];
        var modeLabel = app.modeLabels[app.mode] || app.mode;
        parts.push(line.noCard ? modeLabel + ", " + (app.tr.summary_no_card || "") : modeLabel);
        for (var i = 0; i < app.access.length; i++) {
            var a = app.access[i];
            var name = app.tr["access_" + a.key];
            if (a.on)
                parts.push(app.t("summary_on", name));
            else if (a.blocked !== "")
                parts.push(app.t("summary_shut", name, a.by));
            else if (!a.configured)
                parts.push(app.t("summary_missing", name));
        }
        return parts.join(" · ");
    }
    spacing: Style.spacing.xxs

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md

        Rectangle {
            Layout.preferredWidth: Style.space(7)
            Layout.preferredHeight: Style.space(7)
            Layout.alignment: Qt.AlignVCenter
            radius: width / 2
            color: line.unsafe || line.noCard ? Color.urgent : Color.accent
        }
        Text {
            id: summaryText
            Layout.fillWidth: true
            text: line.summary
            elide: Text.ElideRight
            maximumLineCount: 1
            color: line.unsafe ? Color.urgent : Color.menu.text
            opacity: line.unsafe ? 1 : 0.6
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
            HoverHandler { id: summaryHover }
            PanelToolTip {
                visible: summaryHover.hovered
                text: summaryText.truncated ? line.summary + "\n" + line.guardText : line.guardText
            }
        }
        Text {
            id: details
            text: (line.app.tr.details || "")
            color: details.activeFocus ? Color.accent : Color.menu.text
            opacity: detailsMouse.containsMouse || details.activeFocus ? 1 : 0.75
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
            font.underline: true
            activeFocusOnTab: true
            Keys.onReturnPressed: line.app.showSettings("mode")
            Keys.onEnterPressed: line.app.showSettings("mode")
            Keys.onSpacePressed: line.app.showSettings("mode")
            MouseArea {
                id: detailsMouse
                anchors.fill: parent
                anchors.margins: -Style.space(4)
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: line.app.showSettings("mode")
            }
            Accessible.role: Accessible.Link
            Accessible.name: (line.app.tr.details || "")
        }
    }
}
