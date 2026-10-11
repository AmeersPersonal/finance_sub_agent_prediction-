#!/usr/bin/env bash
# Project-owned PostgreSQL cluster. Never touches system clusters or credentials.
set -euo pipefail

backend_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cluster_dir="$backend_dir/data/postgres"
socket_dir="$backend_dir/data/pgsocket"
pg_bin="${POSTGRES_BIN:-/usr/lib/postgresql/18/bin}"
log_file="$backend_dir/data/postgres-server.log"

case "${1:-status}" in
    init)
        if [[ -f "$cluster_dir/PG_VERSION" ]]; then
            echo "Project PostgreSQL cluster already exists."
            exit 0
        fi
        mkdir -p "$socket_dir"
        chmod 700 "$socket_dir"
        "$pg_bin/initdb" -D "$cluster_dir" -E UTF8 --locale=C.UTF-8 \
            --auth-local=peer --auth-host=scram-sha-256
        cat >> "$cluster_dir/postgresql.conf" <<EOF

# Project development instance: accessible only on this computer.
listen_addresses = '127.0.0.1'
port = 55440
unix_socket_directories = '$socket_dir'
password_encryption = 'scram-sha-256'
EOF
        ;;
    start)
        if [[ ! -f "$cluster_dir/PG_VERSION" ]]; then
            echo "Initialize first: $0 init" >&2
            exit 1
        fi
        if "$pg_bin/pg_ctl" -D "$cluster_dir" status >/dev/null 2>&1; then
            echo "Project PostgreSQL is already running."
        else
            "$pg_bin/pg_ctl" -D "$cluster_dir" -l "$log_file" -w start
        fi
        ;;
    stop)
        if "$pg_bin/pg_ctl" -D "$cluster_dir" status >/dev/null 2>&1; then
            "$pg_bin/pg_ctl" -D "$cluster_dir" -m fast -w stop
        else
            echo "Project PostgreSQL is stopped."
        fi
        ;;
    status)
        "$pg_bin/pg_ctl" -D "$cluster_dir" status
        ;;
    *)
        echo "Usage: $0 {init|start|stop|status}" >&2
        exit 2
        ;;
esac
