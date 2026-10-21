# Notes

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
