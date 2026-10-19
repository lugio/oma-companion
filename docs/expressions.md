# Expressions

← [Back to README](../README.md)

Alison has a face. It is drawn live in the panel header (and, smaller, in the bar), in the colours of the
active Omarchy theme, and it always tells the truth about what she is doing: the microphone ring only
shows when she is really listening, her mouth follows the **real volume** of her voice.

## Alive

<table>
  <tr>
    <td align="center"><img src="assets/expressions/idle.gif" width="120" alt="Idle" /><br/><b>Idle</b><br/><sub>breathes, blinks, smiles</sub></td>
    <td align="center"><img src="assets/expressions/listening.gif" width="120" alt="Listening" /><br/><b>Listening</b><br/><sub>a crown of bars follows your voice</sub></td>
    <td align="center"><img src="assets/expressions/speaking.gif" width="120" alt="Speaking" /><br/><b>Speaking</b><br/><sub>her mouth follows her real voice</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="assets/expressions/thinking.gif" width="120" alt="Thinking" /><br/><b>Thinking</b><br/><sub>a spinning arc, eyes looking up</sub></td>
    <td align="center"><img src="assets/expressions/waiting.gif" width="120" alt="Waiting for approval" /><br/><b>Waiting for you</b><br/><sub>eyebrows raised, the ring pulses until you answer the card</sub></td>
    <td align="center"><img src="assets/expressions/ignored.gif" width="120" alt="Not for her" /><br/><b>Not for her</b><br/><sub>a little shake of the head</sub></td>
  </tr>
</table>

## Moods

| | Mood | When |
|:-:|---|---|
| <img src="assets/expressions/idle.png" width="56" alt="" /> | **Idle** | at rest |
| <img src="assets/expressions/listening.png" width="56" alt="" /> | **Listening** | the microphone is open; the bars follow your voice |
| <img src="assets/expressions/thinking.png" width="56" alt="" /> | **Thinking** | transcribing or waiting for the agent |
| <img src="assets/expressions/speaking.png" width="56" alt="" /> | **Speaking** | reading her answer aloud |
| <img src="assets/expressions/waiting.png" width="56" alt="" /> | **Waiting** | an approval card is open |
| <img src="assets/expressions/acting.png" width="56" alt="" /> | **Focused** | an approved action is running |
| <img src="assets/expressions/ignored.png" width="56" alt="" /> | **Not for her** | she heard a sentence that was not addressed to her |
| <img src="assets/expressions/muted.png" width="56" alt="" /> | **Microphone off** | hands-free conversation, microphone cut: eyes half closed, dotted ring |
| <img src="assets/expressions/error.png" width="56" alt="" /> | **Worried** | something failed; the ring takes the theme's urgent colour |

## What she is doing

While the agent works, her face shows *what* it is doing, derived from the tools it uses:

| | Activity | Tool |
|:-:|---|---|
| <img src="assets/expressions/search.png" width="56" alt="" /> | **Searching** — eyes scanning, a dot runs on the ring | web search |
| <img src="assets/expressions/read.png" width="56" alt="" /> | **Reading** — lines of text scroll by | reading a page or a file |
| <img src="assets/expressions/write.png" width="56" alt="" /> | **Writing** — a blinking cursor, the ring fills | editing a text |
| <img src="assets/expressions/code.png" width="56" alt="" /> | **Coding** — braces, the ring fills | editing code |
| <img src="assets/expressions/run.png" width="56" alt="" /> | **Running** — the `>` prompt and its cursor | running a command |
| <img src="assets/expressions/mail.png" width="56" alt="" /> | **Mail** — an envelope | reading mail |
| <img src="assets/expressions/dream.png" width="56" alt="" /> | **Dreaming** — eyes closed, rising “z” | tidying her memory while the machine is idle |

Everything is drawn with one `Canvas` (`Avatar.qml`) from the theme's colours, so every Omarchy theme —
light, dark, square or round — gives her its own look. The animation clock only runs while she is visible.
