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

## Interface translation versus complete voice support

Only French and English currently have a complete set of built-in voice resources and command
grammars. Adding `lang/de.json`, for example, translates the interface; it does not add German
Piper/Vosk models or qualified approval words.

Transcription keeps the selected language code. For a language without a built-in vocabulary hint
or hallucination filter, both stay empty; no French or English hint/filter is substituted.
Parakeet v3 detects its 25 languages automatically: bg, hr, cs, da, nl, en, et, fi, fr, de, el, hu,
it, lv, lt, mt, pl, pt, ro, sk, sl, es, sv, ru and uk. See the
[upstream model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3).
For any other code, only local Whisper is tried, regardless of the engine preference; an unavailable
or unsupported Whisper language is reported as an error, never replaced by Parakeet. This does not
claim that arbitrary codes are recognized. The generated Voxtype fallback configuration likewise
keeps the requested language with an empty hint if no hint exists. An explicitly compatible system
Voxtype configuration is still reused as before.

For a translated-only language, Piper speech and the Vosk wake-word model keep the existing English
fallback. Voice commands, stop words and approval/refusal words also keep their existing English
grammars. Settings → Voice displays that limitation, and the journal reports it once per language
per backend process, including after a settings change. A user-selected custom wake phrase remains
a custom phrase; the fallback Vosk model must still know its words. A previous language’s default
wake phrase follows the English fallback when the new translation supplies none. No new approval word is inferred
from a translation: `approve`, `go ahead`, `allow it` remain the English approval vocabulary.
The existing clickable approval cards stay available.

A **complete language** needs all of the following, separately integrated and tested:

- interface and engine translations, including missing-resource/error messages;
- a licensed, pinned Piper voice and a Vosk model with verified downloads;
- a wake phrase supported by that Vosk model;
- command and stop grammars, and conservatively qualified approval/refusal grammars;
- transcription support in the selected engine, plus listening, false-activation, interruption,
  negation and approval tests with speakers of that language.

No additional models or third-language grammars are shipped by 0.17.5. An interface translation
alone does not qualify voice approval in that language or change anyone's permissions.

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
