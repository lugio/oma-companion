# Maintainer notes

← [Back to README](../README.md)

## Store review

- Store installation executes no installer. The explicit **Install the voice** click in `backend.py`
  creates a venv and runs pip with fixed top-level versions. Transitive dependencies are not locked
  or hash-pinned: `--require-hashes` cannot be added safely without a complete, platform-tested lockfile.
  SHA-256 model verification is separate from Python package verification. OpenCV Zoo model URLs
  currently use `main`; changed bytes are rejected by the stored hashes.
- `systemctl` appears in `agents.py` / `guard.py` as a **refused command**, not an automatic service
  installation. The PipeWire restart in [Voice](voice.md) is a manual user operation.
- `sudo` and `pkexec` appear in refusal rules; the plugin does not request root access.
- `install.py` is a development copy tool, not the store installer.

## Development

Apply local code by restarting the shell: the plugin is kept loaded (`keepLoaded`).

```bash
python3 tests/test_backend.py
python3 tests/test_publication.py
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
