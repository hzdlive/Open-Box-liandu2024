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
# 退出时写最终状态（对标原版：进度靠状态文件读回，面板不直接等 applier）。
# trap 在面板重启之后才触发，写文件不受重启影响。
trap 'code=$?; if [ "$code" -eq 0 ]; then st=done; else st=failed; fi; printf "stage=%s\nat=%s\nref=%s\nmessage=see %s\n" "$st" "$(date +%s%3N)" "$REF" "$LOG" > "$STATUS"' EXIT
exec >>"$LOG" 2>&1
echo "[selfupdate] start $(date '+%F %T') repo=$REPO ref=$REF"

# let the triggering HTTP response finish first
sleep 3
cd "$REPO" || { echo "[selfupdate] cannot cd to repo"; exit 1; }

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "[selfupdate] working tree dirty, abort (panel untouched)"
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
