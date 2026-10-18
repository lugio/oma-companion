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

Settings → Backup exports a readable JSON file: preferences, roles, Alison's personality and the home
watch — plus, only if you ask, the *pointers* (vault paths, accounts, addresses: not secrets, but they say
where secrets live). **Never exported:** tokens and passwords, memory and conversations, private
extensions, and anything that grants rights (mode, enabled accesses, trusted sites, voice approval,
active role). Restoring shows a preview first, saves the current state automatically, and never turns
anything back on.

## Removal

```bash
omarchy plugin remove io.github.lugio.companion
```

Remove your shortcut separately. State, models and the voice environment remain under
`~/.local/state/omarchy-companion` and `~/.local/share/omarchy-companion`; remove them manually if desired.
Remove the optional PipeWire configuration using the [undo instructions](voice.md#echo-cancellation-optional).
