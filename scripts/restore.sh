#!/usr/bin/env bash
# Restore a TruthLens backup tarball into the data volume. STOP the app first:
#   docker compose down && scripts/restore.sh backups/truthlens-XXXX.tar.gz && docker compose up -d
set -euo pipefail
VOLUME="${TRUTHLENS_VOLUME:-truthlens-storage}"
ARCHIVE="${1:?usage: scripts/restore.sh <backup.tar.gz>}"
[ -f "$ARCHIVE" ] || { echo "No such file: $ARCHIVE" >&2; exit 1; }
if [ -n "$(docker ps -q --filter volume="$VOLUME")" ]; then
  echo "Volume $VOLUME is in use by a running container; stop it first (docker compose down)." >&2; exit 1
fi
ARCH_DIR="$(cd "$(dirname "$ARCHIVE")" && pwd)"; ARCH_NAME="$(basename "$ARCHIVE")"
docker volume create "$VOLUME" >/dev/null
docker run --rm -v "$VOLUME":/storage -v "$ARCH_DIR":/backup:ro alpine sh -c "
  set -e
  find /storage -mindepth 1 -delete
  tar -xzf /backup/$ARCH_NAME -C /storage
  chown -R 10001:10001 /storage
"
echo "Restored $ARCHIVE into volume $VOLUME"
