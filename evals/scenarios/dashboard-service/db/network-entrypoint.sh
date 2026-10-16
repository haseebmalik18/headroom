#!/bin/sh
# Adds DB_NETWORK_DELAY of one-way latency (e.g. "500us") to traffic leaving the
# database container, modelling an app server and database on separate hosts.
# Set DB_NETWORK_DELAY=0 to disable.
set -e

if [ -n "${DB_NETWORK_DELAY:-}" ] && [ "${DB_NETWORK_DELAY}" != "0" ]; then
  if tc qdisc replace dev eth0 root netem delay "${DB_NETWORK_DELAY}" limit 100000; then
    echo "network-entrypoint: added ${DB_NETWORK_DELAY} egress delay on eth0"
  else
    echo "network-entrypoint: WARNING could not apply netem delay (needs NET_ADMIN)" >&2
  fi
fi

exec docker-entrypoint.sh "$@"
