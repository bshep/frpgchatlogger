#!/bin/bash
set -euo pipefail

# --- Configuration ---
# This script assumes it's run by a user with access to these paths.
# The DB_FILE path should match the location where your backend creates the SQLite file.
DB_FILE="/var/www/frpgchatlogger/backend/chatlog.db"
BACKUP_DIR="/var/www/frpgchatlogger/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/chatlog_backup_$TIMESTAMP.db.gz"

# --- Main Logic ---
echo "Starting database backup process..."

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

# Check if the database file exists
if [ ! -f "$DB_FILE" ]; then
    echo "Database file not found at $DB_FILE. Skipping backup."
    exit 0
fi

# Create a temporary backup and compress it
# The .backup command is the safest way to take a snapshot of a live SQLite database.
TEMP_BACKUP_FILE=$(mktemp)
echo "Backing up $DB_FILE to temporary file..."
sqlite3 "$DB_FILE" ".backup '$TEMP_BACKUP_FILE'"

echo "Compressing backup to $BACKUP_FILE..."
gzip -c "$TEMP_BACKUP_FILE" > "$BACKUP_FILE"

# Clean up the temporary uncompressed backup file
rm "$TEMP_BACKUP_FILE"

# (Optional) Clean up old backups, e.g., keep backups for the last 14 days
echo "Cleaning up old backups (older than 14 days)..."
find "$BACKUP_DIR" -name "chatlog_backup_*.db.gz" -mtime +14 -exec rm {} \;

echo "Backup complete: $BACKUP_FILE"
