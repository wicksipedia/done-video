"""Fundamental frequency of a voice clip, by autocorrelation.

Two of the skill's checks need it: whether the clone is tracking the reference
speaker, and whether a line ends on a rising pitch. numpy is already a
dependency, so there is no pitch library here.

Runnable on its own to check a finished file:

    python pitch.py audio/b7_000.wav
"""

import sys
import wave

import numpy as np

# A speaking voice sits inside this range. Anything outside it is a harmonic or
# a subharmonic, and letting the search find one halves or doubles the answer.
FMIN, FMAX = 70.0, 350.0
FRAME, HOP = 0.04, 0.01
# Normalised autocorrelation peak below this is noise or a consonant, not pitch.
VOICED = 0.3


def read_wav(path):
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        sr, channels = w.getframerate(), w.getnchannels()
    x = x.astype(float)
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, sr


def f0_track(x, sr):
    """Times and pitches of every voiced frame. Unvoiced frames are dropped."""
    length, hop = int(FRAME * sr), int(HOP * sr)
    lo, hi = int(sr / FMAX), int(sr / FMIN)
    times, pitches = [], []
    for start in range(0, max(0, len(x) - length), hop):
        frame = x[start:start + length]
        frame = frame - frame.mean()
        energy = (frame ** 2).sum()
        if energy <= 0:
            continue
        correlation = np.correlate(frame, frame, "full")[length - 1:]
        window = correlation[lo:hi]
        if len(window) == 0:
            continue
        lag = lo + int(window.argmax())
        if correlation[lag] / energy < VOICED:
            continue
        times.append((start + length / 2) / sr)
        pitches.append(sr / lag)
    return np.array(times), np.array(pitches)


def median_f0(x, sr):
    _, pitches = f0_track(x, sr)
    return float(np.median(pitches)) if len(pitches) else 0.0


def ending_rise(x, sr, window=0.45):
    """Hz the pitch climbs over the final `window`.

    Negative for a statement, positive for a question. Fitting a line rather
    than comparing two points, because a single frame lands on whatever
    syllable happens to be there.
    """
    times, pitches = f0_track(x, sr)
    if len(pitches) < 4:
        return 0.0
    tail = times >= times[-1] - window
    if tail.sum() < 4:
        return 0.0
    slope = np.polyfit(times[tail], pitches[tail], 1)[0]
    return float(slope * window)


def _self_check():
    sr = 24000
    t = np.linspace(0, 1.0, sr, endpoint=False)

    steady = np.sin(2 * np.pi * 180 * t) * 8000
    found = median_f0(steady, sr)
    assert abs(found - 180) < 5, f"steady 180 Hz read as {found:.1f}"
    assert abs(ending_rise(steady, sr)) < 5, "steady tone should not slope"

    # Phase is the integral of frequency, so a linear sweep needs a cumulative
    # sum rather than freq * t.
    def sweep(f_start, f_end):
        freq = np.linspace(f_start, f_end, sr)
        return np.sin(2 * np.pi * np.cumsum(freq) / sr) * 8000

    up = ending_rise(sweep(150, 260), sr)
    down = ending_rise(sweep(260, 150), sr)
    assert up > 20, f"rising sweep read as {up:+.1f} Hz"
    assert down < -20, f"falling sweep read as {down:+.1f} Hz"
    print(f"self-check passed (steady {found:.0f} Hz, "
          f"up {up:+.0f} Hz, down {down:+.0f} Hz)")


def main(argv):
    if not argv:
        _self_check()
        return 0
    for path in argv:
        x, sr = read_wav(path)
        print(f"{path}  median {median_f0(x, sr):5.0f} Hz  "
              f"ending {ending_rise(x, sr):+5.0f} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
