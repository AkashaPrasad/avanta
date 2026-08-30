#!/bin/sh
set -eu

# Railway and other managed runtimes attach persistent volumes after the image
# layer is built, so their root directory is owned by root even though the
# Dockerfile prepared /data for the application user. Claim only this dedicated
# mount, then immediately drop privileges for the API process.
mkdir -p /data
chown avanta:avanta /data

exec runuser -u avanta -- "$@"
