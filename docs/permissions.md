# Permissions

← [Back to README](../README.md)

Alison uses **Omarchy's default agent** (`omarchy default agent`). Claude Code currently provides the
complete permission guard. Codex can answer, but its file reads cannot be restricted by this
integration, so Code mode stays closed with it.

## Five modes

New installations start in **Chat**. Autonomous mode can only be selected by clicking, never by voice.

| Mode | Permissions |
|---|---|
| Chat | Answers only; no tools. |
| Read | Read files and inspect system state; no changes or program launches. |
| Assistant | Read access; changes require a confirmation card, with the exceptions below. |
| Code | Development sessions; reads without cards, writes and execution require cards. |
| Autonomous | Code permissions without cards; every action is logged. |

## Always refused

Root commands (`sudo`, `pkexec`), disk destruction, private keys, keyrings and browser profiles remain
blocked in every mode. Secret files (`.env`, `vault.json` and paths listed in Settings → Private
locations) are blocked outside Code mode. Native agent permissions, `guard.py`, and engine checks
enforce the rules. Commands such as `find -delete`, `sort -o`, `rg --pre` and non-local `curl` requests
require cards even when their program normally allows reads.

## Actions without cards

- explicitly enabled Home Assistant lights, heating and media;
- robot gestures;
- direct desktop commands such as reminders, notes, menus and requested screenshots;
- an action family approved as “always in this conversation” (never chained commands or interpreters);
- Autonomous actions.

Voice approval is disabled by default and applies only to the currently displayed card.

## Roles

A role is a persona with its own instructions. It can only **remove** rights — never add any. Roles are
folders dropped in `~/.config/omarchy-companion/roles` (`role.md` for the persona, `role.json` for what
it takes away); the folders listed in the `rolePaths` setting are read as well. Examples shipped with the
plugin (Settings → Roles): *Writing*, *Home*, *Accounting (read-only)*.
