---
name: done-video
description: Record a narrated before/after demo video of a bug fix by driving the app with Playwright, cloning the presenter's voice locally, and assembling with ffmpeg. Use when asked for a done video, a before and after video, a demo video of a fix, a recording of a bug, a screen recording with narration, or to show the pain then the fix.
---

# Done Video

Produce a narrated screen-capture showing a bug before a fix and the same steps
after it, per the [SSW done video rule](https://www.ssw.com.au/rules/done-video):
show the pain, then show it solved.

## Set up a run

The kit is a starting point to copy and edit, not a library to call. Copy it
into a scratch directory and work there, so the plugin stays clean between runs.

```bash
WORK=$(mktemp -d)/done-video
cp -R "${CLAUDE_PLUGIN_ROOT}/skills/done-video/kit" "$WORK"
cd "$WORK"
```

| File | |
|---|---|
| `beats.json` | Narration lines, captions, per-beat pauses. Rewrite for each video |
| `record.mjs` | Drives the app, captures video, logs a timeline. Rewrite the steps |
| `clone.py` | Renders each line in the presenter's voice, writes `timings.json` |
| `calibrate.py` | Moves the timeline from Node's clock onto the video's |
| `assemble.sh` | Upscales, mixes, concatenates |
| `cards.mjs` | Renders title cards |
| `stingers.py` | Generates the win and lose cues |
| `harness.sh` | Runs the whole thing unattended across two git refs |
| `requirements.txt` | Python dependencies |

## Requirements

```bash
brew install ffmpeg jq                    # ffprobe ships with ffmpeg
python3 -m venv .venv                     # Python 3.10+
./.venv/bin/pip install -r requirements.txt
```

Node 20+ for the two `.mjs` scripts. Both scripts set `PYTHON` if the venv is
somewhere else: `PYTHON=/path/to/python ./assemble.sh`.

**Playwright is borrowed from the app being recorded, not installed here.**
`record.mjs` and `cards.mjs` resolve it through `APP_DIR`, so the target app
needs `@playwright/test` in its own `node_modules` and its browsers installed
(`pnpm exec playwright install chromium`). This keeps the recorder on whatever
Playwright version the app already tests against, and means there is no second
copy of Chromium to keep current.

First `clone.py` run downloads roughly 2 GB: `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`
from Hugging Face, cached under `~/.cache/huggingface`.

Verifying output needs `mlx-whisper` as well. It is not a pipeline dependency —
nothing in `assemble.sh` calls it — so install it only when checking sync.

## Voice setup

**No voice reference ships with this plugin.** A cloned voice is a person's
likeness, so the presenter supplies their own. `clone.py` stops with
instructions if `voice/` is missing, and nothing downstream runs without it.

Two files are needed:

- `voice/ref.wav` — about 10 seconds of the presenter. One speaker, no music,
  no other voices. A stretch of an existing talk or podcast works.
- `voice/ref.txt` — the transcript of **that exact cut**, word for word.

**Ask the presenter for a source clip before doing anything else.** Any file
ffmpeg reads will do: a video of a talk, a voice memo, a screen recording. Then
cut and transcribe it:

```bash
mkdir -p voice
# Cut ~10s from a quiet single-speaker stretch. Adjust -ss until it is clean.
ffmpeg -y -ss 00:01:24 -t 10.5 -i /path/to/source -ac 1 -ar 24000 voice/ref.wav

# Transcribe the cut, never the source: the two must agree word for word.
./.venv/bin/pip install mlx-whisper
./.venv/bin/python -c "
import mlx_whisper
print(mlx_whisper.transcribe('voice/ref.wav',
      path_or_hf_repo='mlx-community/whisper-tiny')['text'].strip())
" > voice/ref.txt
cat voice/ref.txt
```

Read `voice/ref.txt` back and correct it by hand before recording. Whisper drops
filler words and mishears names, and every mismatch pulls the clone off the
reference.

A clip from a stage talk carries a presenting cadence. A quieter stretch reads
warmer.

## Inputs

- A bug with a **deterministic repro** the app can be driven into
- Two git refs: the broken one and the fixed one
- A voice reference, as above
- A page for the intro and outro to rest on, as `PR_URL`. A pull request reads
  well because it names the change without narration having to

## Every video ends with an outro

Two beats, always, after the demo lands:

1. **What was done**, named as the thing rather than the change: "So that is the
   admin panel. Announcements are managed from a browser…". A viewer arriving at
   the end should be able to say what now exists.
2. **The sign-off**, in the presenter's own words. Same wording every video, so
   it reads as a series rather than a one-off. Over a closing card, with the
   outcome badge cleared first — it belongs to the demo, not to the closing
   words.

Hold the card about a second and a half after the last word. Four seconds of
silence reads as the file having failed rather than ended, and `-t` on the
finished mp4 trims it without a re-encode.

## Order matters: narration first

Generate every line **before** recording, measure each, then pace the capture to
those durations. The reverse means re-recording video every time a sentence
changes. Audio and footage stay separate until the final mux, so re-voicing
never costs a re-record.

`clone.py` → `record.mjs` → `calibrate.py` → `assemble.sh`.

## Two clocks, and why sync breaks

Getting narration and sound to land correctly needs both of these. Each was a
real bug, not a precaution.

**Beats are not the sum of their lines.** A video beat runs for
`max(action, narration) + pad`. Concatenating audio back-to-back means beat N
starts at the sum of the *lines* before it, so every action that outruns its
line pushes the audio further ahead. `record.mjs` logs each beat's measured
start and `assemble.sh` places each line at that offset.

**Node's clock is not the video's.** Capture begins after `newPage()` returns,
so raw timestamps put every sound late. `record.mjs` flashes a magenta marker at
a known logged time and `calibrate.py` finds it in the frames. Measured offset
on the reference build: **~75ms, consistent to 3ms** across recordings.

> Flash the marker **at least a second in**. One drawn immediately lands in
> frame 0 whatever the offset is, which bounds the answer instead of measuring
> it. That mistake reported a confident, useless `-0.004s`.

## Pitfalls that cost real time

| Trap | What actually happens | Fix |
|---|---|---|
| A whole segment's audio lands early, last line cut | The clip's capture began *at* the sync marker, so the marker sits in frame 0 — a real measurement when the marker is flashed seconds in, and rejecting it as "bounded" put that segment 2.4s out | Only distrust frame 0 for a marker drawn at `t=0`. Measure across segments: the offset held to 2ms here, so a clip that genuinely cannot measure its own can borrow the median |
| A large image is white for the first second | `page.goto` resolves before a multi-megapixel PNG decodes, and the beat starts under a blank frame | Load it before the beat and `waitForFunction` on `img.complete && naturalWidth > 0` |
| A scrolled page loses its heading immediately | Scrolling from the first frame takes the title off screen while the narration is still naming it | Hold at the top for ~3s, then scroll |
| Trimming trailing silence eats the last line | An amplitude threshold walked back from the end skips a short, quiet closing line and cuts the video before it starts. The sign-off vanished twice this way, once from the synthesiser and once from this | Derive the end from the calibrated timeline's last beat, never from an audio threshold. Once the outro exists the natural tail is ~1s, so trimming is usually unnecessary |
| A line is synthesised half-finished | The audio is valid and nothing downstream notices; the line just ends mid-word. Speaking rate does not find it — short phrases read fast while a long line can lose its ending and still average out | Measure the final 60ms against the line's own peak. A finished utterance decays into silence, a cut one stops at full voice. Retry above about -32 dB (`clone.py`) |
| One audio channel drops out | Narration is mono 24kHz (Qwen), effects are stereo 44.1kHz. `amix` renegotiates layout mid-graph and channels fall out | `aresample=44100,aformat=channel_layouts=stereo` on **every** input before it reaches the mixer |
| Video is letterboxed | Playwright pads the viewport into the video frame; it does not scale it | Set `recordVideo.size` equal to `viewport`. Record 1536x864 and let ffmpeg upscale — that ratio *is* 125% zoom |
| Overlay vanishes at the key moment | A crash demo unmounts React's root, taking any overlay inside it | Append every overlay to `document.body` via `addInitScript`, never into the app |
| Wrong text gets formatted | Slate drops selection keys sent closer than ~150ms apart | Pace word-wise navigation at ~180ms, and poll `getSelection().toString()` rather than asserting once |
| Sentences run together | The synthesiser ignores beat boundaries inside one utterance | Split the beat and use `pauseAfter`. No amount of spacing between *beats* fixes bleed *within* one |
| The sign-off sounds like a question | A 0.6s closing line reads as truncated, not as rising pitch | Lengthen it. Measured F0 slope was already falling — the problem was duration |
| `drawtext` filter not found | Homebrew ffmpeg often ships without libfreetype | Render title cards as HTML in Chromium and loop the PNG |
| A quiet cue jumps to full scale | `loudnorm` across the whole mix rides gain up around a sound sitting in silence | Normalise speech alone, mix effects in afterwards at fixed level, then `alimiter` |
| Recording shows the old behaviour | Only packages served from source pick up a ref change; anything consumed from `dist` needs building | `BUILD_CMD` in the harness |
| Optional dialog breaks the run | A first-run dialog appears once per browser context, and every run is fresh | `Promise.race` the dialog against the content |
| Killed someone's dev server | Another project may hold the usual port | Probe for a free one. Never kill a process you did not start |

## On-screen affordances

Playwright's synthetic input is invisible, so a recording of it looks like
things happening by themselves. All four are `document.body` overlays:

- **Cursor** — eases to each target, pulses on click, parks somewhere sensible
  after. Without it, clicks read as spontaneous.
- **Keycaps** — `⌘ B Bold` while the shortcut fires. A formatting change is a
  few pixels of text and is over before a viewer sees what caused it. Hold
  ~900ms *after* the key so the change lands while they are still looking.
- **Outcome badges** — a cross and a tick in a corner, marking the pain and the
  fix.
- **Captions** — drop them when there is narration. Two channels saying the
  same thing at once is worse than either alone (`CAPTIONS=off`).

## Sound

**Check the licence before using any audio you did not generate.** Assume a
YouTube video with no declared licence is all rights reserved. Prior use inside
a company is not a licence; if the user reaffirms after being told, that is
their call to record and proceed.

Synthesise where the sound is a genre convention rather than a specific work —
a descending run for failure, an ascending major arpeggio for success, both from
odd-harmonic tones (`stingers.py`). Nothing to license, nothing to attribute.
`assemble.sh` builds them on first run, so nothing is carried in the repo.

Clicks: a real mouse click is a ~10ms transient with a pitched body. A 45ms
pink-noise burst sounds like rain on a tin roof, so `assemble.sh` filters and
fades one instead. To supply a recording, drop it at `clicks/click-source.wav`,
trimmed to the transient, with the tail faded and the peak normalised so the mix
level stays predictable.

## Voice cloning, locally

`mlx-audio` (MIT) driving Qwen3-TTS (**Apache 2.0**). Both allow commercial use.

**Check the wrapper's licence separately from the model's.** `darrenoakey/tts`
is CC BY-NC 4.0 and XTTS-v2 is CPML — both unusable for company work.

`ref_text` must match `ref_audio` word for word. Cut the reference, then
transcribe **that exact cut** with whisper. See Voice setup above.

`load_model()` once and loop `generate_audio()` — the CLI reloads per call.

The log prints a default voice name (`af_heart`) even while cloning correctly.
Verify by pitch, not by reading the log.

## Verifying without eyes or ears

An agent cannot watch or listen. Every defect in this build was caught by
measuring, and several were introduced by *assuming* instead.

```bash
# Channel balance — per-channel RMS in windows. Any window >6 dB apart is a bug.
# Video/audio drift — transcribe the finished file and match lines by content.
ffmpeg -i out.mp4 -af volumedetect -f null -            # mean ~-18 dB, peak ~-1.5
ffmpeg -i out.mp4 -vf freezedetect=n=-55dB:d=1.5 -f null -   # dead air
```

**Transcribe the finished file and check the closing words of every line.** Not
the generated wavs — the mp4, after assembly and any trimming, because both
stages have their own ways of losing a line. `mlx-whisper` with
`mlx-community/whisper-tiny` is enough (`whisper-small` is not a real repo).
Match on the last few words of each beat and normalise first: a plain substring
test reports false misses on `organisation`/`organization` and
`hand edited`/`hand-edited`, which costs a round of chasing nothing.

- **Voice actually cloned?** Median F0 within ~10 Hz of the reference. A stock
  voice sits far higher.
- **Rising or falling inflection?** Fit a line to F0 over the final ~450ms.
- **Beat overlap?** Compare each beat's start against the previous beat's start
  plus its audio length.

> **Distrust your own detectors.** Colour-matching a cursor against a page full
> of brand colour produced ±700ms of noise that looked like real desync, and a
> narration-sync check once reported 18s of drift that was entirely an artifact
> of pairing whisper segments by index instead of by content. When a measurement
> disagrees with a clean, repeatable one, suspect the measurement. Say which
> numbers are trustworthy and which are not.

## Running it unattended

```bash
REPO=~/code/my-app \
APP_DIR=~/code/my-app \
DEV_CMD='pnpm dev --port %PORT%' \
PR_URL=https://github.com/owner/repo/pull/123 \
ADMIN_PATH=/ \
BEFORE_REF=main AFTER_REF=fix/my-branch \
OUT_NAME=done-video-123 \
./harness.sh
```

Refuses to start on a dirty tracked tree, an unknown ref, or without `DEV_CMD` —
guessing the dev command records the wrong app. Picks a free port, polls for
readiness, and kills the process tree it spawned rather than matching on names.

`BUILD_CMD` runs after each checkout, for anything the dev server consumes from
`dist` rather than serving from source.

`GENERATED_PATHS` names files the dev server rewrites on boot. They are restored
on exit **and exempt from the dirty-tree guard** — otherwise the harness locks
itself out on its second run. Anything else left modified is reported, never
discarded: a blanket `git checkout -- .` would throw away whatever the user
saved during the five minutes it was running.

**Demonstrating two PRs at once:** if the fix spans branches, merge them into a
throwaway branch and point `AFTER_REF` at it. Say so when handing over — the
video then shows a state that does not exist on `main` yet.

## Limitations

**Apple Silicon only.** The voice cloning runs on MLX, which is Metal-backed
with no CUDA or x86 path. Everything else — recording, calibration, assembly —
is portable; swapping the TTS is what a Linux port would take.

**The capture is the page and nothing else.** Playwright records the viewport,
so there is no browser chrome, no OS UI, and no native dialogs or file pickers.
Anything outside the page has to be drawn or composited (see Open questions).

**Not a general-purpose recorder.** `beats.json` and `record.mjs` encode one
app's DOM and one bug's reproduction steps. Retargeting means rewriting the
selectors and the beats, not passing different arguments. The kit is a worked
example to copy and edit.

**Needs a deterministic repro and two git refs.** A bug that only appears
sometimes, or one with no fixed "before" to check out, does not fit this shape.

**One presenter, one reference clip.** The clone is only as good as `ref.wav`,
and switching presenter means a new reference plus its exact transcript.

**No publishing step.** The pipeline ends at a local MP4.

## Success criteria

- [ ] Under 3 minutes, 1080p, H.264 + AAC
- [ ] Pain shown before the solution, same steps both halves
- [ ] Outro names what was built, then signs off
- [ ] Every beat's visuals match its narration (frame-checked)
- [ ] Channels balanced, audio normalised, no clipped final word
- [ ] Repo back on its original ref, tree clean, nothing saved by the run
- [ ] No dev server left running

## Talking head

SSW's rule wants a face on the intro and outro. Not built yet; researched
August 2026 and parked. Three findings worth keeping.

**Lip sync does not save you a filming session.** LatentSync, MuseTalk and
Wav2Lip all edit mouths in footage you supply — they need video of the
presenter as input. Only SadTalker animates a still photo. So the choice is
not "film something" versus "generate a face", it is what happens to footage
you have to shoot either way.

**Licences, checked at source rather than from summaries:**

| Model | Code | Weights | Usable commercially |
|---|---|---|---|
| MuseTalk | MIT | "any purpose, even commercially" | Yes, cleanest |
| LatentSync | Apache 2.0 | OpenRAIL++ | Yes — see below |
| SadTalker | Apache 2.0 | Apache 2.0 | Lists Wav2Lip in its own stack; trace before relying on it |
| LivePortrait | MIT | MIT, needs InsightFace `buffalo_l` | No |
| Wav2Lip | — | trained on LRS2 | No, research and personal only |

LivePortrait is the trap worth remembering: everyone quotes the MIT licence,
and it cannot run without InsightFace weights that are non-commercial. Same
shape as XTTS-v2. Always resolve the weights separately from the code, and the
dependencies' weights separately again.

LatentSync's weights carry a different licence from its code. OpenRAIL++
permits commercial use subject to Attachment A, and none of its eleven
restrictions touch this use — there is no clause about likenesses, deepfakes,
or disclosing machine-generated content.

**The blocker is macOS, not licensing.** Both viable models are CUDA-first with
no official Apple Silicon support, and claims that MuseTalk "supports Apple
MPS" trace to SEO listicles rather than the repo, whose macOS issue has sat
unanswered since November 2025. `ssrsybz/LatentSync1.5-mac` is a genuine port
with real MPS code and weights pulled from ByteDance's official Hugging Face
repo, but it is a standalone re-upload rather than a fork, pinned to
`torch==2.4.1`, last touched June 2025, and its setup script still runs
`apt install` on the Mac path. Upstream LatentSync has not shipped in over a
year. Renting a GPU (Replicate hosts both) sidesteps all of it for cents per
run, at the cost of sending a likeness to a third party.

> `pubple/LatentSync-Mac` is not a Mac port. It is an untouched snapshot of
> upstream with "-Mac" in the name: zero commits of its own, README unmodified,
> no MPS code. Diff a fork against its parent before believing its name.

A cheaper approximation, if the mouth does not have to match the words: two
short loops, talking and idle, swapped on the narration timings already in the
calibrated timeline. Corner PiP reads fine at ~280px.

## Open questions

- **Browser chrome is not in the capture.** Playwright records the page only.
  Draw the frame — tab, address bar, traffic lights — as a PNG via the
  `cards.mjs` trick and composite: a 1792x72 bar at (64, 0) above the recording
  scaled to 1792x1008 at (64, 72) fills 1080 exactly with no stretch. OS-level
  capture gives real chrome but needs screen-recording permission, catches
  whatever else is on screen, and cannot run headless, which breaks the
  harness. An app on hash routes shows one URL for the whole video with a static
  bar; a live one means logging URL changes in `record.mjs`.
- Narration that sounds conversational rather than read. A fully generated
  video trades that for repeatability. Decide per audience.
- Roughly half the runtime is a static frame even after trimming. Some of that
  is unavoidable in a narrated screencast; the levers are shortening lines and
  the card durations, not speeding up the typing, which already reads fast.
- **Publishing is not covered.** Uploading unlisted to YouTube and linking the
  PR needs `porjo/youtubeuploader`, a Google Cloud OAuth client, and a one-time
  browser consent. Untested here, so not documented as a step.
