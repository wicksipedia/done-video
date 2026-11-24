"""Renders every narration beat in the presenter's cloned voice.

The reference clip and its transcript must match word for word, otherwise the
clone drifts. Supply both in $DONE_VIDEO_HOME/voice/ (default ~/.done-video):
a ~10s single-speaker clip as ref.wav, and the transcript of that exact cut as
ref.txt. A voice/ folder next to this script still works.
"""

import json
import os
import pathlib
import numpy as np

from mlx_audio.tts.generate import generate_audio, load_model

import pitch

HERE = pathlib.Path(__file__).parent
AUDIO = HERE / "audio"
AUDIO.mkdir(exist_ok=True)

MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
# The presenter records the reference once, and every copy of the kit reads it from the shared home.
SHARED_VOICE = pathlib.Path(os.environ.get("DONE_VIDEO_HOME", pathlib.Path.home() / ".done-video")) / "voice"
VOICE = SHARED_VOICE if (SHARED_VOICE / "ref.wav").exists() else HERE / "voice"
REF_AUDIO = VOICE / "ref.wav"
REF_TEXT_FILE = VOICE / "ref.txt"

if not REF_AUDIO.exists() or not REF_TEXT_FILE.exists():
    raise SystemExit(
        f"No voice reference found in {SHARED_VOICE}.\n"
        "Supply two files before recording:\n"
        f"  {SHARED_VOICE}/ref.wav  a ~10s clip of the presenter, one speaker, no music\n"
        f"  {SHARED_VOICE}/ref.txt  the transcript of that exact cut, word for word\n"
        "See the skill's Voice setup section for how to cut and transcribe one."
    )

REF_TEXT = REF_TEXT_FILE.read_text().strip()

beats = json.loads((HERE / "beats.json").read_text())
model = load_model(MODEL)

# The synthesiser sometimes stops early. The audio is valid and sounds fine, so
# nothing downstream notices; the line simply ends mid-word.
#
# Speaking rate does not find it. A truncated line does read fast, but so does
# any short phrase, and a long line can lose its last few words while still
# averaging out normal. What separates them is how the audio ends: a finished
# utterance decays into silence, and a cut one stops at full voice. Measuring
# the last 60ms against the line's own peak says which happened.
MAX_TAIL_DB = -32.0

# It also sometimes ends a statement on a rising pitch, which reads as a
# question. Nothing about the text causes it and re-rendering the same line
# usually fixes it, so it is measured and retried like a cut ending.
#
# Tune this on the first run: every line prints its rise, so the number to
# reject by is visible in the output rather than guessed at here.
MAX_RISE_HZ = 12.0

ATTEMPTS = 4


def tail_db(x, sr):
    """How loud the final 60ms is against the line's own peak."""
    peak = np.abs(x).max() or 1.0
    tail = x[-int(0.06 * sr):]
    return 20 * np.log10((np.sqrt((tail ** 2).mean()) + 1e-9) / peak)


def render(beat, prefix):
    generate_audio(
        text=beat["text"],
        model=model,
        ref_audio=str(REF_AUDIO),
        ref_text=REF_TEXT,
        file_prefix=prefix,
        audio_format="wav",
        verbose=False,
    )
    path = pathlib.Path(f"{prefix}_000.wav")
    x, sr = pitch.read_wav(path)
    return {
        "path": path,
        "seconds": len(x) / sr,
        "tail": tail_db(x, sr),
        "rise": pitch.ending_rise(x, sr),
        "median": pitch.median_f0(x, sr),
    }


def score(take):
    """Lower is better. A cut line is worse than a merely rising one."""
    return (take["tail"] > MAX_TAIL_DB, max(0.0, take["rise"] - MAX_RISE_HZ))


ref_x, ref_sr = pitch.read_wav(REF_AUDIO)
reference_f0 = pitch.median_f0(ref_x, ref_sr)

timings = []
for beat in beats:
    prefix = str(AUDIO / beat["id"])
    best = None
    for attempt in range(1, ATTEMPTS + 1):
        take = render(beat, prefix)
        if best is None or score(take) < score(best):
            best = {**take, "data": take["path"].read_bytes()}
        if score(take) == (False, 0.0):
            break
        if attempt < ATTEMPTS:
            print(f"     {beat['id']} tail {take['tail']:.1f} dB, "
                  f"rise {take['rise']:+.0f} Hz — retry {attempt}")

    # Keep the attempt that scored best, which is not always the last one.
    best["path"].write_bytes(best["data"])

    flags = []
    if best["tail"] > MAX_TAIL_DB:
        flags.append("STILL CUT")
    if best["rise"] > MAX_RISE_HZ:
        flags.append("STILL RISING")
    flag = "  " + ", ".join(flags) if flags else ""

    print(f"{beat['id']:4s} {best['seconds']:5.2f}s  tail {best['tail']:6.1f} dB  "
          f"rise {best['rise']:+5.0f} Hz  {beat['caption']}{flag}")
    timings.append({**beat, "file": str(best["path"]), "seconds": best["seconds"],
                    "median_f0": best["median"]})

(HERE / "timings.json").write_text(f"{json.dumps(timings, indent=2)}\n")
print(f"\ntotal speech {sum(t['seconds'] for t in timings):.1f}s")

# The log prints a stock voice name even while cloning correctly, so pitch is
# the only honest way to tell whether the reference was used.
spoken_f0 = float(np.median([t["median_f0"] for t in timings]))
print(f"median F0 {spoken_f0:.0f} Hz, reference {reference_f0:.0f} Hz")
if abs(spoken_f0 - reference_f0) > 15:
    print("  the clone is not tracking the reference — check that ref.txt "
          f"matches ref.wav word for word in {VOICE}")
