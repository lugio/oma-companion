# Privacy & data

← [Back to README](../README.md)

## What leaves the machine

- Conversation prompts and history go to the configured agent and its provider. Agent web searches
  send search text to its search service.
- Installation and optional vision downloads contact Hugging Face (`huggingface.co` and its download
  infrastructure), `alphacephei.com`, GitHub (`github.com`, its raw and release download hosts), and
  Google model storage (`storage.googleapis.com`). Python installation also contacts PyPI and its
  package hosts. Transitive model libraries may download their own models.
- User-configured connections contact Home Assistant, IMAP servers, Dolibarr, private connectors,
  the robot and configured cameras. A local model uses the configured endpoint.
- Images download only after a click: HTTPS, at most 8 MB, no SVG; local addresses are refused.

## What stays local

Speech, wake detection and transcription run locally. Memory and logs remain under
`~/.local/state/omarchy-companion` (directories 700, files 600).

## Memory

Memory includes a notebook, daily notes and conversation recall, with daily tidying while idle.
“Forget…” removes notebook content. **New conversation** (＋ in the panel header) clears the current
thread and agent session; **Delete conversation** (🗑, confirmed by a second click) also removes that
thread's entries from daily notes. Information already extracted into the notebook is managed in
Settings → Memory.

## Backup

Settings → Backup exports preferences and the home watch, plus optionally personality and local roles.
The personality and role switches let you omit those fields; omitting personality does not reset it on
restore. Vault/account/address pointers are included only when selected. The restore preview shows the
complete personality and role texts before approval.

Credential files (vaults, `ha.json`, keyrings), memory, conversations and private connector code are not
copied. **Free-form text may still contain confidential information or credentials entered by you**,
including personality, role descriptions, preferences and home rules. URL filtering is best effort,
not a guarantee that a backup contains no secrets. Review the JSON before sharing it. The automatic
pre-restore snapshot includes current personality, roles and pointers to allow recovery; it is private
(600 in a 700 directory) but may contain the same confidential text.

Restore ignores settings that grant rights (mode, enabled accesses, trusted sites, voice approval,
active role and agent endpoint). It never silently enables an access. Active roles cannot be replaced.

## Process arguments and reminders

Guard private paths and role restrictions are read from private policy files (600 in a 700 directory),
deleted with the agent session. A delegation request reaches the PreToolUse hook through JSON on stdin.
The hook rewrites the tool input before a shell starts, replacing the business question with a private
single-use file. The helper reads and deletes that file; leftover request files are removed with the
session. Neither helper nor parent-shell argv contains the question. Unknown/legacy forms and shell
here-documents are refused. Direct trusted callers can also supply stdin to the helper.

**Intentional exception:** reminder text is meant to be displayed in desktop notifications. The local
`omarchy reminder` command has no stdin message interface, so it receives the redacted text in argv and
stores it in a user systemd unit/message file. It can be visible through process inspection and unit
inspection before the notification. Redaction is heuristic; do not use reminders for confidential text.

## Web preview

Each supported Firefox/Chromium preview uses a new private profile (700), separate from the personal
browser. The profile is removed after browser exit, including closing the window manually, by an
independent cleanup watcher; explicit close also waits for exit before deleting it. Unsupported browser
families fail closed rather than falling back to a persistent personal profile. A machine crash or a
forced kill of the cleanup watcher can leave an unused profile on disk; it is never reused on the next
opening and can be removed from the private state directory.

## Removal

```bash
omarchy plugin remove io.github.lugio.companion
```

Remove your shortcut separately. State, models and the voice environment remain under
`~/.local/state/omarchy-companion` and `~/.local/share/omarchy-companion`; remove them manually if desired.
Remove the optional PipeWire configuration using the [undo instructions](voice.md#echo-cancellation-optional).
