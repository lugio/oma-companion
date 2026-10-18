import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Sous l'en-tête, DEUX rangées étiquetées, nommées comme les onglets des Réglages :
//
//   QUI répond  -> le RÔLE, dans l'en-tête, avec l'identité (PanelHeader)
//   JUSQU'OÙ    -> le MODE : cinq crans du plus fermé au plus ouvert, Autonome en dernier
//   À QUOI      -> les ACCÈS : maison, courrier, comptabilité — trois pastilles identiques
//
// Le mode se choisit ICI et nulle part ailleurs (il était aussi dans Réglages › Cerveau, avec un
// deuxième texte par cran — audit du 21/09). Les trois accès obéissent à la même règle et se lisent
// au même endroit ; la pastille allume ou éteint, les Réglages configurent.
// Active = fond et texte accent, point plein ; inactive = contour seul, texte atténué, point vide.
// Le mode et les accès n'existent que pour le cerveau Omarchy.
ColumnLayout {
    id: chips
    required property var app
    readonly property bool omarchy: app.provider === "omarchy"
    readonly property int chipHeight: Style.spacing.controlHeight
    spacing: Style.spacing.xs

    component RowLabel: Text {
        required property string text2
        text: text2
        color: Color.menu.text
        opacity: 0.42
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 1.4
    }

    component Chip: Rectangle {
        id: chip
        property string label: ""
        property bool on: false
        // Quatre états, et l'infobulle dit toujours POURQUOI : pas réglée (pointillés, pâle) ·
        // réglée mais éteinte (contour) · active (accent) · fermée par le mode ou le rôle (barrée).
        property bool missing: false
        property bool shut: false
        property string tip: ""
        signal toggled()
        implicitHeight: chips.chipHeight
        implicitWidth: chipRow.implicitWidth + Style.space(20)
        radius: chips.app.rounded(7)
        opacity: chip.shut ? 0.3 : (chip.missing ? 0.45 : 1)
        color: on ? Util.alpha(Color.accent, 0.14) : (!chip.shut && chipMouse.containsMouse ? Util.alpha(Color.menu.text, 0.06) : Style.normalFill)
        border.width: Style.controlBorderWidth(chip.activeFocus, chipMouse.containsMouse)
        border.color: chip.activeFocus ? Style.focusBorderColor : (on ? Util.alpha(Color.accent, 0.55) : Util.alpha(Color.menu.text, 0.22))
        activeFocusOnTab: !chip.shut
        Keys.onReturnPressed: if (!chip.shut) chip.toggled()
        Keys.onEnterPressed: if (!chip.shut) chip.toggled()
        Keys.onSpacePressed: if (!chip.shut) chip.toggled()
        Row {
            id: chipRow
            anchors.centerIn: parent
            spacing: Style.space(7)
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(7)
                height: width
                radius: width / 2
                color: chip.on ? Color.accent : "transparent"
                border.width: Math.max(1, Style.space(1.5))
                border.color: chip.on ? Color.accent : Util.alpha(Color.menu.text, 0.6)
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: chip.label
                color: chip.on ? Color.accent : Color.menu.text
                opacity: chip.on ? 1 : 0.65
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.bodySmall
                font.strikeout: chip.shut
                font.bold: chip.on
            }
        }
        MouseArea {
            id: chipMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: chip.shut ? Qt.ArrowCursor : Qt.PointingHandCursor
            onClicked: if (!chip.shut) chip.toggled()
        }
        PanelToolTip {
            visible: chipMouse.containsMouse && chip.tip !== ""
            text: chip.tip
        }
        Accessible.role: Accessible.CheckBox
        Accessible.checked: on
        Accessible.name: label
    }

    RowLabel { visible: chips.omarchy; text2: chips.app.tr.row_mode }
    // Mode : cinq segments, celui qui est pris en accent. Autonome, le cran sans carte, prend la
    // couleur d'urgence du thème quand il est pris : plus personne ne relit avant qu'elle agisse.
    Rectangle {
        visible: chips.omarchy
        implicitHeight: chips.chipHeight
        implicitWidth: segments.implicitWidth
        radius: chips.app.rounded(7)
        color: Style.normalFill
        border.width: Style.normalBorderWidth
        border.color: Util.alpha(Color.menu.text, 0.22)
        clip: true
        Row {
            id: segments
            anchors.fill: parent
            Repeater {
                model: chips.app.modes
                Rectangle {
                    id: segment
                    required property var modelData
                    readonly property bool taken: chips.app.mode === modelData.value
                    readonly property bool noCard: modelData.value === "auto"
                    readonly property color tone: noCard ? Color.urgent : Color.accent
                    // Fermé par le rôle actif : éteint, barré, non cliquable. Le panneau affichait
                    // « Code » comme actif alors que le rôle ramenait en Assistant (audit 20/09).
                    readonly property bool shut: modelData.closed === true
                    height: parent.height
                    width: segmentText.implicitWidth + Style.space(20)
                    radius: chips.app.rounded(6)
                    color: taken ? Util.alpha(tone, 0.14) : (!segment.shut && (segmentMouse.containsMouse || segment.activeFocus) ? Util.alpha(Color.menu.text, 0.06) : "transparent")
                    border.width: segment.activeFocus ? Math.max(1, Style.focusBorderWidth) : 0
                    border.color: Style.focusBorderColor
                    activeFocusOnTab: !taken && !shut
                    Keys.onReturnPressed: if (!segment.taken && !segment.shut) chips.app.setSetting("mode", segment.modelData.value)
                    Keys.onEnterPressed: if (!segment.taken && !segment.shut) chips.app.setSetting("mode", segment.modelData.value)
                    Keys.onSpacePressed: if (!segment.taken && !segment.shut) chips.app.setSetting("mode", segment.modelData.value)
                    Text {
                        id: segmentText
                        anchors.centerIn: parent
                        text: segment.modelData.label
                        color: segment.taken ? segment.tone : Color.menu.text
                        font.strikeout: segment.shut
                        opacity: segment.shut ? 0.28 : (segment.taken ? 1 : 0.65)
                        font.family: Style.font.menuFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: segment.taken
                    }
                    MouseArea {
                        id: segmentMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: segment.taken || segment.shut ? Qt.ArrowCursor : Qt.PointingHandCursor
                        onClicked: if (!segment.taken && !segment.shut) chips.app.setSetting("mode", segment.modelData.value)
                    }
                    // Un seul texte par cran, le même que dans Réglages › Mode.
                    PanelToolTip {
                        visible: segmentMouse.containsMouse
                        text: segment.shut ? chips.app.t("role_closed_mode", chips.app.roleLabel)
                                           : chips.app.t("mode_" + segment.modelData.value + "_hint")
                    }
                    Accessible.role: Accessible.RadioButton
                    Accessible.checked: taken
                    Accessible.name: chips.app.t("chip_mode", modelData.label)
                }
            }
        }
    }
    RowLabel { visible: chips.omarchy; text2: chips.app.tr.row_access }
    Flow {
        Layout.fillWidth: true
        spacing: Style.spacing.md
        // Les trois accès, rendus par la MÊME pastille, à partir de l'état publié par le moteur.
        // Le panneau ne décide rien : il afficherait sinon une limite que le moteur n'applique pas.
        Repeater {
            model: chips.omarchy ? chips.app.access : []
            Chip {
                required property var modelData
                label: chips.app.tr["access_" + modelData.key]
                on: modelData.on
                missing: !modelData.configured
                shut: modelData.blocked !== ""
                tip: modelData.blocked === "role" ? chips.app.t("access_shut_role", modelData.by)
                   : modelData.blocked === "mode" ? chips.app.t("access_shut_mode", modelData.by)
                   : !modelData.configured ? chips.app.t("access_missing", chips.app.tr["access_" + modelData.key])
                   : modelData.on ? chips.app.t("access_on", chips.app.tr["access_" + modelData.key])
                   : chips.app.t("access_off", chips.app.tr["access_" + modelData.key])
                onToggled: chips.app.toggleAccess(modelData)
            }
        }
        // Trait : ce qui suit n'est ni un mode ni un accès. « Conversation » est un réglage de voix.
        Rectangle {
            width: 1
            height: chips.chipHeight - Style.space(8)
            color: Util.alpha(Color.menu.text, 0.18)
        }
        Chip {
            label: chips.app.tr.chip_conversation
            on: chips.app.conversation
            tip: chips.app.conversation ? chips.app.tr.chip_conversation_on : chips.app.tr.chip_conversation_off
            onToggled: chips.app.toggleConversation()
        }
        Dropdown {
            visible: chips.omarchy
            showLabel: false
            implicitWidth: Style.space(150)
            value: chips.app.modelName
            options: [{ value: "", label: chips.app.tr.model_default }].concat(chips.app.models)
            fontFamily: Style.font.menuFamily
            onChanged: function (picked) { chips.app.setSetting("model", picked); }
        }
    }
}
