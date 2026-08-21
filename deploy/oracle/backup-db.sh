#!/usr/bin/env sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="$repo_dir/deploy/oracle/compose.yaml"
env_file="$repo_dir/deploy/oracle/.env"
backup_dir="${1:-$repo_dir/backups}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$backup_dir"
docker compose --env-file "$env_file" -f "$compose_file" exec -T db \
  pg_dump -U comic_ficp -d comic_ficp | gzip > "$backup_dir/comic-ficp-$stamp.sql.gz"
printf '%s\n' "$backup_dir/comic-ficp-$stamp.sql.gz"
