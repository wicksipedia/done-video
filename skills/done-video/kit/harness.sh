#!/usr/bin/env bash
# Records both halves of a done video unattended: narration, capture on each git
# ref, and assembly. Restores the starting ref even when it fails.
#
#   REPO=~/code/my-app \
#   APP_DIR=~/code/my-app \
#   DEV_CMD='pnpm dev --port %PORT%' \
#   PR_URL=https://github.com/owner/repo/pull/123 \
#   AFTER_REF=fix/my-branch ./harness.sh
#
# DEV_CMD is required rather than defaulted: guessing it would silently run the
# wrong server and record a video of the wrong thing. %PORT% is substituted.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO:?set REPO to the git repository root}"
APP_DIR="${APP_DIR:?set APP_DIR to the directory whose dev script serves the app}"
BEFORE_REF="${BEFORE_REF:-main}"
AFTER_REF="${AFTER_REF:?set AFTER_REF to the branch containing the fix}"
DEV_CMD="${DEV_CMD:?set DEV_CMD to the dev server command, using %PORT% for the port}"
PR_URL="${PR_URL:?set PR_URL to the page the intro and outro show}"
# Path the readiness poll requests, and the page record.mjs opens on.
ADMIN_PATH="${ADMIN_PATH:-/}"
OUT_NAME="${OUT_NAME:-done-video}"
READY_TIMEOUT="${READY_TIMEOUT:-180}"
# Files the dev server is known to rewrite on boot, restored during cleanup.
# Anything else left dirty is reported rather than discarded.
GENERATED_PATHS="${GENERATED_PATHS:-}"

log() { printf '\033[36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31mfatal:\033[0m %s\n' "$*" >&2; exit 1; }

# --- guards -----------------------------------------------------------------

git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || die "$REPO is not a git repo"

# Tracked changes only. Untracked files are the user's business and are left be,
# but anything modified would silently ride along into both recordings.
#
# GENERATED_PATHS are exempt: the dev server rewrites them on every boot, so a
# previous run leaves them dirty and the guard would refuse to run ever again.
dirty="$(git -C "$REPO" status --porcelain --untracked-files=no | awk '{print $2}')"
for generated in $GENERATED_PATHS; do
  dirty="$(printf '%s\n' "$dirty" | grep -v -x -F "$generated" || true)"
done
if [ -n "$(printf '%s' "$dirty" | tr -d '[:space:]')" ]; then
  printf '%s\n' "$dirty" >&2
  die "working tree has uncommitted changes; commit or stash before recording"
fi

for ref in "$BEFORE_REF" "$AFTER_REF"; do
  git -C "$REPO" rev-parse --verify --quiet "$ref" >/dev/null || die "unknown ref: $ref"
done

for tool in node ffmpeg ffprobe curl; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done

# Detached HEAD reports as "HEAD", so fall back to the sha to restore exactly.
START_REF="$(git -C "$REPO" symbolic-ref --quiet --short HEAD || git -C "$REPO" rev-parse HEAD)"

# --- process lifecycle ------------------------------------------------------

SERVER_PID=""

# The dev command spawns children (a bundler, a framework server). Killing only
# the parent orphans them holding the port, so walk the tree depth-first.
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  local code=$?
  if [ -n "$SERVER_PID" ]; then
    log "stopping dev server"
    kill_tree "$SERVER_PID"
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  # Restore only what the dev server is known to rewrite. A blanket
  # `checkout -- .` would also throw away anything saved during the run.
  if [ -n "$GENERATED_PATHS" ]; then
    # shellcheck disable=SC2086
    git -C "$REPO" checkout --quiet -- $GENERATED_PATHS 2>/dev/null || true
  fi
  local dirty
  dirty="$(git -C "$REPO" status --porcelain --untracked-files=no)"
  if [ -n "$dirty" ]; then
    printf '\033[33mtracked files left modified — review before committing:\033[0m\n%s\n' "$dirty" >&2
  fi
  local now
  now="$(git -C "$REPO" symbolic-ref --quiet --short HEAD || git -C "$REPO" rev-parse HEAD)"
  if [ "$now" != "$START_REF" ]; then
    log "restoring $START_REF"
    git -C "$REPO" checkout --quiet "$START_REF" || \
      printf '\033[31mcould not restore %s — you are on %s\033[0m\n' "$START_REF" "$now" >&2
  fi
  [ "$code" -eq 0 ] || printf '\033[31mharness failed (exit %s)\033[0m\n' "$code" >&2
  exit "$code"
}
trap cleanup EXIT INT TERM

# --- port -------------------------------------------------------------------

# Never assume a port is ours. Another project may already own the usual one,
# and killing it to make room would be someone else's bad afternoon.
pick_port() {
  local port=${1:-3001}
  while lsof -i "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1; do
    port=$((port + 1))
    [ "$port" -gt 3100 ] && die "no free port between 3001 and 3100"
  done
  printf '%s' "$port"
}
PORT="$(pick_port "${PORT:-3001}")"
ADMIN_URL="http://localhost:${PORT}${ADMIN_PATH}"

start_server() {
  local ref=$1
  log "checking out $ref"
  git -C "$REPO" checkout --quiet "$ref"

  # Only packages the dev server serves from source pick a ref change up for
  # free. Anything consumed from dist has to be rebuilt between refs, or the
  # recording shows the previous ref's behaviour.
  if [ -n "${BUILD_CMD:-}" ]; then
    log "building"
    ( cd "$REPO" && eval "$BUILD_CMD" ) >"$HERE/build-${ref//\//-}.log" 2>&1 \
      || die "build failed; see build-${ref//\//-}.log"
  fi

  # Branch names contain slashes, which would make the log path a directory.
  local logfile="$HERE/server-${ref//\//-}.log"

  log "starting dev server on port $PORT"
  ( cd "$APP_DIR" && eval "${DEV_CMD//%PORT%/$PORT}" ) >"$logfile" 2>&1 &
  SERVER_PID=$!

  # Poll for readiness. A fixed sleep is either a stall or a race.
  local waited=0
  until curl -sf -o /dev/null "$ADMIN_URL"; do
    kill -0 "$SERVER_PID" 2>/dev/null || die "dev server died; see $logfile"
    sleep 2
    waited=$((waited + 2))
    [ "$waited" -ge "$READY_TIMEOUT" ] && die "server not ready after ${READY_TIMEOUT}s"
  done
  log "server ready after ${waited}s"
}

stop_server() {
  [ -n "$SERVER_PID" ] || return 0
  kill_tree "$SERVER_PID"
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
}

record() {
  local segment=$1
  log "recording $segment"
  ( cd "$HERE" && CAPTIONS="${CAPTIONS:-off}" SEGMENT="$segment" \
      ADMIN_URL="$ADMIN_URL" APP_DIR="$APP_DIR" PR_URL="$PR_URL" node record.mjs )
}

# --- run --------------------------------------------------------------------

# Narration first: the capture paces itself to these durations, so it has to
# exist before anything is recorded. Skipped when already current.
if [ ! -f "$HERE/timings.json" ] || [ "$HERE/beats.json" -nt "$HERE/timings.json" ]; then
  log "generating narration"
  ( cd "$HERE" && "${PYTHON:-$HERE/.venv/bin/python}" clone.py )
else
  log "narration is current, skipping"
fi

start_server "$BEFORE_REF"
record before
stop_server

start_server "$AFTER_REF"
record after
record intro   # branch-independent, but the browser is already warm
stop_server

log "assembling"
( cd "$HERE" && OUT_NAME="$OUT_NAME" ./assemble.sh )

log "done: $HERE/$OUT_NAME.mp4"
