"""Converts a recording's timings from Node's clock into the video's own.

record.mjs timestamps everything with Date.now(), but Playwright starts writing
frames some time after newPage() returns. Left uncorrected every narration line
and every click lands late by that amount. The recorder flashes a magenta marker
at a known logged time; finding it in the frames gives the difference exactly.
"""

import json
import pathlib
import subprocess
import sys

import numpy as np

W, H, FPS = 256, 144, 30
# The click file's transient is not at its first sample, so the file has to
# start slightly early for the peak itself to land on the colour change.
PEAK_OFFSET = 0.0098


def marker_time(clip: str) -> float | None:
    raw = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', clip, '-t', '6',
         '-vf', f'scale={W}:{H},fps={FPS}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        capture_output=True,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W, 3).astype(int)
    # Magenta appears nowhere in the admin, so an exact-ish match is enough.
    corner = frames[:, -8:, :8, :]
    r, g, b = corner[..., 0], corner[..., 1], corner[..., 2]
    hits = ((r > 180) & (g < 90) & (b > 180)).reshape(len(frames), -1).sum(axis=1)
    found = np.where(hits > 2)[0]
    if len(found) == 0:
        return None
    # Frame 0 is a real measurement here, not a bounded one: the marker is drawn
    # seconds in, so seeing it in the first frame says capture began about when
    # it appeared. That is only uninformative for a marker drawn at t=0, which is
    # why this one is not.
    return int(found[0]) / FPS


def main() -> int:
    segments = sys.argv[1:]

    # Measure every segment first. A clip whose capture began at the marker can
    # only bound its own offset, and the offset is a property of the recorder
    # rather than of the clip: measured across segments it holds to a couple of
    # milliseconds. So a segment that cannot measure its own borrows the median
    # of the ones that could, rather than silently assuming zero.
    measured = {}
    for segment in segments:
        timeline = json.loads(
            (pathlib.Path('clips') / f'{segment}.timeline.json').read_text()
        )
        seen = marker_time(f'clips/{segment}.webm')
        if seen is not None and 'sync' in timeline:
            measured[segment] = seen - timeline['sync']
            print(f'{segment}: marker logged {timeline["sync"]:.3f}s, '
                  f'seen {seen:.3f}s, offset {measured[segment]:+.3f}s')

    if not measured:
        print('no segment could measure an offset; leaving every timing as recorded')
    fallback = float(np.median(list(measured.values()))) if measured else 0.0

    for segment in segments:
        path = pathlib.Path('clips') / f'{segment}.timeline.json'
        timeline = json.loads(path.read_text())
        if segment in measured:
            offset = measured[segment]
        else:
            offset = fallback
            print(f'{segment}: marker not measurable, '
                  f'using {offset:+.3f}s measured from the other segments')

        timeline['beats'] = [
            {**b, 'start': max(0.0, b['start'] + offset), 'end': b['end'] + offset}
            for b in timeline['beats']
        ]
        timeline['clicks'] = [
            max(0.0, c + offset - PEAK_OFFSET) for c in timeline['clicks']
        ]
        timeline['stingers'] = [
            {**s, 'at': max(0.0, s['at'] + offset)}
            for s in timeline.get('stingers', [])
        ]
        timeline['offset'] = offset
        out = path.with_suffix('.calibrated.json')
        out.write_text(f'{json.dumps(timeline, indent=2)}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
