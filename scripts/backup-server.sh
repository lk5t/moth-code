#!/usr/bin/env bash
# Back up the MOTH Server's critical data to owner-controlled storage.
#
#   MOTH_SERVER_DATA_DIR=/data MOTH_SERVER_DATABASE_URL=... MOTH_BACKUP_DIR=/backups \
#   [MOTH_BACKUP_REMOTE=owner-s3:moth-backups] [MOTH_BACKUP_GPG_RECIPIENT=owner@example.com] \
#   scripts/backup-server.sh
#
# Produces a timestamped archive with: a consistent database dump (pg_dump, or SQLite's
# online backup), official model releases + worker releases (storage/), and the training
# coordinator state (checkpoints, shards, probe set). Optionally encrypts with GPG and copies
# off-host with rclone (any S3/B2/SFTP remote you control). Keeps the newest $KEEP archives.
set -euo pipefail
DATA="${MOTH_SERVER_DATA_DIR:?}"
OUT="${MOTH_BACKUP_DIR:?}"
KEEP="${MOTH_BACKUP_KEEP:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT" "$WORK/moth-backup-$STAMP"
DEST="$WORK/moth-backup-$STAMP"

URL="${MOTH_SERVER_DATABASE_URL:-}"
if [[ "$URL" == postgresql* ]]; then
  pg_dump --format=custom --file="$DEST/database.pgdump" "${URL/+psycopg/}"
else
  python3 - "$DATA/moth-server.db" "$DEST/database.sqlite" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)  # consistent online backup
dst.close(); src.close()
PY
fi
for d in storage coordinator eval; do
  [[ -d "$DATA/$d" ]] && cp -a "$DATA/$d" "$DEST/$d"
done
( cd "$DEST" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
ARCHIVE="$OUT/moth-backup-$STAMP.tar.gz"
tar -C "$WORK" -czf "$ARCHIVE" "moth-backup-$STAMP"
if [[ -n "${MOTH_BACKUP_GPG_RECIPIENT:-}" ]]; then
  gpg --batch --yes --encrypt --recipient "$MOTH_BACKUP_GPG_RECIPIENT" --output "$ARCHIVE.gpg" "$ARCHIVE"
  rm -f "$ARCHIVE"
  ARCHIVE="$ARCHIVE.gpg"
fi
chmod 600 "$ARCHIVE"
if [[ -n "${MOTH_BACKUP_REMOTE:-}" ]]; then
  rclone copy "$ARCHIVE" "$MOTH_BACKUP_REMOTE" --checksum
fi
ls -1t "$OUT"/moth-backup-*.tar.gz* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "backup written: $ARCHIVE"
