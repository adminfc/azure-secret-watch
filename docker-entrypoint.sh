#!/bin/sh
# Bind-mounted host directories (./data, ./certs) often land inside the
# container owned by root, even though the app runs as the unprivileged
# "watcher" user — that mismatch is what causes "unable to open database
# file" on a fresh Linux host. Fix ownership here (while we're still root),
# then drop to "watcher" for the real process.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown -R watcher:watcher /data
    exec su watcher -s /bin/sh -c 'exec python -m azure_secret_watch "$@"' -- "$@"
fi

exec python -m azure_secret_watch "$@"
