# Voice

← [Back to README](../README.md)

## Installing the local voice

Choose **Settings → Voice → Install the voice** (or the button in the first-run wizard). Only that click
creates the dedicated Python environment at `~/.local/share/omarchy-companion/.venv` and downloads
packages and models (about 1.5 GB). Piper, Vosk, faster-whisper and sherpa-onnx versions are pinned.
Downloaded models are **verified by SHA-256**; not every download host provides immutable commit URLs.

Speech, wake detection and transcription then run locally.

## Wake word

French and English Vosk models are included in the downloader; the default wake phrase follows the
selected language (*“Hey Alison”* in English, *“Salut Alison”* in French). Custom wake phrases must use
words the selected Vosk model can recognize.

## Transcription

Parakeet (fast) is the default; Whisper takes over on its own if Parakeet is missing. *Install the voice*
downloads both.

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
