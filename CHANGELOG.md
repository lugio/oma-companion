# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.17.4] — 2026-10-19

### Security
- Download the complete six-file faster-whisper-small snapshot at a fixed commit on the explicit voice-install click, checking each SHA-256 before renaming its `.part` file.
- Verify the local Whisper files before loading; disable model-name overrides and implicit downloads during listening or fallback. Missing or altered files are refused with French/English installation guidance.

### Changed
- Offer voice completion when the pinned local Whisper folder is missing, even if Parakeet is already installed, and keep an explicit verify/repair action for complete installations. Correct download estimates and first-listen messages.
- Document model attributions, the unresolved Lessac corpus restrictions and three English medium voice candidates with documented training provenance. Keep the existing English voice unchanged.

## [0.17.3] — 2026-10-19

### Security
- Verify the IMAP server's certificate and hostname before sending the mailbox login. Python's
  `imaplib.IMAP4_SSL` checks neither by default, so an attacker on the network could impersonate the
  mail server and receive the credentials. An untrusted certificate now stops the connection with a
  clear message. Reported during the Omarchy store review.

## [0.17.2] — 2026-10-19

### Security
- Reject mutating or executable variants of pre-authorized read commands in Read mode; require cards
  in action modes. Preserve arguments after the command name; remove AWK and configuration-driven tools from automatic approvals.
- Reject shell expansions in sensitive helper calls; restrict desktop launchers to a closed catalogue.
- Reject non-canonical imported role names before checking existing and active roles.
- Move guard private paths and restrictions into private policy files; rewrite delegated questions to single-use private files before shell execution.
- Show complete edits, multi-edits and file creations in scrollable approval cards.
- Use a fresh isolated browser profile for each supported web preview and clean it after exit.

### Changed
- Let users exclude personality and roles from backups and inspect their full text in restore previews.
  Clarify that free-form text may contain confidential information.
- Document the intentional reminder-argument exception, systemctl permissions and Claude Code 2.1.*
  family certification.

## [0.17.1] — 2026-10-19

### Security
- The agent's system prompt (which includes the user's notebook) and its settings (which list private
  locations) are no longer passed as command-line arguments, readable by any process through `ps`.
  They go through private files (600, in a 700 directory under `$XDG_RUNTIME_DIR`), deleted when the
  session closes. Reported during the Omarchy store review.

## [0.17.0] — 2026-10-19

First public release.

### Added
- Panel, bar widget and background engine for Omarchy 4, in English and French.
- First-run wizard (language, brain, starting mode, name, voice, connections, shortcut).
- Five permission modes with approval cards, private locations and a three-layer guard.
- Roles that can only remove rights, with *Writing*, *Home* and *Accounting (read-only)* examples.
- Local voice on request: Piper speech, Vosk wake word, Parakeet / Whisper transcription,
  hands-free conversation, optional echo-cancelled microphone example.
- Memory: notebook, daily notes, recall, daily tidying; *New* and *Delete conversation* buttons.
- Optional connections: Home Assistant, IMAP mail, Dolibarr — credentials in a vault or the system keyring.
- Backup and restore of preferences with preview; credential files are not copied (free-form text may contain confidential information).
- Optional Reachy Mini body with a paired settings page.

[0.17.3]: https://github.com/lugio/oma-companion/compare/v0.17.2...v0.17.3
[0.17.2]: https://github.com/lugio/oma-companion/compare/v0.17.1...v0.17.2
[0.17.1]: https://github.com/lugio/oma-companion/compare/v0.17.0...v0.17.1
[0.17.0]: https://github.com/lugio/oma-companion/releases/tag/v0.17.0
