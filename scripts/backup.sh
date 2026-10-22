#!/usr/bin/env bash
# Back up the TruthLens data volume (ChromaDB vectors, SQLite history/feedback, uploads) to a tarball.
# Usage: scripts/backup.sh [output_dir]        (default: ./backups)
# Safe to run while the app is up: SQLite is copied with its online backup API, the rest as files.
set -euo pipefail
VOLUME="${TRUTHLENS_VOLUME:-truthlens-storage}"
OUT_DIR="${1:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
OUT_ABS="$(cd "$OUT_DIR" && pwd)"

docker volume inspect "$VOLUME" >/dev/null 2>&1 || { echo "Volume $VOLUME not found" >&2; exit 1; }

docker run --rm -v "$VOLUME":/storage:ro -v "$OUT_ABS":/backup python:3.12-slim sh -c "
  set -e
  mkdir -p /tmp/snap && cp -a /storage/. /tmp/snap/
  # consistent SQLite copy even if a write was in flight
  if [ -f /storage/truthlens.db ]; then
    python -c \"import sqlite3; s=sqlite3.connect('file:/storage/truthlens.db?mode=ro', uri=True); d=sqlite3.connect('/tmp/snap/truthlens.db'); s.backup(d); d.close(); s.close()\"
  fi
  tar -czf /backup/truthlens-$STAMP.tar.gz -C /tmp/snap .
"
echo "Backup written: $OUT_ABS/truthlens-$STAMP.tar.gz"
# keep the newest 14 backups
ls -1t "$OUT_ABS"/truthlens-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
