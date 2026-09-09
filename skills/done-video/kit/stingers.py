"""Generates the two outcome stingers.

Synthesised rather than sampled: a descending run for a failure and an ascending
one for a success are the genre convention, so there is no need to take audio
from an actual game.
"""

import pathlib
import wave

import numpy as np

SR = 44100
OUT = pathlib.Path(__file__).parent / 'clicks'
OUT.mkdir(exist_ok=True)


def tone(freq: float, seconds: float, decay: float = 6.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    # Odd harmonics give the hollow square-ish timbre these cues are made of.
    wave_ = (
        np.sin(2 * np.pi * freq * t)
        + 0.32 * np.sin(2 * np.pi * 3 * freq * t)
        + 0.14 * np.sin(2 * np.pi * 5 * freq * t)
    )
    env = np.exp(-decay * t)
    # Short fade in so each note starts without a click.
    attack = np.minimum(1.0, np.linspace(0, 1, len(t)) * 60)
    return wave_ * env * attack


def sequence(notes, gap: float = 0.0) -> np.ndarray:
    out = np.zeros(0)
    for freq, dur, decay in notes:
        out = np.concatenate([out, tone(freq, dur, decay)])
        if gap:
            out = np.concatenate([out, np.zeros(int(SR * gap))])
    return out


def write(name: str, samples: np.ndarray, peak: float = 0.6) -> None:
    samples = samples / (np.abs(samples).max() or 1) * peak
    stereo = np.repeat((samples * 32767).astype(np.int16)[:, None], 2, axis=1)
    path = OUT / name
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())
    print(f'  {name}  {len(samples)/SR*1000:.0f}ms')


# Falling run, last note held and sagging: the shape of losing a life.
write('lose.wav', sequence([
    (392.00, 0.10, 7), (329.63, 0.10, 7), (261.63, 0.10, 7),
    (196.00, 0.14, 6), (155.56, 0.45, 3.2),
]))

# Rising major arpeggio landing on the octave: the shape of winning.
write('win.wav', sequence([
    (523.25, 0.085, 9), (659.25, 0.085, 9), (783.99, 0.085, 9),
    (1046.50, 0.40, 3.0),
]))
