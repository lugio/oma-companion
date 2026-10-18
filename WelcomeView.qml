import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Assistant de première installation (18/10/2026). Il ne s'ouvre que sur une installation neuve
// (`firstRun`, décidé par le moteur), se passe à tout moment et se relance depuis Réglages › Cerveau.
// Il ne fait rien de plus que les Réglages : chaque choix passe par app.setSetting(), et le
// raccourci clavier est seulement MONTRÉ (le plugin n'écrit jamais la configuration d'Hyprland).
ColumnLayout {
    id: welcome
    required property var app
    property int step: 0
    readonly property int steps: 7
    // Le nom entre dans du code Lua à copier : guillemets, antislashs et retours à la ligne retirés.
    readonly property string safeName: String(app.companionName).replace(/["\\\n\r]/g, "").trim() || "Alison"
    readonly property string bindLine: 'o.bind("SUPER + ALT + L", "' + safeName
        + '", "omarchy-shell shell toggle ' + app.pluginId + " '{}'\")"
    spacing: Style.spacing.lg

    // Le clavier part sur « Suivant », jamais sur un choix : le panneau prend le clavier en s'ouvrant,
    // et une frappe destinée à une autre fenêtre changeait la langue (constaté le 18/10).
    function focusNext() { Qt.callLater(function () { nextButton.forceActiveFocus(); }); }
    onVisibleChanged: if (visible) focusNext()

    function saveName() {
        var name = nameField.text.trim();
        if (name !== "" && name !== app.companionName)
            app.setSetting("name", name);
    }

    function finish() {
        app.setSetting("setupDone", true);
        app.firstRun = false;
        app.setView("chat");
    }

    component Title: PanelSectionHeader {
        Layout.fillWidth: true
        foreground: Color.menu.text
        fontFamily: Style.font.menuFamily
        font.letterSpacing: 1
    }
    component Hint: Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        color: Color.menu.text
        opacity: 0.6
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.bodySmall
    }
    component TextButton: Button {
        bordered: true
        focusable: true
        foreground: Color.menu.text
        fontFamily: Style.font.menuFamily
        Accessible.role: Accessible.Button
        Accessible.name: text
    }

    // Où on en est : lisible (et dit aux lecteurs d'écran), puis un trait par étape.
    Text {
        Layout.fillWidth: true
        text: app.t("welcome_step", welcome.step + 1, welcome.steps)
        color: Color.menu.text
        opacity: 0.6
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.caption
        Accessible.role: Accessible.StaticText
        Accessible.name: text
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.xxs
        Repeater {
            model: welcome.steps
            Rectangle {
                required property int index
                Layout.fillWidth: true
                implicitHeight: Style.space(3)
                radius: app.rounded(2)
                color: index <= welcome.step ? Color.accent : Util.alpha(Color.menu.text, 0.18)
            }
        }
    }

    QQC.ScrollView {
        id: scroller
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: scroller.availableWidth
            spacing: Style.spacing.lg

            // 1 · Langue
            ColumnLayout {
                visible: welcome.step === 0
                Layout.fillWidth: true
                spacing: Style.spacing.md
                Title { text: (app.tr.welcome_language || "") }
                Hint { text: (app.tr.welcome_intro || "") }
                ButtonGroup {
                    value: app.lang
                    options: app.languages.length
                             ? app.languages.map(function (l) { return { value: l.code, label: l.name }; })
                             : [{ value: "fr", label: "Français" }, { value: "en", label: "English" }]
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (picked) { app.setSetting("language", picked); }
                }
            }

            // 2 · Cerveau : l'agent choisi dans Omarchy, et ce qu'Alison peut faire avec.
            ColumnLayout {
                visible: welcome.step === 1
                Layout.fillWidth: true
                spacing: Style.spacing.md
                Title { text: (app.tr.welcome_brain || "") }
                Hint { text: (app.tr.welcome_brain_hint || "") }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: (app.agentName || (app.tr.welcome_brain_none || "")) + " — " + (app.tr["brain_level_" + (app.brainLevel || "none")] || "")
                    color: app.brainLevel === "complete" ? Color.accent : app.brainLevel === "none" || app.brainLevel === "missing" ? Color.urgent : Color.menu.text
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.body
                }
                Hint { text: app.tr["brain_level_" + (app.brainLevel || "none") + "_hint"] || "" }
                // Le tableau de la maquette : ce qu'Alison fait avec chaque cerveau d'Omarchy.
                Repeater {
                    model: [
                        { name: "Claude Code", level: "complete" },
                        { name: "Codex", level: "certifying" },
                        { name: "OpenCode, Gemini, Pi…", level: "uncertified" }
                    ]
                    RowLayout {
                        id: brainRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        Text {
                            Layout.preferredWidth: Style.space(150)
                            text: brainRow.modelData.name
                            color: Color.menu.text
                            font.bold: app.agentName === brainRow.modelData.name
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.bodySmall
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: app.tr["brain_level_" + brainRow.modelData.level] || ""
                            color: brainRow.modelData.level === "complete" ? Color.accent : Color.menu.text
                            opacity: brainRow.modelData.level === "complete" ? 1 : 0.7
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.bodySmall
                        }
                    }
                }
                Hint { visible: app.brainLevel !== "complete"; text: (app.tr.welcome_brain_change || ""); opacity: 0.45 }
            }

            // 3 · Par où commencer : un cran fermé. Code et Autonome viennent plus tard, dans les Réglages.
            ColumnLayout {
                visible: welcome.step === 2
                Layout.fillWidth: true
                spacing: Style.spacing.md
                Title { text: (app.tr.welcome_mode || "") }
                ButtonGroup {
                    value: ["chat", "read", "assistant"].indexOf(app.mode) >= 0 ? app.mode : "chat"
                    options: app.modes.filter(function (m) { return ["chat", "read", "assistant"].indexOf(m.value) >= 0; })
                                      .map(function (m) { return { value: m.value, label: m.label }; })
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (picked) { app.setSetting("mode", picked); }
                }
                Hint { text: app.tr["mode_" + (["chat", "read", "assistant"].indexOf(app.mode) >= 0 ? app.mode : "chat") + "_hint"] || "" }
                Hint { text: (app.tr.welcome_mode_later || ""); opacity: 0.45 }
            }

            // 4 · Personnalité : garder Alison, ou lui donner un autre nom (le reste dans Réglages › Rôles).
            ColumnLayout {
                visible: welcome.step === 3
                Layout.fillWidth: true
                spacing: Style.spacing.md
                Title { text: (app.tr.welcome_persona || "") }
                Hint { text: (app.tr.welcome_persona_hint || "") }
                TextField {
                    id: nameField
                    Layout.fillWidth: true
                    foreground: Color.menu.text
                    font.family: Style.font.menuFamily
                    text: app.companionName
                    placeholderText: (app.tr.persona_name || "")
                    // Enregistré sur Entrée ou sur « Suivant » à cette étape, jamais en quittant le champ.
                    onAccepted: welcome.saveName()
                }
            }

            // 5 · Voix (facultatif) : rien ne s'installe sans ce clic.
            ColumnLayout {
                visible: welcome.step === 4
                Layout.fillWidth: true
                spacing: Style.spacing.md
                Title { text: (app.tr.welcome_voice || "") }
                Hint { text: (app.tr.welcome_voice_hint || "") }
                RowLayout {
                    spacing: Style.spacing.md
                    TextButton {
                        visible: !app.voiceReady && !app.voiceSetupRunning
                        text: (app.tr.welcome_voice_install || "")
                        onClicked: app.send("install_voice")
                    }
                    Hint { visible: app.voiceSetupRunning || app.voiceReady; text: app.voiceReady ? (app.tr.welcome_voice_ready || "") : app.voiceSetupText }
                }
                Title { text: (app.tr.welcome_mic || "") }
                TextField {
                    id: micField
                    Layout.fillWidth: true
                    foreground: Color.menu.text
                    font.family: Style.font.menuFamily
                    text: app.micro
                    placeholderText: (app.tr.voice_mic || "")
                    // Comme le nom : enregistré sur Entrée seulement.
                    onAccepted: app.setSetting("micro", text.trim())
                }
                Hint { text: (app.tr.mic_hint || "") }
            }

            // 6 · Accès (facultatif) : chacun se règle et se teste dans les Réglages, sans action matérielle.
            ColumnLayout {
                visible: welcome.step === 5
                Layout.fillWidth: true
                spacing: Style.spacing.md
                Title { text: (app.tr.welcome_access || "") }
                Hint { text: (app.tr.welcome_access_hint || "") }
                Repeater {
                    model: [
                        { key: "home", hint: "welcome_access_home" },
                        { key: "mail", hint: "welcome_access_mail" },
                        { key: "erp", hint: "welcome_access_erp" }
                    ]
                    Rectangle {
                        id: accessCard
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: accessBody.implicitHeight + Style.space(16)
                        radius: app.rounded(6)
                        color: "transparent"
                        border.width: Style.normalBorderWidth
                        border.color: Util.alpha(Color.menu.text, 0.18)
                        RowLayout {
                            id: accessBody
                            anchors.fill: parent
                            anchors.margins: Style.space(8)
                            spacing: Style.spacing.md
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Style.spacing.xxs
                                Text {
                                    text: app.tr["access_" + accessCard.modelData.key] || accessCard.modelData.key
                                    color: Color.menu.text
                                    font.bold: true
                                    font.family: Style.font.menuFamily
                                    font.pixelSize: Style.font.body
                                }
                                Hint { text: app.tr[accessCard.modelData.hint] || "" }
                            }
                            TextButton {
                                text: (app.tr.welcome_access_setup || "")
                                Accessible.name: (app.tr.welcome_access_setup || "") + " : " + (app.tr["access_" + accessCard.modelData.key] || "")
                                onClicked: app.showSettings("access")
                            }
                        }
                    }
                }
            }

            // 7 · Raccourci : montré, copié d'un clic, jamais écrit par le plugin.
            ColumnLayout {
                visible: welcome.step === 6
                Layout.fillWidth: true
                spacing: Style.spacing.md
                Title { text: (app.tr.welcome_shortcut || "") }
                Hint { text: (app.tr.welcome_shortcut_hint || "") }
                Text {
                    Layout.fillWidth: true
                    // Coupée aux espaces seulement : la parenthèse finale reste sur la ligne de la commande.
                    wrapMode: Text.Wrap
                    text: welcome.bindLine
                    color: Color.menu.text
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.bodySmall
                }
                RowLayout {
                    spacing: Style.spacing.md
                    TextButton {
                        id: copyButton
                        property bool copied: false
                        text: copied ? (app.tr.welcome_copied || "") : (app.tr.welcome_copy || "")
                        onClicked: { app.copyText(welcome.bindLine); copied = true; }
                    }
                    Hint { text: (app.tr.welcome_shortcut_reload || "") }
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md
        TextButton { text: (app.tr.welcome_skip || ""); onClicked: welcome.finish() }
        Item { Layout.fillWidth: true }
        TextButton {
            visible: welcome.step > 0
            text: (app.tr.welcome_back || "")
            onClicked: welcome.step -= 1
        }
        TextButton {
            id: nextButton
            text: welcome.step === welcome.steps - 1 ? (app.tr.welcome_finish || "") : (app.tr.welcome_next || "")
            selected: true
            onClicked: {
                if (welcome.step === 3)
                    welcome.saveName();
                if (welcome.step === welcome.steps - 1)
                    welcome.finish();
                else
                    welcome.step += 1;
            }
        }
    }
}
