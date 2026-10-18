# Contributing

Thanks for helping make Alison better! A few rules keep her safe and pleasant to use.

## Before you start

- **Open an issue first** for anything bigger than a typo, so we can agree on the approach.
- Security problems go through [SECURITY.md](SECURITY.md), never a public issue.

## Ground rules

1. **Safety does not regress.** A change may never let an action skip its card, open a refused
   location, or let a role *add* rights. The three guard layers (native permissions, `guard.py`,
   engine checks) must stay consistent.
2. **Both languages.** Every visible string lives in `lang/en.json` **and** `lang/fr.json`, with the
   same keys. No hard-coded text in QML.
3. **No personal data.** No names, private addresses, hostnames or secrets in code, tests or screenshots.
4. **Omarchy conventions.** The shell is the only writer of `shell.json`; the plugin never writes
   `bindings.lua`; processes are started with argument arrays.
5. **Evidence.** Describe how you tested, and add a test when the change allows it.

## Workflow

```bash
git clone https://github.com/lugio/oma-companion.git
cd oma-companion
python3 tests/test_backend.py
python3 tests/test_publication.py
omarchy plugin validate .
```

To try your copy: `omarchy plugin add file://$PWD --enable`, then `omarchy restart shell` after each
change (the plugin is kept loaded).

## Commits and pull requests

- One topic per pull request; small, focused commits with a clear message.
- Fill in the pull request template, including screenshots for any visible change.
- By contributing you agree that your work is released under [GPL-3.0-or-later](LICENSE).
