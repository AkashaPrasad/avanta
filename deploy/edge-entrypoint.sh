#!/bin/sh
set -e
CERT_DIR=/etc/nginx/certs
HOST="${ORIGIN_HOST:-api.avanta.spacesdrive.cc}"
mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/origin.crt" ]; then
  # nginx:alpine does not ship openssl.
  command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null
  echo "generating a self-signed origin certificate for $HOST"
  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout "$CERT_DIR/origin.key" -out "$CERT_DIR/origin.crt" \
    -subj "/CN=$HOST" -addext "subjectAltName=DNS:$HOST"
fi

exec nginx -g 'daemon off;'
