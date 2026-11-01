#!/bin/bash
# Panel self-update applier (detached).
# Usage: selfupdate-apply.sh <repo_dir> <python> <port> <ref>
#   ref: refs/heads/oss-zashboard  -> fast-forward the panel branch from origin
#   ref: refs/tags/<tag> -> fetch and check out the tag
# Aborts (leaving the running panel untouched) when the working tree is
# dirty or the update is not a clean fast-forward / checkout.
set -u
REPO="${1:?repo dir}"; PY="${2:?python}"; PORT="${3:-8080}"; REF="${4:-refs/heads/oss-zashboard}"
LOG="/tmp/openbox-oss-selfupdate.log"
STATUS="/tmp/openbox-oss-update.status"
PREP_STATE="/tmp/openbox-oss-update-prep.json"
# Drop any stale preparation state FIRST: the EXIT trap below restores the
# kernel from this file, and a stale was_running=true from an old run must
# never start a kernel this run did not suspend.
rm -f "$PREP_STATE"
# v0.1.344: kernel restore shared by success/failure/cancel paths.
# The EXIT trap runs restore first (panel API may be the restarted panel:
# --wait-panel), then writes the final stage. The TERM trap (cancel from
# the panel) restores and marks cancelled; SIGKILL cannot be trapped, so
# a KILLed applier leaves the kernel down -- the panel-side cancel path
# (selfupdate.cancel_update with the kernel manager) covers that case.
# trap 在面板重启之后才触发，写文件不受重启影响。
CANCELLED=0
restore_kernel() {
  PYTHONPATH="$REPO/oss" "$PY" -m core.upgradeprep restore --port "$PORT" --state-file "$PREP_STATE" --wait-panel || true
}
trap 'code=$?; restore_kernel; if [ "$CANCELLED" = 1 ]; then st=cancelled; elif [ "$code" -eq 0 ]; then st=done; else st=failed; fi; printf "stage=%s\nat=%s\nref=%s\nmessage=see %s\n" "$st" "$(date +%s%3N)" "$REF" "$LOG" > "$STATUS"' EXIT
trap 'CANCELLED=1; echo "[selfupdate] cancelled, restoring kernel"; exit 143' TERM INT
exec >>"$LOG" 2>&1
echo "[selfupdate] start $(date '+%F %T') repo=$REPO ref=$REF"

# let the triggering HTTP response finish first
sleep 3
cd "$REPO" || { echo "[selfupdate] cannot cd to repo"; exit 1; }

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "[selfupdate] working tree dirty, abort (panel untouched)"
  exit 1
fi

# v0.1.344 preparation BEFORE the first network request: suspend a running
# kernel, wait for real exit, clean possibly-poisoned FakeIP answers from
# the local DNS cache. On failure nothing has been downloaded or changed
# (the helper restores the kernel first when it already stopped it).
if ! PYTHONPATH="$REPO/oss" "$PY" -m core.upgradeprep prepare --port "$PORT" --state-file "$PREP_STATE"; then
  echo "[selfupdate] preparation failed, abort before download"
  exit 1
fi

if [[ "$REF" == refs/tags/* ]]; then
  TAG="${REF#refs/tags/}"
  echo "[selfupdate] fetching tag $TAG"
  git fetch origin "refs/tags/$TAG:refs/tags/$TAG" || { echo "[selfupdate] fetch tag failed"; exit 1; }
  if ! git checkout "$TAG"; then
    echo "[selfupdate] checkout $TAG failed"
    exit 1
  fi
  echo "[selfupdate] now at $(git rev-parse --short HEAD) ($TAG)"
else
  BRANCH="${REF#refs/heads/}"
  echo "[selfupdate] fetching origin"
  if ! git fetch origin; then
    echo "[selfupdate] fetch failed, abort"
    exit 1
  fi
  CUR="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$CUR" != "$BRANCH" ]; then
    echo "[selfupdate] currently on $CUR, checking out $BRANCH"
    git checkout "$BRANCH" || { echo "[selfupdate] checkout failed"; exit 1; }
  fi
  if ! git merge --ff-only "origin/$BRANCH"; then
    echo "[selfupdate] not a fast-forward, abort (panel untouched)"
    exit 1
  fi
  echo "[selfupdate] updated to $(git rev-parse --short HEAD)"
fi
# NOTE: frontend/dist is committed, so the pulled tree already contains the
# built frontend; no rebuild needed here.

echo "[selfupdate] restarting panel on :$PORT"
pkill -f "panel/run.py" || true
sleep 2
# shellcheck disable=SC2086
setsid "$PY" "$REPO/oss/panel/run.py" >>"$LOG" 2>&1 &
echo "[selfupdate] panel restarted, new pid $!"
