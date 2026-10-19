# Voice model attributions and license study

← [Back to README](../README.md) · [Voice installation](voice.md)

Checked on 2026-10-19. Model downloads happen only on the explicit voice-install click.
The plugin's GPL-3.0-or-later license does not replace model, corpus or dependency licenses.
Checksums establish byte identity, not licensing permission. No voice was replaced in 0.17.4.

## Downloaded inventory

| Download in `download_models.py` | Provenance and attribution | What is verified / unresolved |
|---|---|---|
| `ggml-base.bin` (Voxtype fallback) | OpenAI Whisper, converted by the whisper.cpp project; [MIT upstream license](https://github.com/openai/whisper/blob/main/LICENSE); [fixed conversion snapshot](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1) | Fixed snapshot and stored SHA-256. Conversion-specific notices at that snapshot have not been independently archived here. This is not faster-whisper's model. |
| `faster-whisper-small/` (six files) | OpenAI Whisper small, CTranslate2 conversion by SYSTRAN; [MIT model card at the downloaded commit](https://huggingface.co/Systran/faster-whisper-small/blob/536b0662742c02347bc0e980a01041f333bce120/README.md) | Complete commit inventory and SHA-256 for every file. `README.md` and `.gitattributes` are included alongside the four inference files. |
| `fr_FR-siwis-medium.onnx` and its JSON | Piper / Michael Hansen; [SIWIS card](https://huggingface.co/rhasspy/piper-voices/blob/main/fr/fr_FR/siwis/medium/MODEL_CARD) names the [SIWIS corpus](https://datashare.is.ed.ac.uk/handle/10283/2353), CC-BY-4.0 | The card also declares fine-tuning from Lessac medium: corpus attribution alone does not resolve the base-model question. Same unresolved lineage concern as below. |
| `en_US-lessac-medium.onnx` and its JSON | Piper / Michael Hansen; [Lessac card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD), trained from scratch on Lessac Blizzard 2013 | The card links a research/non-commercial corpus license, not CC0 or CC-BY. Unrestricted distribution/use of derived weights is **not established** by this study. |
| `vosk-fr.zip` | Alpha Cephei, `vosk-model-small-fr-0.22`; [official catalogue](https://alphacephei.com/vosk/models) | Catalogue lists Apache-2.0. Fixed version URL plus stored SHA-256; no immutable source commit supplied by that download host. |
| `vosk-en.zip` | Alpha Cephei, `vosk-model-small-en-us-0.15`; [official catalogue](https://alphacephei.com/vosk/models) | Catalogue lists Apache-2.0. Same version-URL limitation. |
| Parakeet v3 int8 archive, then `encoder.int8.onnx`, `decoder.int8.onnx`, `joiner.int8.onnx`, `tokens.txt` | NVIDIA Parakeet TDT 0.6B v3, sherpa-onnx conversion by k2-fsa; [NVIDIA card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), [conversion documentation](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/nemo-transducer-models.html#sherpa-onnx-nemo-parakeet-tdt-0-6b-v3-int8-multi-lingual) | NVIDIA specifies CC-BY-4.0. Attribute NVIDIA and identify the ONNX/int8 conversion. The fixed release URL is not an immutable Git commit; archive and four extracted files are SHA-256 checked. Only those four files are extracted; this document links the source notices. |

Both Piper voices use the fixed revision `1162a9173d0ce503555aed757976b7a9912eae4c`
and a stored SHA-256 for both ONNX and JSON. Attempts to read the MODEL_CARD files at that exact
revision through public web navigation failed; the cards above were read on `main`. Do not claim
those particular historical cards or the full rights chain have been certified. Their links remain
available at the [pinned tree](https://huggingface.co/rhasspy/piper-voices/tree/1162a9173d0ce503555aed757976b7a9912eae4c).

The inventory covers the voice installer, not optional robot/vision downloads or Python wheels.
Piper, Vosk, faster-whisper and sherpa-onnx have their own software licenses; pinned top-level
package versions are not a complete hash-locked dependency chain.

## Lessac: unchanged, license question remains open

The [Lessac corpus terms](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html)
restrict the supplied recordings to research and exclude commercial purposes. Those terms concern
the corpus; this study does not decide their legal effect on trained weights. The global `mit`
badge on the Piper voice repository cannot settle that question. A [public upstream discussion](https://huggingface.co/rhasspy/piper-voices/discussions/105) contains the maintainer’s statement that Piper does not grant rights to the Lessac recordings and points users to a separate redistribution agreement. Clarification from the rights
holder or a different documented lineage is needed before claiming unrestricted use. SIWIS also
inherits an explicitly declared Lessac fine-tuning lineage.

## Three English medium candidates — study only

All three are single-speaker `en_US`, 22,050 Hz Piper voices. None was downloaded, listened to,
selected or integrated. The model cards explicitly declare training from scratch, avoiding an
undocumented assumption that a free new corpus erases Lessac provenance.

| Candidate | Corpus and complete declared training lineage | Recommendation |
|---|---|---|
| **`en_US-ljspeech-medium`** | [Piper card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD): LJ Speech, trained from scratch for 1,000 epochs. [LJ Speech publisher](https://keithito.com/LJ-Speech-Dataset/) identifies recordings, texts and annotations as public domain in the US. | First female candidate to evaluate; strongest explicit corpus description among these options. |
| **`en_US-kristin-medium`** | [Piper card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/kristin/medium/MODEL_CARD): LibriVox, trained from scratch for 2,000 epochs, about 11.5 hours; no Lessac base declared. | Second female candidate; inspect the exact source-recording list before worldwide distribution. |
| **`en_US-norman-medium`** | [Piper card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/norman/medium/MODEL_CARD): LibriVox, trained from scratch for 1,200 epochs, about 15.5 hours; no Lessac base declared. | Male alternative with the same corpus-territory check. |

These public-domain corpus declarations permit unrestricted reuse in the stated US context;
[LibriVox explicitly allows commercial reuse](https://librivox.org/pages/public-domain/) and also
warns that copyright status may differ elsewhere. This is not a claim of universal CC0 status.
For all three, the voice repository advertises MIT, while the individual cards describe corpus
rights rather than providing a separate exhaustive grant for the weights. Consequently they are
**documented candidates**, not a completed worldwide legal clearance. The linked trainer site
was unavailable during this check. Do not substitute `sam` merely because its new corpus has a free license: its card still declares
a Lessac base; `hfc_female` additionally has non-commercial terms. Upstream reports retraining
`libritts_r` from scratch in the discussion above, while its indexed card still declares Lessac.
A replacement would require matching the new weights and revision to the clarified provenance,
not assuming that an older packaged model was also retrained.

Lugio chooses whether to replace the English voice after listening tests, checking the exact
revision's notices and resolving any territorial/weight-license ambiguity. Integration would need
a newly fixed revision, both SHA-256 hashes, updated attribution and a separate approved change.
