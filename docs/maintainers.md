# Maintainer notes

← [Back to README](../README.md)

## Store review

- Store installation executes no installer. The explicit **Install the voice** click in `backend.py`
  creates a venv and runs pip with fixed top-level versions. Transitive dependencies are not locked
  or hash-pinned: `--require-hashes` cannot be added safely without a complete, platform-tested lockfile.
  SHA-256 model verification is separate from Python package verification. OpenCV Zoo model URLs
  currently use `main`; changed bytes are rejected by the stored hashes.
- `systemctl` is not globally refused. The native pre-authorized read subcommands are `status`,
  `list-units`, `list-unit-files`, `is-active`, `is-enabled`, plus `--user status` and
  `--user list-units`. The guard accepts only catalogued read options; an unknown or mutating variant
  is refused in Read mode and requires approval in action modes. Pager/environment overrides are not
  pre-authorized. No service is automatically installed by the store installer.
- For `systemctl --user`, catalogued mutations (`start`, `stop`, `restart`, `reload`, `try-restart`,
  `enable`, `disable`, `mask`, `unmask` on literal unit names, and `daemon-reload`) require an approval
  card in Assistant/Code. Autonomous mode executes them under its explicitly selected no-card policy.
  Unknown subcommands, service linking/editing and environment mutation are refused, even with approval.
  Starting a user service runs that service's configured program with the user's permissions.
  The PipeWire restart in [Voice](voice.md) is a manual user operation.
- `sudo` and `pkexec` appear in refusal rules; the plugin does not request root access.
- `install.py` is a development copy tool, not the store installer.

## Read-command catalogue

The guard validates a closed option catalogue for pre-authorized read utilities, including in Read mode.
Unknown options require a card in Assistant/Code and are refused in Read mode. AWK and tools capable of
loading executable project configuration (`git`, `npm`, `pip`, `qmllint`, `fastfetch`) are no longer pre-authorized;
they remain available by approval in action modes. Leading environment assignments also require approval.

## Delegation transport

The guard uses the official [PreToolUse updatedInput contract](https://code.claude.com/docs/en/hooks#pretooluse-decision-control)
to replace the delegation request before shell execution. It does not return an `allow` decision:
native permissions are still evaluated on the rewritten command. The private file is consumed once;
no shell here-document or quoted business question reaches a process argument. The regression test
replays the hook JSON and verifies the resulting command and single-use file.

## Agent compatibility

Claude Code certification currently covers the `2.1.*` family, not each exact patch release.
`agents.py` intentionally keeps that family check; rerun the adversarial tests when updating it.

## Development

Apply local code by restarting the shell: the plugin is kept loaded (`keepLoaded`).

```bash
python3 tests/test_backend.py
python3 tests/test_publication.py
python3 tests/test_audit_0172.py
python3 tests/qa_parcours.py
omarchy plugin validate .
```

`tests/check_traces.py` optionally reads a private trace list from `COMPANION_TRACES`.
`tests/check_harness.py` probes a real configured agent; it is not an isolated unit test.

## References

- https://omarchy.org/manual/shell-plugins/
- https://github.com/OHF-Voice/piper1-gpl
- https://alphacephei.com/vosk/models
- https://github.com/pollen-robotics/reachy_mini
