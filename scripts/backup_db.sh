#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
# nexus-core — scheduled PostgreSQL backup (pg_dump | gzip)
# ═══════════════════════════════════════════════════════════════════════════
#
# POSIX sh on purpose: the same file runs under Alpine's busybox sh inside the
# compose `backup` service AND from cron on a host. No bashisms, no jq, no
# python — a backup script that needs its own dependency tree is a backup script
# that fails exactly when you need it.
#
#   ./scripts/backup_db.sh                 # one dump now
#   docker compose --profile backup run --rm backup
#   crontab: see scripts/backup_db.cron    # daily at 02:15
#
# Configuration (environment, all optional except the password for auth setups):
#   PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE   standard libpq variables
#   BACKUP_DIR          where dumps land            (default ./backups)
#   BACKUP_KEEP_DAYS    retention in days           (default 7, 0 = keep all)
#   BACKUP_PREFIX       filename prefix             (default nexus)
#   BACKUP_LOCK         lock file                   (default $BACKUP_DIR/.backup.lock)
#
# Exit codes: 0 = dump written and verified, 1 = dump failed, 2 = config error,
# 3 = another run holds the lock (overlap protection — never two dumps at once).
set -eu

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGDATABASE="${PGDATABASE:-postgres}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
BACKUP_PREFIX="${BACKUP_PREFIX:-nexus}"
BACKUP_LOCK="${BACKUP_LOCK:-$BACKUP_DIR/.backup.lock}"

log() { printf '%s backup_db: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
die() { log "FATAL: $*"; exit "${2:-1}"; }

command -v pg_dump >/dev/null 2>&1 || die "pg_dump not found (is postgresql-client installed?)" 2
command -v gzip >/dev/null 2>&1 || die "gzip not found" 2
mkdir -p "$BACKUP_DIR" || die "cannot create BACKUP_DIR=$BACKUP_DIR" 2

# ── overlap protection ──
# A slow dump that is still running must not be joined by a second one; the
# lock is released by the trap even when the dump dies mid-way.
if mkdir "$BACKUP_LOCK" 2>/dev/null; then
    trap 'rmdir "$BACKUP_LOCK" 2>/dev/null || true' EXIT INT TERM
else
    die "another backup is running (lock: $BACKUP_LOCK)" 3
fi

STAMP="$(date -u '+%Y%m%d-%H%M%S')"
OUT="$BACKUP_DIR/${BACKUP_PREFIX}-db-${STAMP}.sql.gz"
TMP="$OUT.part"

log "dumping $PGDATABASE from $PGHOST:$PGPORT -> $OUT"

# --no-owner/--no-privileges: the dump restores into a database whose roles may
# differ (a fresh container, a managed platform) without failing on GRANTs.
# --clean --if-exists: a restore can be replayed over an existing database.
if ! pg_dump \
        --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$PGDATABASE" \
        --no-owner --no-privileges --clean --if-exists \
        --format=plain 2> "$BACKUP_DIR/.pg_dump.err" \
    | gzip -9 -c > "$TMP"; then
    log "pg_dump stderr: $(cat "$BACKUP_DIR/.pg_dump.err" 2>/dev/null | tail -3)"
    rm -f "$TMP"
    die "pg_dump failed"
fi
rm -f "$BACKUP_DIR/.pg_dump.err"

# ── verify before trusting the file ──
# A 0-byte or truncated gzip is worse than no backup: it looks like one.
SIZE="$(wc -c < "$TMP" | tr -d ' ')"
[ "$SIZE" -gt 64 ] || { rm -f "$TMP"; die "dump is suspiciously small (${SIZE} bytes)"; }
gzip -t "$TMP" || { rm -f "$TMP"; die "dump is not a valid gzip archive"; }

mv "$TMP" "$OUT"
log "ok: ${SIZE} bytes"

# ── retention ──
if [ "$BACKUP_KEEP_DAYS" -gt 0 ] 2>/dev/null; then
    KEPT=0
    PRUNED=0
    # find -mtime works on busybox and GNU; -maxdepth keeps it inside BACKUP_DIR.
    for old in $(find "$BACKUP_DIR" -maxdepth 1 -name "${BACKUP_PREFIX}-db-*.sql.gz" \
                 -type f -mtime "+$BACKUP_KEEP_DAYS" 2>/dev/null); do
        rm -f "$old" && PRUNED=$((PRUNED + 1))
    done
    for _ in $(find "$BACKUP_DIR" -maxdepth 1 -name "${BACKUP_PREFIX}-db-*.sql.gz" -type f 2>/dev/null); do
        KEPT=$((KEPT + 1))
    done
    log "retention: keep ${BACKUP_KEEP_DAYS}d, pruned=${PRUNED}, kept=${KEPT}"
fi

log "done"
