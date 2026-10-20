#!/usr/bin/env bash
# Run only in the isolated pilot after the branch checks have passed.
set -euo pipefail
cd /root/transfrota-pwa-piloto
if [ ! -f deploy/pwa/.env ]; then
    echo 'Arquivo de configuração do piloto não encontrado.' >&2
    exit 1
fi
compose=(docker compose --env-file deploy/pwa/.env -f deploy/pwa/compose.yaml)
backup_dir="/root/transfrota-backups/companies-$(date +%Y%m%d-%H%M%S)"
umask 077
mkdir -p "$backup_dir"
git rev-parse HEAD > "$backup_dir/commit.txt"
git diff > "$backup_dir/local-changes.patch"
cp deploy/pwa/compose.yaml "$backup_dir/compose.yaml"
cp deploy/pwa/nginx.conf "$backup_dir/nginx.conf"
"${compose[@]}" exec -T database sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_dir/database.dump"
test -s "$backup_dir/database.dump"
web_id=$("${compose[@]}" ps -q web)
old_image=$(docker inspect --format '{{.Image}}' "$web_id")
docker image tag "$old_image" "transfrota-company-rollback:$(basename "$backup_dir")"
"${compose[@]}" build web
"${compose[@]}" run --rm --no-deps -T web python manage.py check
"${compose[@]}" run --rm --no-deps -T web python manage.py migrate --noinput
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 web
"${compose[@]}" exec -T proxy nginx -t
"${compose[@]}" exec -T proxy nginx -s reload
"${compose[@]}" ps
curl --fail --silent --show-error --max-time 15 -o /dev/null https://piloto.transfrota.digital/api/driver/app/manifest.webmanifest
echo "Piloto atualizado. Backup: $backup_dir"
echo 'Abra https://piloto.transfrota.digital/api/driver/management/ com a conta do proprietário.'
