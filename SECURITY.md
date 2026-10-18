# Security policy

Alison runs commands on behalf of an AI agent, so the permission guard is the heart of the project.
Reports are taken seriously.

## Supported versions

| Version | Supported |
|---|---|
| 0.17.x | ✅ |
| < 0.17 | ❌ |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's
[private vulnerability reporting](https://github.com/lugio/oma-companion/security/advisories/new)
and include:

- the mode and role in use, and the exact request or phrase;
- what Alison did versus what the guard should have done;
- your Omarchy version and the agent selected (`omarchy default agent`).

You will get an acknowledgement within a week. Fixes are released as soon as they are verified, and
reporters are credited unless they prefer otherwise.

## In scope

- an action that runs without its card, or a card that does not show what actually runs;
- access to a refused location (keys, keyrings, browser profiles, private locations, secret files);
- a role or a restored backup that **adds** rights;
- secrets leaking into logs, memory, backups or the agent's context;
- the robot settings page accepting an unpaired device.
