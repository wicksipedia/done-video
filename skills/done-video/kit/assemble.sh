#!/usr/bin/env bash
# Joins the recorded clips with the narration into one 1080p MP4.
set -euo pipefail

cd "$(dirname "$0")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

# A short filtered noise burst. Generated rather than sourced so there is no
# sample to license, and quiet enough to sit under the narration.
# Prefer a supplied click recording; fall back to a synthesised one so this
# script still works without any audio asset alongside it.
if [ -f clicks/click-source.wav ]; then
  cp clicks/click-source.wav "$work/click.wav"
else
  ffmpeg -v error -y -f lavfi -i "anoisesrc=d=0.045:c=pink:a=0.9" \
    -af "highpass=f=900,lowpass=f=8000,afade=t=out:st=0.004:d=0.041,volume=0.8" \
    -ar 44100 -ac 2 "$work/click.wav"
fi

# The outcome cues are synthesised rather than sampled, so they are built here
# instead of being carried in the repo.
if [ ! -f clicks/win.wav ] || [ ! -f clicks/lose.wav ]; then
  "${PYTHON:-./.venv/bin/python}" stingers.py
fi

secs_to_ms() { awk -v s="$1" 'BEGIN { printf "%d", s * 1000 }'; }

# Recorded timings are on Node's clock; this moves them onto the video's.
"${PYTHON:-./.venv/bin/python}" calibrate.py intro before after

# Each narration line is placed at the offset the recorder measured for its
# beat, not at the sum of the lines before it. An action that runs longer than
# its line (typing, waiting for the crash) stretches the video beat, and
# concatenating would let the audio drift a little further ahead on each one.
build_segment() {
  local name=$1
  local timeline="clips/$name.timeline.calibrated.json"
  [ -f "$timeline" ] || { echo "missing $timeline — run calibrate.py" >&2; exit 1; }

  # Every clip opens on a blank page while the sync marker is flashed and the
  # app loads. That is dead air with nothing to hear or see, so the video starts
  # shortly before the first line instead and every timing shifts with it.
  local trim
  trim=$(jq -r '[(.beats[0].start - 0.4), 0] | max' "$timeline")

  local -a inputs=(-ss "$trim" -i "clips/$name.webm")
  local -a filters=()
  local speech="" clicks=""
  local nspeech=0 nclicks=0
  local idx=1

  while read -r id start; do
    local ms; ms=$(secs_to_ms "$(awk -v s="$start" -v t="$trim" 'BEGIN{print s - t}')")
    inputs+=(-i "audio/${id}_000.wav")
    filters+=("[$idx:a]aresample=44100,aformat=channel_layouts=stereo,adelay=${ms}|${ms}[n$idx]")
    speech+="[n$idx]"
    nspeech=$((nspeech + 1)); idx=$((idx + 1))
  done < <(jq -r '.beats[] | "\(.id) \(.start)"' "$timeline")

  while read -r at; do
    local ms; ms=$(secs_to_ms "$(awk -v s="$at" -v t="$trim" 'BEGIN{print s - t}')")
    inputs+=(-i "$work/click.wav")
    filters+=("[$idx:a]aresample=44100,aformat=channel_layouts=stereo,adelay=${ms}|${ms}[n$idx]")
    clicks+="[n$idx]"
    nclicks=$((nclicks + 1)); idx=$((idx + 1))
  done < <(jq -r '.clicks[]' "$timeline")

  # Outcome stingers ride with the narration rather than the clicks: they are
  # meant to be heard, not felt.
  while read -r kind at; do
    local ms; ms=$(secs_to_ms "$(awk -v s="$at" -v t="$trim" 'BEGIN{print s - t}')")
    inputs+=(-i "clicks/$( [ "$kind" = fail ] && echo lose || echo win ).wav")
    filters+=("[$idx:a]aresample=44100,aformat=channel_layouts=stereo,adelay=${ms}|${ms},volume=0.5[n$idx]")
    speech+="[n$idx]"
    nspeech=$((nspeech + 1)); idx=$((idx + 1))
  done < <(jq -r '.stingers // [] | .[] | "\(.kind) \(.at)"' "$timeline")

  local graph
  graph="[0:v]scale=1920:1080:flags=lanczos,fps=30[v];"
  graph+="$(IFS=';'; echo "${filters[*]}");"
  # Normalise the narration on its own. Running loudnorm across the whole mix
  # rides the gain up around a click sitting in silence, which is how a "subtle"
  # click ends up near full scale.
  graph+="${speech}amix=inputs=${nspeech}:normalize=0:dropout_transition=0,"
  graph+="loudnorm=I=-16:TP=-1.5:LRA=11[speech];"
  if [ "$nclicks" -gt 0 ]; then
    graph+="${clicks}amix=inputs=${nclicks}:normalize=0:dropout_transition=0,"
    # ~18 dB under the narration peaks: audible on laptop speakers without
    # competing with the voice.
    # Peaks near the narration's average level: clearly there, never on top of
    # the voice. Raise toward 0.5 for a firmer click, drop to 0.12 to soften.
    graph+="volume=0.25[clicks];"
    # A click landing on a loud syllable summed close to full scale, so the mix
    # is limited rather than trusted.
    graph+="[speech][clicks]amix=inputs=2:normalize=0:dropout_transition=0,"
    graph+="alimiter=limit=0.94:level=disabled,apad[a]"
  else
    graph+="[speech]apad[a]"
  fi

  ffmpeg -v error -y "${inputs[@]}" \
    -filter_complex "$graph" -map '[v]' -map '[a]' -shortest \
    -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
    -c:a aac -b:a 160k "$work/$name.mp4"
}

build_segment intro
build_segment before
build_segment after

# Title cards between the halves so the cut reads as deliberate. Rendered by
# cards.mjs, because this ffmpeg has no libfreetype and so no drawtext.
node cards.mjs >/dev/null

card() {
  local out=$1 png=$2
  ffmpeg -v error -y -loop 1 -t 2.2 -i "$png" \
    -f lavfi -t 2.2 -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
    -vf "fps=30,format=yuv420p" \
    -c:v libx264 -preset slow -crf 20 -c:a aac -b:a 160k "$out"
}

card "$work/card-before.mp4" cards/card-before.png
card "$work/card-after.mp4" cards/card-after.png

for part in intro card-before before card-after after; do
  printf "file '%s'\n" "$work/$part.mp4" >>"$work/parts.txt"
done

out="${OUT_NAME:-done-video}.mp4"
ffmpeg -v error -y -f concat -safe 0 -i "$work/parts.txt" -c copy "$out"
echo "wrote $PWD/$out"
ffprobe -v error -show_entries format=duration:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 "$out"
