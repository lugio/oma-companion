import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// Réglages d'Alison en quatre rubriques. La vue remplace la conversation ; l'icône Réglages
// de l'en-tête (ou Échap) ramène à la conversation. Chaque changement passe par
// app.setSetting(), qui le fait persister par le moteur.
RowLayout {
    id: settings
    required property var app
    function consumeEscape() {
        if (!selfCard.editingPersona)
            return false;
        selfCard.cancelPersona();
        return true;
    }
    property string section: "brain"
    property bool showEngines: app.provider !== "omarchy"
    readonly property bool omarchy: app.provider === "omarchy"
    // L'état d'un accès, tel que la pastille l'affiche : lu dans `app.access`, jamais recalculé.
    function accessState(key) {
        for (var i = 0; i < app.access.length; i++) {
            var a = app.access[i];
            if (a.key !== key)
                continue;
            if (a.blocked === "role") return app.t("access_state_shut_role", a.by);
            if (a.blocked === "mode") return app.t("access_state_shut_mode", a.by);
            if (!a.configured) return app.tr.access_state_missing;
            return a.on ? app.tr.access_state_on : app.tr.access_state_off;
        }
        return "";
    }
    // Fiche de rôle : ce qu'il ferme, en mots du panneau. `closes` et `access` viennent du moteur.
    function roleModesLine(r) {
        var closes = (r.closes || []).map(function (m) { return app.modeLabels[m] || m; });
        var open = app.modeOrder.filter(function (m) { return (r.closes || []).indexOf(m) < 0; });
        var ceiling = open.length ? (app.modeLabels[open[open.length - 1]] || open[open.length - 1]) : "";
        return app.tr.role_ceiling + " " + ceiling + (closes.length ? " · " + app.t("role_closes", closes.join(", ")) : "");
    }
    function roleDelegateLine(r) {
        if (r.delegate === null || r.delegate === undefined)
            return app.tr.role_can_ask_all;
        if (r.delegate.length === 0)
            return app.tr.role_can_ask_none;
        var labels = r.delegate.map(function (n) {
            for (var i = 0; i < app.rolesAvailable.length; i++)
                if (app.rolesAvailable[i].name === n)
                    return app.rolesAvailable[i].label;
            return n;
        });
        return app.t("role_can_ask", labels.join(", "));
    }
    function roleAccessLine(r) {
        if (r.access === null || r.access === undefined)
            return app.tr.role_access + " : " + app.tr.role_all_access;
        var open = [], shut = [];
        for (var i = 0; i < app.access.length; i++) {
            var key = app.access[i].key;
            (r.access.indexOf(key) >= 0 ? open : shut).push(app.tr["access_" + key]);
        }
        return app.tr.role_access + " : " + (open.length ? open.join(", ") : "—")
               + (shut.length ? " · " + app.t("role_access_closed", shut.join(", ")) : "");
    }
    spacing: Style.spacing.panelGap

    // Titre de rubrique du kit Omarchy (PanelSectionHeader), aux couleurs du menu.
    // Les exemples pas encore ajoutés (un rôle du même nom existe déjà = on ne le propose plus).
    function availableExamples() {
        var taken = settings.app.rolesAvailable.map(function (r) { return r.name; });
        return (settings.app.roleExamples || []).filter(function (e) { return taken.indexOf(e.name) < 0; });
    }
    component Label: PanelSectionHeader {
        Layout.fillWidth: true
        foreground: Color.menu.text
        fontFamily: Style.font.menuFamily
        font.letterSpacing: 1
    }
    // Fiche de rôle (Réglages › Rôles) : titre, étiquette, et le corps en dessous.
    component RoleCard: Rectangle {
        id: card
        property string title: ""
        property string tag: ""
        property bool current: false
        default property alias body: cardBody.data
        Layout.fillWidth: true
        implicitHeight: cardBody.implicitHeight + Style.space(20)
        radius: settings.app.rounded(8)
        color: card.current ? Util.alpha(Color.accent, 0.08) : "transparent"
        border.width: Style.normalBorderWidth
        border.color: card.current ? Util.alpha(Color.accent, 0.5) : Util.alpha(Color.menu.text, 0.18)
        ColumnLayout {
            id: cardBody
            anchors.fill: parent
            anchors.margins: Style.space(10)
            spacing: Style.spacing.xxs
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: card.title
                    color: card.current ? Color.accent : Color.menu.text
                    font.bold: true
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.body
                }
                Text {
                    text: card.tag
                    color: card.current ? Color.accent : Color.menu.text
                    opacity: card.current ? 1 : 0.55
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.caption
                }
            }
        }
    }
    component Hint: Text {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        color: Color.menu.text
        opacity: 0.6
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.bodySmall
    }
    component SwitchRow: RowLayout {
        id: switchRow
        property string label: ""
        property bool checked: false
        signal toggled
        Layout.fillWidth: true
        spacing: Style.spacing.lg
        // La ligne entière se prend au clavier : Tab puis Entrée ou Espace bascule l'interrupteur.
        activeFocusOnTab: true
        Keys.onReturnPressed: switchRow.toggled()
        Keys.onEnterPressed: switchRow.toggled()
        Keys.onSpacePressed: switchRow.toggled()
        Accessible.role: Accessible.CheckBox
        Accessible.checked: checked
        Accessible.name: label
        Text {
            Layout.fillWidth: true
            text: switchRow.label
            wrapMode: Text.Wrap
            color: switchRow.activeFocus ? Color.accent : Color.menu.text
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.body
        }
        ToggleSwitch {
            checked: switchRow.checked
            foreground: Color.menu.text
            onToggled: switchRow.toggled()
        }
    }
    // Champ du kit Omarchy : bordure, fond et anneau de focus aux jetons du thème.
    component Field: TextField {
        Layout.fillWidth: true
        foreground: Color.menu.text
        font.family: Style.font.menuFamily
    }
    component TextButton: Button {
        bordered: true
        focusable: true
        foreground: Color.menu.text
        fontFamily: Style.font.menuFamily
    }

    ColumnLayout {
        Layout.alignment: Qt.AlignTop
        Layout.preferredWidth: Style.space(130)
        spacing: Style.spacing.sm
        Repeater {
            model: [
                // Nommés comme les rangées du panneau : MODE et ACCÈS. Le mode (les droits) et
                // ses exceptions étaient éparpillés entre Cerveau et Sécurité (audit du 21/09).
                { key: "brain", label: settings.app.tr.section_brain },
                { key: "mode", label: settings.app.tr.section_mode },
                { key: "access", label: settings.app.tr.section_access },
                { key: "roles", label: settings.app.tr.section_roles },
                { key: "voice", label: settings.app.tr.section_voice },
                { key: "memory", label: settings.app.tr.section_memory },
                { key: "backup", label: settings.app.tr.section_backup }
            ]
            Button {
                required property var modelData
                Layout.fillWidth: true
                leftAlign: true
                focusable: true
                text: modelData.label || modelData.key
                selected: settings.section === modelData.key
                foreground: Color.menu.text
                fontFamily: Style.font.menuFamily
                onClicked: settings.section = modelData.key
            }
        }
    }
    // Séparateur vertical : même teinte que PanelSeparator, qui n'existe qu'à l'horizontale.
    Rectangle {
        Layout.fillHeight: true
        implicitWidth: 1
        color: Color.menu.text
        opacity: 0.12
    }

    QQC.ScrollView {
        id: scroller
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: scroller.availableWidth
            spacing: Style.spacing.panelGap

            // ----- Sauvegarde : exporter, restaurer. Jamais de secret ; une restauration ne rallume rien.
            ColumnLayout {
                id: backupPane
                visible: settings.section === "backup"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                property bool pointers: false
                property bool replaceRoles: false
                property bool includePersona: true
                property bool includeRoles: true
                onVisibleChanged: if (visible) settings.app.send("backup_list")
                Label { text: settings.app.tr.backup_export_title }
                Hint { text: settings.app.tr.backup_export_hint }
                SwitchRow {
                    label: settings.app.tr.backup_pointers
                    checked: backupPane.pointers
                    // Changer l'option annule l'aperçu en cours : on restaure ce qu'on a vu, rien d'autre.
                    onToggled: { backupPane.pointers = !backupPane.pointers; settings.app.backupPreview = null; }
                }
                Hint { text: settings.app.tr.backup_pointers_hint; opacity: 0.45 }
                Hint { text: settings.app.tr.backup_content_hint; opacity: 0.45 }
                SwitchRow {
                    label: settings.app.tr.backup_include_persona || ""
                    checked: backupPane.includePersona
                    onToggled: backupPane.includePersona = !backupPane.includePersona
                }
                SwitchRow {
                    label: settings.app.tr.backup_include_roles || ""
                    checked: backupPane.includeRoles
                    onToggled: backupPane.includeRoles = !backupPane.includeRoles
                }
                RowLayout {
                    spacing: Style.spacing.md
                    TextButton {
                        text: settings.app.tr.backup_export
                        onClicked: settings.app.write({ command: "backup_export", pointers: backupPane.pointers,
                                                        includePersona: backupPane.includePersona, includeRoles: backupPane.includeRoles })
                    }
                    TextButton {
                        text: settings.app.tr.backup_open_folder
                        fontSize: Style.font.caption
                        onClicked: settings.app.send("backup_open_folder")
                    }
                }
                Hint { visible: settings.app.backupStatus !== ""; text: settings.app.backupStatus; opacity: 0.9 }
                Hint { visible: settings.app.backupFolder !== ""; text: settings.app.backupFolder; opacity: 0.4 }

                Label { text: settings.app.tr.backup_restore_title }
                Hint { text: settings.app.tr.backup_restore_hint }
                Repeater {
                    model: settings.app.backupItems.slice(0, 8)
                    RowLayout {
                        id: backupRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        Hint { text: backupRow.modelData.name; opacity: 0.8 }
                        TextButton {
                            text: settings.app.tr.backup_preview
                            fontSize: Style.font.caption
                            Accessible.name: settings.app.tr.backup_preview + " : " + backupRow.modelData.name
                            onClicked: settings.app.write({ command: "backup_preview", path: backupRow.modelData.path,
                                                            pointers: backupPane.pointers })
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Field {
                        id: backupFile
                        placeholderText: settings.app.tr.backup_file
                        onAccepted: settings.app.write({ command: "backup_preview", path: text.trim(), pointers: backupPane.pointers })
                    }
                    TextButton {
                        text: settings.app.tr.backup_preview
                        fontSize: Style.font.caption
                        onClicked: settings.app.write({ command: "backup_preview", path: backupFile.text.trim(), pointers: backupPane.pointers })
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: settings.app.backupError !== ""
                    text: settings.app.backupError
                    wrapMode: Text.Wrap
                    color: Color.urgent
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.bodySmall
                }
                // L'aperçu : ce qui changerait, ce qui sera ignoré. Rien n'est écrit avant « Restaurer ».
                RoleCard {
                    visible: settings.app.backupPreview !== null
                    title: settings.app.tr.backup_preview_title
                    tag: settings.app.backupPreview ? settings.app.backupPreview.created : ""
                    Hint {
                        text: settings.app.backupPreview
                              ? settings.app.t("backup_preview_settings", settings.app.backupPreview.settings.length)
                                + (settings.app.backupPreview.settings.length
                                   ? " : " + settings.app.backupPreview.settings.map(function (c) { return c.key; }).join(", ") : "")
                              : ""
                    }
                    Hint {
                        visible: settings.app.backupPreview && settings.app.backupPreview.rolesNew.length > 0
                        text: settings.app.backupPreview ? settings.app.tr.backup_roles_new + " : " + settings.app.backupPreview.rolesNew.join(", ") : ""
                    }
                    Hint {
                        visible: settings.app.backupPreview && settings.app.backupPreview.rolesReplaced.length > 0
                        text: settings.app.backupPreview ? settings.app.tr.backup_roles_existing + " : " + settings.app.backupPreview.rolesReplaced.join(", ") : ""
                    }
                    SwitchRow {
                        visible: settings.app.backupPreview && settings.app.backupPreview.rolesReplaced.length > 0
                        label: settings.app.tr.backup_replace_roles
                        checked: backupPane.replaceRoles
                        onToggled: backupPane.replaceRoles = !backupPane.replaceRoles
                    }
                    Hint {
                        visible: settings.app.backupPreview && (settings.app.backupPreview.persona || settings.app.backupPreview.personaReset
                                                                || settings.app.backupPreview.maisonPresent)
                        text: settings.app.backupPreview
                              ? (settings.app.backupPreview.persona ? settings.app.tr.backup_persona + " "
                                 : settings.app.backupPreview.personaReset ? settings.app.tr.backup_persona_reset + " " : "")
                                + (settings.app.backupPreview.maisonPresent ? settings.app.t("backup_maison", settings.app.backupPreview.maisonRules) : "")
                              : ""
                    }
                    Hint {
                        visible: settings.app.backupPreview && settings.app.backupPreview.switchedOff.length > 0
                        text: settings.app.backupPreview ? settings.app.t("backup_switched_off", settings.app.backupPreview.switchedOff.join(", ")) : ""
                    }
                    Hint { text: settings.app.tr.backup_never; opacity: 0.45 }
                    Label { text: settings.app.tr.backup_free_text_preview || "" }
                    QQC.ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Style.space(180)
                        contentWidth: availableWidth
                        clip: true
                        QQC.TextArea {
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            textFormat: TextEdit.PlainText
                            text: settings.app.backupPreview
                                  ? (settings.app.backupPreview.personaText || "") + "\n"
                                    + JSON.stringify(settings.app.backupPreview.roleContents || {}, null, 2) : ""
                        }
                    }
                    RowLayout {
                        spacing: Style.spacing.md
                        TextButton {
                            text: settings.app.tr.backup_apply
                            onClicked: settings.app.write({ command: "backup_apply", token: settings.app.backupToken,
                                                            replaceRoles: backupPane.replaceRoles })
                        }
                        TextButton {
                            text: settings.app.tr.role_form_cancel
                            onClicked: settings.app.backupPreview = null
                        }
                    }
                }
            }

            // ----- Cerveau
            ColumnLayout {
                visible: settings.section === "brain"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                // Le niveau de prise en charge du cerveau choisi dans Omarchy (contrat des adaptateurs) :
                // jamais deviné, accordé seulement après preuve.
                Hint {
                    visible: settings.app.provider === "omarchy" && settings.app.brainLevel !== ""
                    opacity: 0.9
                    text: (settings.app.agentName || settings.app.tr.welcome_brain_none) + " — "
                          + (settings.app.tr["brain_level_" + settings.app.brainLevel] || "")
                }
                TextButton {
                    text: settings.app.tr.welcome_restart
                    fontSize: Style.font.caption
                    onClicked: settings.app.restartWelcome()
                }
                Label { text: settings.app.tr.label_language }
                ButtonGroup {
                    value: settings.app.lang
                    // La liste vient des fichiers de langue présents (plugin + dossier de l'utilisateur).
                    options: settings.app.languages.length
                             ? settings.app.languages.map(function (l) { return { value: l.code, label: l.name }; })
                             : [{ value: "fr", label: "Français" }, { value: "en", label: "English" }]
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (picked) { settings.app.setSetting("language", picked); }
                }
                Hint { text: settings.app.tr.language_hint }
                // Le programme qui répond s'appelle CERVEAU ici, jamais « agent » : pour
                // l'utilisateur, un agent c'est un personnage — et un personnage est un rôle (audit du 21/09).
                Label { text: settings.app.tr.label_brain }
                Hint {
                    opacity: 0.9
                    text: settings.omarchy
                          ? (settings.app.agentName || settings.app.tr.brain_none) + settings.app.tr.brain_suffix
                          : settings.app.tr.brain_engine + settings.app.provider
                }
                Label { visible: settings.omarchy; text: settings.app.tr.label_model }
                ButtonGroup {
                    visible: settings.omarchy
                    value: settings.app.modelName
                    options: [{ value: "", label: settings.app.tr.model_default_short }].concat(settings.app.models)
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (picked) { settings.app.setSetting("model", picked); }
                }
                // Le mode ne se règle plus ici : il a UN endroit, la rangée MODE du panneau, et
                // UN onglet qui l'explique (Réglages › Mode).
                Button {
                    text: (settings.showEngines ? "▾ " : "▸ ") + settings.app.tr.other_engines
                    focusable: true
                    foreground: Color.menu.text
                    fontFamily: Style.font.menuFamily
                    onClicked: settings.showEngines = !settings.showEngines
                }
                ColumnLayout {
                    visible: settings.showEngines
                    Layout.fillWidth: true
                    spacing: Style.spacing.lg
                    ButtonGroup {
                        value: settings.app.provider
                        options: [
                            { value: "omarchy", label: settings.app.tr.engine_omarchy },
                            { value: "ollama", label: settings.app.tr.engine_ollama },
                            { value: "openai-compatible", label: settings.app.tr.engine_api }
                        ]
                        foreground: Color.menu.text
                        background: "transparent"
                        fontFamily: Style.font.menuFamily
                        onChanged: function (picked) { settings.app.setSetting("provider", picked); }
                    }
                    Field {
                        visible: !settings.omarchy
                        placeholderText: settings.app.tr.field_model
                        text: settings.app.modelName
                        onEditingFinished: settings.app.setSetting("model", text)
                    }
                    Field {
                        visible: !settings.omarchy
                        placeholderText: settings.app.tr.field_endpoint
                        text: settings.app.endpoint
                        onEditingFinished: settings.app.setSetting("endpoint", text)
                    }
                }
                TextButton {
                    text: settings.app.tr.new_conversation
                    enabled: !settings.app.busy
                    opacity: enabled ? 1 : 0.45
                    onClicked: {
                        settings.app.send("clear");
                        settings.app.actionText = "";
                        settings.app.setView("chat");
                    }
                }
                // Bureau : ce qu'Alison fait elle-même, sans réveiller le cerveau (bureau.py). Ce
                // n'est pas un accès (pas de pastille) : il vit avec le cerveau, pas dans Accès.
                Label { text: settings.app.tr.label_desk }
                Hint { text: settings.app.tr.desk_hint }
                Hint { text: settings.app.tr.desk_list; opacity: 0.75 }
                Field {
                    id: vaultField
                    placeholderText: settings.app.tr.desk_vault
                    text: settings.app.obsidianVault
                    onAccepted: settings.app.setSetting("obsidianVault", text.trim())
                }
                Hint { text: settings.app.tr.desk_vault_hint; opacity: 0.45 }
                Hint { text: settings.app.tr.desk_screen; opacity: 0.45 }
            }

            // ----- Mode : l'échelle expliquée (un seul texte par cran, celui de l'infobulle du
            // panneau), la phrase du garde, puis les exceptions au mode qui vivaient dans un onglet
            // « Sécurité » à part — ce sont des droits, elles vont avec le mode.
            ColumnLayout {
                visible: settings.section === "mode"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Label { text: settings.app.tr.section_mode.toUpperCase() }
                Hint { text: settings.app.tr.mode_ladder }
                Repeater {
                    model: settings.omarchy ? settings.app.modes : []
                    RowLayout {
                        id: rung
                        required property var modelData
                        readonly property bool taken: settings.app.mode === modelData.value
                        readonly property bool shut: modelData.closed === true
                        readonly property bool noCard: modelData.value === "auto"
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        Text {
                            Layout.preferredWidth: Style.space(96)
                            Layout.alignment: Qt.AlignTop
                            text: rung.modelData.label
                            color: rung.taken ? (rung.noCard ? Color.urgent : Color.accent) : Color.menu.text
                            opacity: rung.shut ? 0.35 : 1
                            font.strikeout: rung.shut
                            font.bold: rung.taken
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.bodySmall
                        }
                        Hint {
                            text: rung.shut ? settings.app.t("role_closed_mode", settings.app.roleLabel)
                                            : settings.app.t("mode_" + rung.modelData.value + "_hint")
                            opacity: rung.shut ? 0.35 : 0.6
                        }
                    }
                }
                Label { text: settings.app.tr.label_applies }
                Hint {
                    opacity: 0.9
                    color: settings.app.harnessUnsafe ? Color.urgent : Color.menu.text
                    text: settings.app.harness || settings.app.tr.guard_none
                }
                Label { visible: settings.app.agentProblem !== ""; text: settings.app.tr.label_notice }
                Hint { visible: settings.app.agentProblem !== ""; text: settings.app.agentProblem }
                // Familles d'actions autorisées pour la conversation en cours (bouton « Toujours … »).
                ColumnLayout {
                    visible: settings.app.sessionAllows.length > 0
                    Layout.fillWidth: true
                    spacing: Style.spacing.sm
                    Label { text: settings.app.tr.label_always }
                    Hint { text: settings.app.tr.always_hint }
                    Repeater {
                        model: settings.app.sessionAllows
                        Text {
                            required property string modelData
                            Layout.fillWidth: true
                            text: "· " + modelData
                            wrapMode: Text.Wrap
                            color: Color.menu.text
                            opacity: 0.75
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.bodySmall
                        }
                    }
                    TextButton {
                        text: settings.app.tr.always_forget
                        fontSize: Style.font.caption
                        onClicked: settings.app.send("forget_always")
                    }
                }

                Label { text: settings.app.tr.label_trusted }
                Hint {
                    text: settings.app.trustedSites.length === 0 ? settings.app.tr.trusted_none : settings.app.tr.trusted_some
                }
                Repeater {
                    model: settings.app.trustedSites
                    RowLayout {
                        id: site
                        required property string modelData
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        Text {
                            Layout.fillWidth: true
                            text: site.modelData
                            elide: Text.ElideRight
                            color: Color.menu.text
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.bodySmall
                        }
                        Button {
                            text: settings.app.tr.remove
                            focusable: true
                            bordered: true
                            foreground: Color.menu.text
                            fontFamily: Style.font.menuFamily
                            fontSize: Style.font.caption
                            onClicked: settings.app.send("forget_site", site.modelData)
                        }
                    }
                }
                Label { text: settings.app.tr.label_private }
                Hint {
                    text: settings.app.privatePaths.length === 0
                          ? settings.app.tr.private_none
                          : settings.app.t("private_some", settings.app.privatePaths.join(", "))
                }
                Label { text: settings.app.tr.label_denied }
                Hint { text: settings.app.tr.denied_hint }
            }
            
            // ----- Accès. Trois blocs IDENTIQUES : l'état réel en tête (celui de la pastille, dit
            // par le moteur), puis où prendre les identifiants, puis « Enregistrer et tester ».
            // L'interrupteur « Mode maison » n'existe plus ici : la pastille allume et éteint, et
            // il affichait « allumé » pendant que le rôle fermait la maison (audit du 21/09).
            ColumnLayout {
                visible: settings.section === "access"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Hint { text: settings.app.tr.access_hint }
                Label { text: settings.app.tr.label_home }
                Hint { text: settings.accessState("home"); opacity: 0.9 }
                Hint { text: settings.app.tr.home_hint }
                Field {
                    id: haUrlField
                    placeholderText: settings.app.tr.home_url
                    text: settings.app.haUrl
                }
                Field {
                    id: haTokenField
                    password: true
                    placeholderText: settings.app.haHasToken ? settings.app.tr.home_token_saved : settings.app.tr.home_token
                }
                // Le jeton dans le trousseau du système plutôt que dans ha.json (18/10).
                SwitchRow {
                    id: haKeyringRow
                    visible: settings.app.secrets.available
                    property bool wanted: settings.app.haKeyring
                    label: settings.app.tr.keyring_ha
                    checked: wanted
                    onToggled: wanted = !wanted
                }
                RowLayout {
                    spacing: Style.spacing.lg
                    TextButton {
                        text: settings.app.tr.home_save_test
                        onClicked: {
                            settings.app.haMessage = settings.app.tr.home_testing;
                            settings.app.write({ command: "ha_config", url: haUrlField.text, token: haTokenField.text,
                                                 keyring: haKeyringRow.visible && haKeyringRow.wanted });
                            haTokenField.text = "";
                        }
                    }
                    TextButton {
                        text: settings.app.tr.home_test
                        onClicked: {
                            settings.app.haMessage = settings.app.tr.home_testing;
                            settings.app.write({ command: "ha_status", test: true });
                        }
                    }
                }
                Hint {
                    visible: settings.app.haMessage !== ""
                    opacity: 0.9
                    text: settings.app.haMessage
                }
            }

            // ----- Courrier : lecture seule d'une boîte IMAP (mail.py)
            ColumnLayout {
                visible: settings.section === "access"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Label { text: settings.app.tr.label_mail }
                Hint { text: settings.accessState("mail"); opacity: 0.9 }
                // Où ranger les identifiants : le trousseau du système (par défaut quand il répond) ou un coffre JSON.
                ButtonGroup {
                    id: mailStore
                    visible: settings.app.secrets.available
                    property string picked: ""
                    value: picked !== "" ? picked : (settings.app.mailStore !== "" ? settings.app.mailStore
                                                     : settings.app.mailVault !== "" ? "vault" : "keyring")
                    options: [{ value: "keyring", label: settings.app.tr.store_keyring }, { value: "vault", label: settings.app.tr.store_vault }]
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (value) { picked = value; }
                }
                ColumnLayout {
                    visible: mailStore.visible && mailStore.value === "keyring"
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Hint { text: settings.app.tr.keyring_hint }
                    // L'état du secret, sans jamais sa valeur : enregistré, absent ou trousseau injoignable.
                    Hint {
                        opacity: 0.9
                        text: !settings.app.secrets.available ? settings.app.tr.keyring_state_unavailable
                              : settings.app.secrets.mail ? settings.app.tr.keyring_state_saved : settings.app.tr.keyring_state_missing
                    }
                    Field { id: mailEmailField; placeholderText: settings.app.tr.mail_email; text: settings.app.mailEmail }
                    Field { id: mailHostField; placeholderText: settings.app.tr.mail_host; text: settings.app.mailHost }
                    Field {
                        id: mailPasswordField
                        password: true
                        placeholderText: settings.app.secrets.mail ? settings.app.tr.keyring_saved : settings.app.tr.mail_password
                    }
                    RowLayout {
                        spacing: Style.spacing.md
                        TextButton {
                            text: settings.app.tr.keyring_save_test
                            onClicked: {
                                // Le coffre, s'il est renseigné, passerait avant : on le vide pour ce choix.
                                settings.app.setSetting("mailStore", "keyring");
                                settings.app.setSetting("mailVault", "");
                                settings.app.setSetting("mailAccount", "");
                                settings.app.setSetting("mailEmail", mailEmailField.text.trim());
                                settings.app.setSetting("mailHost", mailHostField.text.trim());
                                // Avec un nouveau secret, le moteur teste APRÈS l'avoir rangé ; sinon, test direct.
                                if (mailPasswordField.text !== "")
                                    settings.app.write({ command: "secret_save", acces: "mail", value: mailPasswordField.text, test: true });
                                else
                                    settings.app.send("mail_test");
                                mailPasswordField.text = "";
                            }
                        }
                        TextButton {
                            visible: settings.app.secrets.mail
                            text: settings.app.tr.keyring_clear
                            fontSize: Style.font.caption
                            onClicked: settings.app.write({ command: "secret_clear", acces: "mail" })
                        }
                    }
                }
                Hint { visible: !mailStore.visible || mailStore.value === "vault"; text: settings.app.tr.mail_hint }
                Field {
                    id: mailVaultField
                    visible: !mailStore.visible || mailStore.value === "vault"
                    placeholderText: settings.app.tr.mail_vault
                    text: settings.app.mailVault
                    onAccepted: settings.app.setSetting("mailVault", text.trim())
                }
                Field {
                    id: mailAccountField
                    visible: !mailStore.visible || mailStore.value === "vault"
                    placeholderText: settings.app.tr.mail_account
                    text: settings.app.mailAccount
                    onAccepted: settings.app.setSetting("mailAccount", text.trim())
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    TextButton {
                        visible: !mailStore.visible || mailStore.value === "vault"
                        text: settings.app.tr.mail_save_test
                        onClicked: {
                            settings.app.setSetting("mailStore", "vault");
                            settings.app.setSetting("mailVault", mailVaultField.text.trim());
                            settings.app.setSetting("mailAccount", mailAccountField.text.trim());
                            settings.app.send("mail_test");
                        }
                    }
                    Hint {
                        visible: settings.app.mailStatus !== ""
                        opacity: 0.9
                        text: (settings.app.mailOk ? "✓ " : "✗ ") + settings.app.mailStatus
                    }
                }
                Hint { text: settings.app.tr.mail_readonly; opacity: 0.45 }
            }

            // ----- Comptabilité : lecture seule d'un Dolibarr. Même principe que le courrier —
            // le moteur écrit OÙ prendre la clé, jamais la clé, et aucun verbe d'écriture n'existe
            // dans le lecteur.
            ColumnLayout {
                visible: settings.section === "access"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Label { text: settings.app.tr.label_erp }
                Hint { text: settings.accessState("erp"); opacity: 0.9 }
                ButtonGroup {
                    id: erpStore
                    visible: settings.app.secrets.available
                    property string picked: ""
                    value: picked !== "" ? picked : (settings.app.erpStore !== "" ? settings.app.erpStore
                                                     : settings.app.erpVault !== "" ? "vault" : "keyring")
                    options: [{ value: "keyring", label: settings.app.tr.store_keyring }, { value: "vault", label: settings.app.tr.store_vault }]
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (value) { picked = value; }
                }
                ColumnLayout {
                    visible: erpStore.visible && erpStore.value === "keyring"
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Hint { text: settings.app.tr.keyring_hint }
                    // L'état du secret, sans jamais sa valeur : enregistré, absent ou trousseau injoignable.
                    Hint {
                        opacity: 0.9
                        text: !settings.app.secrets.available ? settings.app.tr.keyring_state_unavailable
                              : settings.app.secrets.erp ? settings.app.tr.keyring_state_saved : settings.app.tr.keyring_state_missing
                    }
                    Field { id: erpUrlField; placeholderText: settings.app.tr.erp_url; text: settings.app.erpUrl }
                    Field {
                        id: erpKeyField
                        password: true
                        placeholderText: settings.app.secrets.erp ? settings.app.tr.keyring_saved : settings.app.tr.erp_key
                    }
                    RowLayout {
                        spacing: Style.spacing.md
                        TextButton {
                            text: settings.app.tr.keyring_save_test
                            onClicked: {
                                settings.app.setSetting("erpStore", "keyring");
                                settings.app.setSetting("erpVault", "");
                                settings.app.setSetting("erpAccount", "");
                                settings.app.setSetting("erpUrl", erpUrlField.text.trim());
                                // Avec un nouveau secret, le moteur teste APRÈS l'avoir rangé ; sinon, test direct.
                                if (erpKeyField.text !== "")
                                    settings.app.write({ command: "secret_save", acces: "erp", value: erpKeyField.text, test: true });
                                else
                                    settings.app.send("erp_test");
                                erpKeyField.text = "";
                            }
                        }
                        TextButton {
                            visible: settings.app.secrets.erp
                            text: settings.app.tr.keyring_clear
                            fontSize: Style.font.caption
                            onClicked: settings.app.write({ command: "secret_clear", acces: "erp" })
                        }
                    }
                }
                Hint { visible: !erpStore.visible || erpStore.value === "vault"; text: settings.app.tr.erp_hint }
                Field {
                    id: erpVaultField
                    visible: !erpStore.visible || erpStore.value === "vault"
                    placeholderText: settings.app.tr.erp_vault
                    text: settings.app.erpVault
                    onAccepted: settings.app.setSetting("erpVault", text.trim())
                }
                Field {
                    id: erpAccountField
                    visible: !erpStore.visible || erpStore.value === "vault"
                    placeholderText: settings.app.tr.erp_account
                    text: settings.app.erpAccount
                    onAccepted: settings.app.setSetting("erpAccount", text.trim())
                }
                // Libellé visible : le texte d'aide du champ disparaît dès qu'une valeur est saisie (QA du 18/10).
                Hint { text: settings.app.tr.erp_fiscal_month; opacity: 0.8 }
                Field {
                    id: erpFiscalField
                    placeholderText: settings.app.tr.erp_fiscal_month
                    text: String(settings.app.erpFiscalMonth)
                    onAccepted: {
                        const month = parseInt(text.trim(), 10);
                        if (month >= 1 && month <= 12)
                            settings.app.setSetting("erpFiscalMonth", month);
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    TextButton {
                        visible: !erpStore.visible || erpStore.value === "vault"
                        text: settings.app.tr.erp_save_test
                        onClicked: {
                            settings.app.setSetting("erpStore", "vault");
                            settings.app.setSetting("erpVault", erpVaultField.text.trim());
                            settings.app.setSetting("erpAccount", erpAccountField.text.trim());
                            settings.app.send("erp_test");
                        }
                    }
                    Hint {
                        visible: settings.app.erpStatus !== ""
                        opacity: 0.9
                        text: (settings.app.erpOk ? "✓ " : "✗ ") + settings.app.erpStatus
                    }
                }
                Hint { text: settings.app.tr.erp_readonly; opacity: 0.45 }
            }
            // ----- Portail : une EXTENSION PRIVÉE (extensions.py), jamais livrée avec le plugin. Le
            // bloc n'apparaît que si elle est installée : le moteur ne met alors l'accès dans la liste.
            ColumnLayout {
                visible: settings.section === "access"
                         && (settings.app.access || []).some(a => a.key === "portail")
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Label { text: settings.app.tr.label_portail }
                Hint { text: settings.accessState("portail"); opacity: 0.9 }
                Hint { text: settings.app.tr.portail_hint }
                Field {
                    id: portailUrlField
                    placeholderText: settings.app.tr.portail_url
                    text: settings.app.portailUrl
                    onAccepted: settings.app.setSetting("portailUrl", text.trim())
                }
                Field {
                    id: portailVaultField
                    placeholderText: settings.app.tr.portail_vault
                    text: settings.app.portailVault
                    onAccepted: settings.app.setSetting("portailVault", text.trim())
                }
                Field {
                    id: portailAccountField
                    placeholderText: settings.app.tr.portail_account
                    text: settings.app.portailAccount
                    onAccepted: settings.app.setSetting("portailAccount", text.trim())
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    TextButton {
                        text: settings.app.tr.portail_save_test
                        onClicked: {
                            settings.app.setSetting("portailUrl", portailUrlField.text.trim());
                            settings.app.setSetting("portailVault", portailVaultField.text.trim());
                            settings.app.setSetting("portailAccount", portailAccountField.text.trim());
                            settings.app.send("portail_test");
                        }
                    }
                    Hint {
                        visible: settings.app.portailStatus !== ""
                        opacity: 0.9
                        text: (settings.app.portailOk ? "✓ " : "✗ ") + settings.app.portailStatus
                    }
                }
                Hint { text: settings.app.tr.portail_writes; opacity: 0.45 }
            }
            // ----- Robot : un Reachy Mini, son corps. Même bloc que les autres : l'état réel en
            // tête, l'adresse du service du robot (ce portable ou une autre machine), tester. Le
            // reflet ne fait que montrer, comme l'avatar (spec 2026-10-09-corps-reachy-mini).
            ColumnLayout {
                visible: settings.section === "access"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Label { text: settings.app.tr.label_robot }
                Hint { text: settings.accessState("robot"); opacity: 0.9 }
                Hint { text: settings.app.tr.robot_hint }
                Field {
                    id: robotUrlField
                    placeholderText: settings.app.tr.robot_url
                    text: settings.app.robotUrl
                    onAccepted: settings.app.setSetting("robotUrl", text.trim())
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    TextButton {
                        text: settings.app.tr.robot_save_test
                        onClicked: {
                            settings.app.setSetting("robotUrl", robotUrlField.text.trim());
                            settings.app.send("robot_test");
                        }
                    }
                    Hint {
                        visible: settings.app.robotStatus !== ""
                        opacity: 0.9
                        text: (settings.app.robotOk ? "✓ " : "✗ ") + settings.app.robotStatus
                    }
                }
                // Branché ICI : sa voix et son oreille par le robot. Les deux ensemble ou rien — c'est
                // ce qui rend son micro sans écho. Le bouton écrit les deux réglages de Voix, rien d'autre.
                TextButton {
                    visible: settings.app.robotSink !== "" && settings.app.robotSource !== ""
                    text: settings.app.tr.robot_use_audio
                    onClicked: {
                        settings.app.setSetting("sortie", settings.app.robotSink);
                        settings.app.setSetting("micro", settings.app.robotSource);
                    }
                }
                Hint {
                    visible: settings.app.robotSink !== "" && settings.app.robotSource !== ""
                    text: settings.app.tr.robot_audio_hint
                    opacity: 0.6
                }
                Hint { text: settings.app.tr.robot_note; opacity: 0.45 }
            }


            // ----- Rôles : QUI répond. Le rôle se CHOISIT sous le nom d'Alison, pas ici : ici, des
            // fiches en lecture qui disent ce que chaque rôle est et tout ce qu'il RETIRE — plafond
            // de mode, accès fermés, mots interdits, carnet. Avant, on choisissait un rôle sans
            // rien voir de ce qu'il fermait (audit du 21/09).
            ColumnLayout {
                id: rolePane
                visible: settings.section === "roles"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                // Formulaire ouvert ? Et pour quel rôle ("" = un nouveau).
                property bool editing: false
                property string editName: ""
                property bool confirmDelete: false
                function open(card) {
                    confirmDelete = false;
                    editName = card ? card.name : "";
                    roleName.text = card ? card.name : "";
                    roleLabelField.text = card ? (card.label || "") : "";
                    roleDescription.text = card ? (card.description || "") : "";
                    roleDescription.cursorPosition = 0;     // sinon le champ montre la FIN du texte (recette 21/09)
                    roleLabelField.cursorPosition = 0;
                    personaEdit.text = "";
                    rolePersonaPath.text = "";
                    var closes = card ? (card.closes || []) : [];
                    var open = settings.app.modeOrder.filter(function (m) { return closes.indexOf(m) < 0; });
                    roleForm.ceiling = open.length ? open[open.length - 1] : "chat";
                    roleForm.access = card ? (card.access === null || card.access === undefined
                                              ? settings.app.access.map(function (a) { return a.key; })
                                              : card.access.slice())
                                           : settings.app.access.map(function (a) { return a.key; });
                    roleForbid.text = card ? (card.forbid || []).join(", ") : "";
                    roleForm.memory = card && card.memory === "shared" ? "shared" : "separate";
                    var others = settings.app.rolesAvailable.filter(function (r) { return r.name !== editName; }).map(function (r) { return r.name; });
                    roleForm.delegate = card && card.delegate !== null && card.delegate !== undefined
                                        ? card.delegate.filter(function (n) { return others.indexOf(n) >= 0; })
                                        : others;
                    settings.app.roleSaveError = "";
                    editing = true;
                }
                function close() {
                    editing = false;
                    editName = "";
                    confirmDelete = false;
                }
                // Enregistré : le formulaire se ferme ; refusé : il reste avec le message.
                Connections {
                    target: settings.app
                    function onRoleSaveCountChanged() {
                        if (settings.app.roleSaveError === "")
                            rolePane.close();
                    }
                }
                Label { text: settings.app.tr.section_roles.toUpperCase() }
                Hint {
                    visible: settings.omarchy
                    text: settings.app.rolesAvailable.length === 0
                          ? settings.app.tr.role_none_installed + " " + settings.app.tr.role_where
                          : settings.app.tr.role_hint
                }
                Hint {
                    visible: settings.omarchy && settings.app.rolePaths.length > 0
                    opacity: 0.55
                    text: settings.app.tr.role_paths + " : " + settings.app.rolePaths.join(", ")
                }
                // Un rôle en appelle un autre : l'interrupteur général ; chaque fiche dit à qui.
                SwitchRow {
                    visible: settings.omarchy && settings.app.rolesAvailable.length > 1 && !rolePane.editing
                    label: settings.app.tr.delegation_switch
                    checked: settings.app.delegation
                    onToggled: settings.app.setSetting("delegation", !settings.app.delegation)
                }
                Hint { visible: settings.omarchy && settings.app.rolesAvailable.length > 1 && !rolePane.editing; text: settings.app.tr.delegation_hint }
                // Alison elle-même : toujours là, personnalisable (18/10). Sa personnalité est un
                // fichier privé écrit par le moteur ; « Revenir à l'original » le retire.
                RoleCard {
                    id: selfCard
                    visible: settings.omarchy && !rolePane.editing
                    property bool editingPersona: false
                    function cancelPersona() {
                        editingPersona = false;
                        selfEdit.forceActiveFocus();
                    }
                    title: settings.app.companionName
                    tag: (settings.app.role === "" ? settings.app.tr.role_current : settings.app.tr.role_no_role) + " · "
                         + (settings.app.personaCustom ? settings.app.tr.persona_tag_custom : settings.app.tr.persona_tag_shipped)
                    current: settings.app.role === ""
                    Hint { text: settings.app.tr.role_self_desc }
                    Hint { visible: settings.app.personaCustom && !selfCard.editingPersona; text: settings.app.tr.persona_custom_hint }
                    SwitchRow {
                        visible: settings.app.omarchySkill
                        label: settings.app.tr.omarchy_knowledge
                        checked: settings.app.omarchyKnowledge
                        onToggled: settings.app.setSetting("omarchyKnowledge", !settings.app.omarchyKnowledge)
                    }
                    Hint { visible: settings.app.omarchySkill; text: settings.app.tr.omarchy_knowledge_hint; opacity: 0.45 }
                    ColumnLayout {
                        visible: selfCard.editingPersona
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        Field { id: selfName; placeholderText: settings.app.tr.persona_name }
                        Hint { text: settings.app.tr.persona_text_hint }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: Math.max(Style.space(96), selfPersona.implicitHeight + Style.space(16))
                            radius: settings.app.rounded(6)
                            color: Style.normalFill
                            border.width: Style.controlBorderWidth(selfPersona.activeFocus, selfPersonaHover.hovered)
                            border.color: selfPersona.activeFocus ? Style.focusBorderColor : Util.alpha(Color.menu.text, 0.22)
                            HoverHandler { id: selfPersonaHover }
                            TextEdit {
                                id: selfPersona
                                anchors.fill: parent
                                anchors.margins: Style.space(8)
                                wrapMode: TextEdit.Wrap
                                color: Color.menu.text
                                selectionColor: Util.alpha(Color.accent, 0.35)
                                font.family: Style.font.menuFamily
                                font.pixelSize: Style.font.bodySmall
                                activeFocusOnTab: true
                                Accessible.role: Accessible.EditableText
                                Accessible.name: settings.app.tr.persona_text
                            }
                        }
                    }
                    RowLayout {
                        spacing: Style.spacing.md
                        TextButton {
                            id: selfEdit
                            text: selfCard.editingPersona ? settings.app.tr.persona_save : settings.app.tr.persona_edit
                            fontSize: Style.font.caption
                            onClicked: {
                                if (!selfCard.editingPersona) {
                                    selfName.text = settings.app.companionName;
                                    selfPersona.text = settings.app.personaText;
                                    selfCard.editingPersona = true;
                                    return;
                                }
                                var name = selfName.text.trim();
                                if (name !== "" && name !== settings.app.companionName)
                                    settings.app.setSetting("name", name);
                                settings.app.write({ command: "persona_save", text: selfPersona.text });
                                selfCard.editingPersona = false;
                            }
                        }
                        TextButton {
                            visible: selfCard.editingPersona
                            text: settings.app.tr.role_form_cancel
                            fontSize: Style.font.caption
                            onClicked: selfCard.cancelPersona()
                        }
                        TextButton {
                            visible: settings.app.personaCustom && !selfCard.editingPersona
                            text: settings.app.tr.persona_reset
                            fontSize: Style.font.caption
                            onClicked: settings.app.write({ command: "persona_reset" })
                        }
                    }
                }
                Repeater {
                    model: settings.omarchy && !rolePane.editing ? settings.app.rolesAvailable : []
                    RoleCard {
                        id: roleCard
                        required property var modelData
                        title: modelData.label
                        tag: settings.app.role === modelData.name ? settings.app.tr.role_current : ""
                        current: settings.app.role === modelData.name
                        Hint { visible: text !== ""; text: roleCard.modelData.description || "" }
                        Hint { text: settings.roleModesLine(roleCard.modelData) }
                        Hint { text: settings.roleAccessLine(roleCard.modelData) }
                        Hint {
                            visible: (roleCard.modelData.forbid || []).length > 0
                            text: settings.app.tr.role_forbid + " : " + (roleCard.modelData.forbid || []).slice(0, 6).join(", ")
                        }
                        Hint {
                            text: roleCard.modelData.memory === "shared" ? settings.app.tr.role_memory_shared
                                                                          : settings.app.tr.role_memory_separate
                        }
                        Hint { visible: settings.app.rolesAvailable.length > 1; text: settings.roleDelegateLine(roleCard.modelData) }
                        Hint { text: roleCard.modelData.folder || ""; opacity: 0.4 }
                        Hint { visible: roleCard.modelData.editable !== true; text: settings.app.tr.role_readonly_hint; opacity: 0.45 }
                        RowLayout {
                            spacing: Style.spacing.md
                            TextButton {
                                visible: roleCard.modelData.editable === true
                                text: settings.app.tr.role_edit
                                fontSize: Style.font.caption
                                onClicked: rolePane.open(roleCard.modelData)
                            }
                            TextButton {
                                text: settings.app.tr.role_open_persona
                                fontSize: Style.font.caption
                                onClicked: settings.app.write({ command: "open_role", name: roleCard.modelData.name })
                            }
                        }
                    }
                }
                // ----- Le formulaire : créer ou modifier. Il n'offre que des RESTRICTIONS (plafond,
                // accès permis, mots interdits, carnet) — un rôle ne peut rien ouvrir, le formulaire
                // non plus. Le moteur écrit le dossier ; le panneau ne touche jamais au disque.
                ColumnLayout {
                    id: roleForm
                    visible: rolePane.editing
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    property string ceiling: "assistant"
                    property var access: []
                    property string memory: "separate"
                    property var delegate: []
                    Label { text: rolePane.editName === "" ? settings.app.tr.role_new : settings.app.t("role_editing", rolePane.editName) }
                    Hint { text: settings.app.tr.role_form_name_hint }
                    Field {
                        id: roleName
                        enabled: rolePane.editName === ""
                        opacity: enabled ? 1 : 0.6
                        placeholderText: settings.app.tr.role_form_name
                    }
                    Field { id: roleLabelField; placeholderText: settings.app.tr.role_form_label }
                    Field { id: roleDescription; placeholderText: settings.app.tr.role_form_description }
                    Label { text: settings.app.tr.role_form_persona }
                    Hint { text: rolePane.editName === "" ? settings.app.tr.role_form_persona_hint : settings.app.tr.role_form_persona_keep }
                    // Plusieurs lignes : le kit n'a qu'un champ d'une ligne, on habille un TextEdit
                    // avec les mêmes jetons (bordure, fond, police) que TextField.
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Math.max(Style.space(96), personaEdit.implicitHeight + Style.space(16))
                        radius: settings.app.rounded(6)
                        color: Style.normalFill
                        border.width: Style.controlBorderWidth(personaEdit.activeFocus, personaHover.hovered)
                        border.color: personaEdit.activeFocus ? Style.focusBorderColor : Util.alpha(Color.menu.text, 0.22)
                        HoverHandler { id: personaHover }
                        TextEdit {
                            id: personaEdit
                            anchors.fill: parent
                            anchors.margins: Style.space(8)
                            wrapMode: TextEdit.Wrap
                            color: Color.menu.text
                            selectionColor: Util.alpha(Color.accent, 0.35)
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.bodySmall
                            activeFocusOnTab: true
                            Accessible.role: Accessible.EditableText
                            Accessible.name: settings.app.tr.role_form_persona
                        }
                    }
                    Field { id: rolePersonaPath; placeholderText: settings.app.tr.role_form_persona_path }
                    Label { text: settings.app.tr.role_form_ceiling }
                    ButtonGroup {
                        value: roleForm.ceiling
                        options: settings.app.modes.map(function (m) { return { value: m.value, label: m.label }; })
                        foreground: Color.menu.text
                        background: "transparent"
                        fontFamily: Style.font.menuFamily
                        onChanged: function (picked) { roleForm.ceiling = picked; }
                    }
                    Hint { text: settings.app.tr.role_form_ceiling_hint }
                    Label { text: settings.app.tr.role_form_access }
                    Flow {
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        Repeater {
                            model: settings.app.access
                            TextButton {
                                required property var modelData
                                readonly property bool on: roleForm.access.indexOf(modelData.key) >= 0
                                text: (on ? "☑ " : "☐ ") + settings.app.tr["access_" + modelData.key]
                                foreground: on ? Color.accent : Color.menu.text
                                Accessible.role: Accessible.CheckBox
                                Accessible.checked: on
                                onClicked: {
                                    var next = roleForm.access.filter(function (k) { return k !== modelData.key; });
                                    if (!on)
                                        next.push(modelData.key);
                                    roleForm.access = next;
                                }
                            }
                        }
                    }
                    Hint { text: settings.app.tr.role_form_access_hint }
                    Label { text: settings.app.tr.role_form_forbid }
                    Field { id: roleForbid; placeholderText: settings.app.tr.role_form_forbid_hint }
                    Label { visible: delegateTargets.count > 0; text: settings.app.tr.role_delegate_title }
                    Flow {
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        Repeater {
                            id: delegateTargets
                            model: settings.app.rolesAvailable.filter(function (r) { return r.name !== rolePane.editName; })
                            TextButton {
                                required property var modelData
                                readonly property bool on: roleForm.delegate.indexOf(modelData.name) >= 0
                                text: (on ? "☑ " : "☐ ") + modelData.label
                                foreground: on ? Color.accent : Color.menu.text
                                Accessible.role: Accessible.CheckBox
                                Accessible.checked: on
                                onClicked: {
                                    var next = roleForm.delegate.filter(function (n) { return n !== modelData.name; });
                                    if (!on)
                                        next.push(modelData.name);
                                    roleForm.delegate = next;
                                }
                            }
                        }
                    }
                    Hint { visible: delegateTargets.count > 0; text: settings.app.tr.role_delegate_hint }
                    Label { text: settings.app.tr.role_form_memory }
                    ButtonGroup {
                        value: roleForm.memory
                        options: [{ value: "separate", label: settings.app.tr.role_memory_separate },
                                  { value: "shared", label: settings.app.tr.role_memory_shared }]
                        foreground: Color.menu.text
                        background: "transparent"
                        fontFamily: Style.font.menuFamily
                        onChanged: function (picked) { roleForm.memory = picked; }
                    }
                    Hint {
                        visible: settings.app.roleSaveError !== "" && rolePane.editing
                        color: Color.urgent
                        opacity: 1
                        text: settings.app.roleSaveError
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Style.spacing.md
                        TextButton {
                            text: rolePane.editName === "" ? settings.app.tr.role_form_create : settings.app.tr.role_form_save
                            onClicked: settings.app.write({ command: "role_save", form: {
                                name: rolePane.editName === "" ? roleName.text.trim() : rolePane.editName,
                                label: roleLabelField.text.trim(), description: roleDescription.text.trim(),
                                persona_text: personaEdit.text.trim(), persona_path: rolePersonaPath.text.trim(),
                                ceiling: roleForm.ceiling, access: roleForm.access,
                                forbid: roleForbid.text, memory: roleForm.memory,
                                // Tous cochés = absent (tous, y compris un rôle installé plus tard).
                                delegate: roleForm.delegate.length === delegateTargets.count ? null : roleForm.delegate } })
                        }
                        TextButton { text: settings.app.tr.role_form_cancel; onClicked: rolePane.close() }
                        Item { Layout.fillWidth: true }
                        TextButton {
                            visible: rolePane.editName !== ""
                            text: rolePane.confirmDelete ? settings.app.tr.role_form_delete_confirm : settings.app.tr.role_form_delete
                            foreground: Color.urgent
                            onClicked: {
                                // Deux clics : le premier arme, le second supprime. Le dossier part, le
                                // carnet séparé du rôle reste dans l'état privé.
                                if (!rolePane.confirmDelete) {
                                    rolePane.confirmDelete = true;
                                    return;
                                }
                                settings.app.write({ command: "role_delete", name: rolePane.editName });
                            }
                        }
                    }
                }
                RowLayout {
                    visible: !rolePane.editing && settings.omarchy
                    spacing: Style.spacing.md
                    TextButton { text: settings.app.tr.role_new; onClicked: rolePane.open(null) }
                }
                // Rôles d'exemple livrés avec le plugin (18/10) : rien n'est ajouté sans ce clic, et un
                // exemple passe par le même chemin que le formulaire — il ne peut que retirer.
                Label {
                    visible: !rolePane.editing && settings.omarchy && settings.availableExamples().length > 0
                    text: settings.app.tr.role_examples
                }
                Repeater {
                    model: !rolePane.editing && settings.omarchy ? settings.availableExamples() : []
                    RoleCard {
                        id: exampleCard
                        required property var modelData
                        title: modelData.label
                        tag: settings.app.tr.role_example_tag
                        Hint { text: exampleCard.modelData.description }
                        TextButton {
                            text: settings.app.tr.role_example_add
                            fontSize: Style.font.caption
                            Accessible.name: settings.app.tr.role_example_add + " : " + exampleCard.modelData.label
                            onClicked: {
                                settings.app.roleSaveError = "";
                                settings.app.write({ command: "role_example", name: exampleCard.modelData.name });
                            }
                        }
                    }
                }
                // L'échec d'un ajout d'exemple se lit ici : le formulaire, qui l'affiche d'habitude, est fermé.
                Text {
                    Layout.fillWidth: true
                    visible: settings.app.roleSaveError !== "" && !rolePane.editing && settings.omarchy
                    text: settings.app.roleSaveError
                    wrapMode: Text.Wrap
                    color: Color.urgent
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.bodySmall
                }
                // Un rôle se crée en déposant un dossier. Le chemin doit être lisible ET ouvrable :
                // sinon il faut le deviner, et personne n'écrit un rôle qu'on ne sait pas où poser.
                RowLayout {
                    visible: settings.omarchy
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Text {
                        Layout.fillWidth: true
                        text: settings.app.rolesFolder
                        elide: Text.ElideMiddle
                        color: Color.menu.text
                        opacity: 0.55
                        font.family: Style.font.menuFamily
                        font.pixelSize: Style.font.caption
                    }
                    Button {
                        text: settings.app.tr.role_open_folder
                        focusable: true
                        bordered: true
                        foreground: Color.menu.text
                        fontFamily: Style.font.menuFamily
                        fontSize: Style.font.caption
                        onClicked: settings.app.send("open_roles")
                    }
                }
            }

            // ----- Voix
            ColumnLayout {
                visible: settings.section === "voice"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Label { text: settings.app.tr.label_voice }
                // Premier usage : la voix locale n'est pas livrée avec le plugin. Rien ne s'installe
                // sans ce clic ; le moteur annonce chaque étape.
                ColumnLayout {
                    visible: !settings.app.voiceReady || !settings.app.voiceComplete || settings.app.voiceSetupRunning
                             || settings.app.voiceSetupText !== ""
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Hint {
                        text: settings.app.voiceSetupText !== "" ? settings.app.voiceSetupText
                              : (settings.app.voiceReady ? settings.app.tr.voice_incomplete_hint : settings.app.tr.voice_missing)
                    }
                    TextButton {
                        visible: !settings.app.voiceReady || !settings.app.voiceComplete
                        text: settings.app.voiceSetupRunning ? settings.app.tr.voice_installing
                              : (settings.app.voiceReady ? settings.app.tr.voice_complete : settings.app.tr.voice_install)
                        enabled: settings.app.connected && !settings.app.voiceSetupRunning
                        opacity: enabled ? 1 : 0.45
                        onClicked: settings.app.send("install_voice")
                    }
                }
                // Un dossier complet peut être altéré : garder une réparation explicite sur clic,
                // sans hacher les gros modèles à chaque rafraîchissement du panneau.
                TextButton {
                    visible: settings.app.voiceReady && settings.app.voiceComplete
                    text: settings.app.tr.voice_verify
                    enabled: settings.app.connected && !settings.app.voiceSetupRunning
                    opacity: enabled ? 1 : 0.45
                    onClicked: settings.app.send("install_voice")
                }
                SwitchRow {
                    label: settings.app.tr.voice_read_aloud
                    checked: settings.app.voice
                    onToggled: settings.app.setSetting("voice", !settings.app.voice)
                }
                SwitchRow {
                    label: settings.app.tr.voice_conversation
                    checked: settings.app.conversation
                    onToggled: settings.app.toggleConversation()
                }
                SwitchRow {
                    label: settings.app.t("voice_wake", settings.app.wakeLabel)
                    checked: settings.app.wakeEnabled
                    onToggled: settings.app.setSetting("wakeword", !settings.app.wakeEnabled)
                }
                // Moteur de transcription (spec 2026-10-09-transcription-parakeet) : Parakeet par
                // défaut, Whisper pour revenir en arrière d'un clic. Le serveur est relancé seul.
                Label { text: settings.app.tr.label_stt }
                ButtonGroup {
                    value: settings.app.sttEngine
                    options: [{ value: "parakeet", label: settings.app.tr.stt_parakeet },
                              { value: "whisper", label: settings.app.tr.stt_whisper }]
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (picked) { settings.app.setSetting("sttEngine", picked); }
                }
                Hint { text: settings.app.tr.stt_hint; opacity: 0.6 }
                Label { text: settings.app.tr.label_strip }
                ButtonGroup {
                    value: settings.app.voiceStrip
                    options: [{ value: "barre", label: settings.app.tr.strip_bar },
                              { value: "bas", label: settings.app.tr.strip_bottom },
                              { value: "panneau", label: settings.app.tr.strip_panel }]
                    foreground: Color.menu.text
                    background: "transparent"
                    fontFamily: Style.font.menuFamily
                    onChanged: function (picked) { settings.app.setSetting("voiceStrip", picked); }
                }
                Hint { text: settings.app.tr.strip_hint }
                SwitchRow {
                    label: settings.app.tr.voice_barge
                    checked: settings.app.barge
                    enabled: settings.app.wakeEnabled
                    opacity: enabled ? 1 : 0.45
                    onToggled: settings.app.setSetting("barge", !settings.app.barge)
                }
                Hint { text: settings.app.tr.barge_hint; opacity: 0.6 }
                Field {
                    id: microField
                    placeholderText: settings.app.tr.voice_mic
                    text: settings.app.micro
                    onAccepted: settings.app.setSetting("micro", text.trim())
                }
                Hint { text: settings.app.tr.mic_hint; opacity: 0.6 }
                Field {
                    id: sortieField
                    placeholderText: settings.app.tr.voice_sortie
                    text: settings.app.sortie
                    onAccepted: settings.app.setSetting("sortie", text.trim())
                }
                Hint { text: settings.app.tr.sortie_hint; opacity: 0.6 }
                SwitchRow {
                    label: settings.app.tr.voice_decide
                    checked: settings.app.voiceDecide
                    enabled: settings.app.wakeEnabled
                    opacity: enabled ? 1 : 0.45
                    onToggled: settings.app.setSetting("voiceDecide", !settings.app.voiceDecide)
                }
                Hint { text: settings.app.tr.decide_hint; opacity: 0.6 }
                Hint {
                    text: settings.app.service && settings.app.service.errorText
                          ? settings.app.service.errorText
                          : (settings.app.wakeEnabled
                             ? settings.app.t("wake_on_hint", settings.app.wakeLabel)
                             : settings.app.tr.wake_off_hint)
                }
            }

            // ----- Mémoire : le carnet d'Alison, tenu par le moteur (fichier privé)
            // Rangé par thème, daté, corrigeable : ce que tu vois ici est exactement ce qu'elle
            // emporte au début de chaque conversation.
            ColumnLayout {
                id: memoryPane
                // Souvenir en cours de correction (son texte d'origine), "" si aucun.
                property string editing: ""
                property string editTopic: ""
                visible: settings.section === "memory"
                Layout.fillWidth: true
                spacing: Style.spacing.lg
                Label { text: settings.app.tr.label_memory }
                Hint { text: settings.app.tr.memory_hint }
                Hint { visible: settings.app.memory.length === 0; text: settings.app.tr.memory_none; opacity: 0.4 }

                Repeater {
                    model: settings.app.memoryTopics
                    ColumnLayout {
                        id: topicGroup
                        required property string modelData
                        readonly property var facts: settings.app.memoryIn(topicGroup.modelData)
                        visible: topicGroup.facts.length > 0
                        Layout.fillWidth: true
                        spacing: Style.spacing.sm

                        Text {
                            Layout.fillWidth: true
                            text: settings.app.tr["topic_" + topicGroup.modelData]
                            color: Color.menu.text
                            opacity: 0.45
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.caption
                            font.letterSpacing: 1
                        }

                        Repeater {
                            model: topicGroup.facts
                            ColumnLayout {
                                id: fact
                                required property var modelData
                                readonly property bool editing: memoryPane.editing === fact.modelData.text
                                Layout.fillWidth: true
                                spacing: Style.spacing.xs

                                // Lecture : le souvenir, sa date, et de quoi le corriger ou le retirer.
                                RowLayout {
                                    visible: !fact.editing
                                    Layout.fillWidth: true
                                    spacing: Style.spacing.md
                                    Text {
                                        Layout.fillWidth: true
                                        text: fact.modelData.text
                                        wrapMode: Text.Wrap
                                        color: Color.menu.text
                                        font.family: Style.font.menuFamily
                                        font.pixelSize: Style.font.bodySmall
                                    }
                                    Text {
                                        visible: text !== ""
                                        // Locale explicite : sans elle la date sort en anglais quel
                                        // que soit le réglage de langue du panneau.
                                        text: fact.modelData.at > 0
                                              ? new Date(fact.modelData.at * 1000).toLocaleDateString(
                                                    Qt.locale(settings.app.lang === "en" ? "en_US" : "fr_FR"),
                                                    settings.app.tr.memory_date)
                                              : ""
                                        color: Color.menu.text
                                        opacity: 0.35
                                        font.family: Style.font.menuFamily
                                        font.pixelSize: Style.font.caption
                                    }
                                    TextButton {
                                        text: settings.app.tr.memory_edit
                                        bordered: false
                                        fontSize: Style.font.caption
                                        onClicked: {
                                            memoryPane.editTopic = fact.modelData.topic || "other";
                                            memoryPane.editing = fact.modelData.text;
                                        }
                                    }
                                    TextButton {
                                        text: settings.app.tr.remove
                                        bordered: false
                                        fontSize: Style.font.caption
                                        onClicked: settings.app.send("forget_memory", fact.modelData.text)
                                    }
                                }

                                // Correction : le texte, le thème, puis Enregistrer. Échap annule.
                                ColumnLayout {
                                    visible: fact.editing
                                    Layout.fillWidth: true
                                    spacing: Style.spacing.sm
                                    Field {
                                        id: editField
                                        text: fact.modelData.text
                                        // Rouvrir la correction d'un autre souvenir doit repartir de son texte.
                                        onVisibleChanged: if (visible) { text = fact.modelData.text; forceActiveFocus(); }
                                        Keys.onEscapePressed: memoryPane.editing = ""
                                        onAccepted: {
                                            settings.app.editMemory(fact.modelData.text, text, memoryPane.editTopic);
                                            memoryPane.editing = "";
                                        }
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: Style.spacing.sm
                                        Repeater {
                                            model: settings.app.memoryTopics
                                            Button {
                                                required property string modelData
                                                text: settings.app.tr["topic_" + modelData]
                                                selected: memoryPane.editTopic === modelData
                                                focusable: true
                                                foreground: Color.menu.text
                                                fontFamily: Style.font.menuFamily
                                                fontSize: Style.font.caption
                                                onClicked: memoryPane.editTopic = modelData
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Style.spacing.md
                                        TextButton {
                                            text: settings.app.tr.memory_save
                                            fontSize: Style.font.caption
                                            onClicked: {
                                                settings.app.editMemory(fact.modelData.text, editField.text, memoryPane.editTopic);
                                                memoryPane.editing = "";
                                            }
                                        }
                                        TextButton {
                                            text: settings.app.tr.memory_cancel
                                            fontSize: Style.font.caption
                                            onClicked: memoryPane.editing = ""
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Field {
                        id: newFact
                        placeholderText: settings.app.tr.memory_placeholder
                        onAccepted: { settings.app.send("remember", text); text = ""; }
                    }
                    TextButton {
                        text: settings.app.tr.memory_add
                        onClicked: { settings.app.send("remember", newFact.text); newFact.text = ""; }
                    }
                }
                SwitchRow {
                    label: settings.app.tr.recall_label
                    checked: settings.app.recall
                    onToggled: settings.app.setSetting("recall", !settings.app.recall)
                }
                Hint { text: settings.app.tr.recall_hint }
                Hint {
                    visible: settings.app.notesDays > 0
                    opacity: 0.45
                    text: settings.app.t("memory_notes", settings.app.notesDays)
                }
                // ----- Le rêve : le tri, une fois par jour
                SwitchRow {
                    label: settings.app.tr.dream_label
                    checked: settings.app.dreams
                    onToggled: settings.app.setSetting("dreams", !settings.app.dreams)
                }
                Hint { text: settings.app.tr.dream_hint }
                Hint {
                    visible: !settings.app.dreamReport.at
                    opacity: 0.4
                    text: settings.app.tr.dream_none
                }
                ColumnLayout {
                    visible: !!settings.app.dreamReport.at
                    Layout.fillWidth: true
                    spacing: Style.spacing.xs
                    Hint { text: settings.app.t("dream_last", settings.app.dreamReport.at || "") }
                    Hint {
                        text: settings.app.t("dream_counts",
                                             settings.app.dreamReport.looked || 0,
                                             (settings.app.dreamReport.kept || []).length,
                                             (settings.app.dreamReport.replaced || []).length)
                    }
                    Repeater {
                        model: settings.app.dreamReport.kept || []
                        Text {
                            required property var modelData
                            Layout.fillWidth: true
                            text: "+ " + modelData[0] + (modelData[1] ? "  (" + modelData[1] + ")" : "")
                            wrapMode: Text.Wrap
                            color: Color.menu.text
                            opacity: 0.75
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.caption
                        }
                    }
                    Repeater {
                        model: settings.app.dreamReport.replaced || []
                        Text {
                            required property var modelData
                            Layout.fillWidth: true
                            text: "~ " + modelData[0] + "  →  " + modelData[1]
                            wrapMode: Text.Wrap
                            color: Color.menu.text
                            opacity: 0.6
                            font.family: Style.font.menuFamily
                            font.pixelSize: Style.font.caption
                        }
                    }
                    Hint {
                        visible: !!settings.app.dreamReport.undone
                        opacity: 0.5
                        text: settings.app.tr.dream_undone
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    TextButton {
                        text: settings.app.dreaming ? settings.app.tr.dream_running : settings.app.tr.dream_now
                        enabled: !settings.app.dreaming
                        fontSize: Style.font.caption
                        onClicked: settings.app.send("dream_now")
                    }
                    TextButton {
                        visible: !!settings.app.dreamReport.backup && !settings.app.dreamReport.undone
                        text: settings.app.tr.dream_undo
                        fontSize: Style.font.caption
                        onClicked: settings.app.send("undo_dream")
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Hint { text: settings.app.t("memory_count", settings.app.memory.length, settings.app.memoryMax) }
                    TextButton {
                        visible: settings.app.memory.length > 0
                        text: settings.app.tr.memory_clear
                        fontSize: Style.font.caption
                        onClicked: settings.app.send("clear_memory")
                    }
                }
            }

        }
    }
}
