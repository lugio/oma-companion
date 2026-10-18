# Connections

← [Back to README](../README.md)

Home Assistant is disabled by default. Mail, accounting, private portal and robot access switches are
initially enabled, but require user-supplied connection details and a compatible permission mode before
they work. Existing saved switches are preserved.

| Connection | Helper | Scope |
|---|---|---|
| Home Assistant | `ha.py` | Assistant mode onward. Lights, heating and media; covers, switches, scripts and scenes require cards. Locks and alarms refused. |
| IMAP mail | `mail.py` | Read mode onward, read only. |
| Dolibarr | `dolibarr.py` | Read mode onward, read-only invoices, balances and accounting summaries. |
| Reachy Mini | `reachy.py` | Gestures and emotions; photos require cards. See [Robot](robot.md). |

## Credentials

Credentials come from a user-selected JSON vault or the system keyring (`secret-tool`); helpers hold
their own secrets and the agent never sees them. A secret is bound to its destination: it is only sent
over HTTPS, or over HTTP to a local-network address.

## Home watch

A home watch can be configured in `~/.config/omarchy-companion/maison.json`; no watch rules are supplied.

## Private extensions

Private connectors belong in `~/.config/omarchy-companion/extensions/`; none are shipped. Their constants
are read without executing the file, and files writable by other accounts are ignored.
