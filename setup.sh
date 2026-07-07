#!/usr/bin/env bash
# Download the Chinook SQLite database into data/ (idempotent).
set -euo pipefail

mkdir -p data
if [ -f data/Chinook.db ]; then
  echo "data/Chinook.db already present — skipping download."
  exit 0
fi

echo "Downloading Chinook database..."
curl -s https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_Sqlite.sql \
  | sqlite3 data/Chinook.db

echo "Done: data/Chinook.db ($(du -h data/Chinook.db | cut -f1))"
