# Voice

← [Back to README](../README.md)

## Installing the local voice

Choose **Settings → Voice → Install the voice** (or the button in the first-run wizard). Only that click
creates the dedicated Python environment at `~/.local/share/omarchy-companion/.venv` and downloads
packages and models (about 1.3 GB of model downloads, plus Python packages; extracted files and the environment need additional disk space). Piper, Vosk, faster-whisper and sherpa-onnx versions are pinned.
Downloaded models are **verified by SHA-256**; not every download host provides immutable commit URLs.

Speech, wake detection and transcription then run locally.

## Wake word

French and English Vosk models are included in the downloader; the default wake phrase follows the
selected language (*“Hey Alison”* in English, *“Salut Alison”* in French). Custom wake phrases must use
words the selected Vosk model can recognize.

## Transcription

Parakeet (fast) is the default; Whisper takes over on its own if Parakeet is missing. *Install the voice*
downloads both. Whisper is the fixed `Systran/faster-whisper-small` snapshot
`536b0662742c02347bc0e980a01041f333bce120` from Hugging Face (about 486 MB).
The complete snapshot (`model.bin`, `config.json`, `tokenizer.json`, `vocabulary.txt`, `README.md`,
`.gitattributes`) is stored under `models/faster-whisper-small/`. Each download goes to `.part` and
is renamed only after SHA-256 matches; interrupted downloads are removed. The four inference files
and the two metadata files are all checked again before loading. `local_files_only=True` and a local
directory prevent model downloads during listening, including fallback. Missing or altered files
produce installation guidance; the other installed engine can still take over.

Existing installations using the old Hugging Face cache must click **Complete the voice models**;
the old cache is neither imported nor removed. `COMPANION_STT_MODEL` is no longer used: selecting an
arbitrary model would bypass the pinned inventory. Parakeet's archive adds about 465 MB; remaining
voice models account for roughly 350 MB. The remaining downloads are approximately 148 MB of GGML, two 63 MB Piper voices and two
roughly 40 MB Vosk archives. These are rounded download estimates, not installed sizes.
Verified existing files are reused; missing or altered files are downloaded again on click.
**Verify and repair models** remains available when the installation looks complete, so a corrupted
file can be repaired without automatic network access. It reuses the explicit installer, including
the check of pinned Python packages.

See [model attributions and licenses](model-licenses.md), especially the unresolved English Lessac
voice licensing. That voice is unchanged in this release.

## Echo cancellation (optional)

An optional PipeWire configuration is supplied in [examples/99-alison-echo.conf](../examples/99-alison-echo.conf).
It creates `alison_micro`, subtracting playback from microphone input, so you can interrupt Alison by
speaking. Hardware and volume affect results. From the plugin directory, copy it manually (back up an
existing file with the same name first):

```bash
mkdir -p ~/.config/pipewire/pipewire.conf.d
cp examples/99-alison-echo.conf ~/.config/pipewire/pipewire.conf.d/99-alison-echo.conf
systemctl --user restart pipewire
```

Select **alison_micro** under Settings → Voice. To undo, select the system microphone, remove the copied
file (or restore your previous version), then run `systemctl --user restart pipewire` again.
Restarting PipeWire briefly interrupts audio.
