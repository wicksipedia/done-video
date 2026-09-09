"""Renders every narration beat in the presenter's cloned voice.

The reference clip and its transcript must match word for word, otherwise the
clone drifts. Supply both in voice/: a ~10s single-speaker clip as ref.wav, and
the transcript of that exact cut as ref.txt.
"""

import json
import pathlib
import wave

import numpy as np

from mlx_audio.tts.generate import generate_audio, load_model

HERE = pathlib.Path(__file__).parent
AUDIO = HERE / "audio"
AUDIO.mkdir(exist_ok=True)

MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
VOICE = HERE / "voice"
REF_AUDIO = VOICE / "ref.wav"
REF_TEXT_FILE = VOICE / "ref.txt"

if not REF_AUDIO.exists() or not REF_TEXT_FILE.exists():
    raise SystemExit(
        f"No voice reference found in {VOICE}.\n"
        "Supply two files before recording:\n"
        "  voice/ref.wav  a ~10s clip of the presenter, one speaker, no music\n"
        "  voice/ref.txt  the transcript of that exact cut, word for word\n"
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
# averaging out normal — which is exactly how the epic line passed while ending
# mid-sentence. What separates them is how the audio ends: a finished utterance
# decays into silence, and a cut one stops at full voice. Measuring the last
# 60ms against the line's own peak says which happened, whatever its length.
MAX_TAIL_DB = -32.0
ATTEMPTS = 4


def tail_db(path):
    """How loud the final 60ms is against the line's own peak."""
    with wave.open(str(path)) as w:
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        sr = w.getframerate()
    x = frames.astype(float)
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
    with wave.open(str(path)) as w:
        seconds = w.getnframes() / w.getframerate()
    return path, seconds, tail_db(path)


timings = []
for beat in beats:
    prefix = str(AUDIO / beat["id"])
    path, seconds, tail = render(beat, prefix)

    # Keep the attempt that ended most quietly: the one that got furthest.
    for attempt in range(2, ATTEMPTS + 1):
        if tail <= MAX_TAIL_DB:
            break
        best, best_seconds, best_tail = path.read_bytes(), seconds, tail
        print(f"     {beat['id']} ends at {tail:.1f} dB, retry {attempt - 1}")
        path, seconds, tail = render(beat, prefix)
        if best_tail < tail:
            path.write_bytes(best)
            seconds, tail = best_seconds, best_tail

    flag = "  STILL CUT" if tail > MAX_TAIL_DB else ""
    print(f"{beat['id']:4s} {seconds:5.2f}s  tail {tail:6.1f} dB  "
          f"{beat['caption']}{flag}")
    timings.append({**beat, "file": str(path), "seconds": seconds})

(HERE / "timings.json").write_text(f"{json.dumps(timings, indent=2)}\n")
print(f"\ntotal speech {sum(t['seconds'] for t in timings):.1f}s")
