#!/bin/sh
set -eu

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=db_user="$POSTGRES_USER" <<'SQL'
SELECT format('CREATE SCHEMA IF NOT EXISTS n8n AUTHORIZATION %I', :'db_user')
\gexec
SQL

