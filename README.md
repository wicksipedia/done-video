# done-video

A Claude Code plugin that records a narrated before/after demo video of a bug
fix. Playwright drives the app on each of two git refs, a locally-run voice
clone reads the narration, and ffmpeg assembles the result into a 1080p MP4.

It follows the [SSW done video rule](https://www.ssw.com.au/rules/done-video):
show the pain, then show it solved.

## Install

```
/plugin marketplace add wicksipedia/done-video
/plugin install done-video
```

Then ask for a done video of a fix, and the skill takes it from there.

## What it does

1. Reads the narration script and renders every line in the presenter's voice.
2. Checks out the broken ref, starts the dev server, and drives the app through
   the reproduction steps while recording.
3. Checks out the fixed ref and repeats the identical steps.
4. Measures the offset between Node's clock and the video's, places each line at
   the beat it belongs to, mixes, and concatenates with title cards.

The capture carries a drawn cursor, keycaps for shortcuts, and outcome badges,
because Playwright's synthetic input is otherwise invisible.

## Requirements

- **Apple Silicon.** The voice cloning runs on MLX, which is Metal-backed. The
  rest of the pipeline is portable; a Linux port means swapping the TTS.
- `ffmpeg` and `jq` (`brew install ffmpeg jq`)
- Python 3.10+ and Node 20+
- The app being recorded must already depend on `@playwright/test`, with its
  browsers installed. The recorder borrows Playwright from the app rather than
  shipping a second copy of Chromium.
- A deterministic reproduction of the bug, and two git refs to show it across.

The first run downloads roughly 2 GB of model weights from Hugging Face.

## Your voice is not included

No voice reference ships with this plugin, and it will not run without one. A
cloned voice is a person's likeness, so the presenter supplies their own: about
ten seconds of clean single-speaker audio, plus a word-for-word transcript of
that exact cut. The skill walks through cutting and transcribing it, and the
pipeline stops with instructions if it is missing.

Reference audio lives in a gitignored directory and is never committed.

## Licence

MIT. See [LICENSE](LICENSE).

The pipeline uses [mlx-audio](https://github.com/Blaizzy/mlx-audio) (MIT) with
Qwen3-TTS (Apache 2.0). Both permit commercial use. The outcome cues are
synthesised at build time rather than sampled, so there is no third-party audio
in the repository.
