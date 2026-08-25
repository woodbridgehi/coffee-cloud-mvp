#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR=/etc/letsencrypt/live/mqtt-api.woodbridge.top
TARGET_DIR=/home/alex/coffee-emqx/certs

install -d -m 0750 -o 1000 -g 1000 "$TARGET_DIR"
for name in fullchain.pem chain.pem privkey.pem; do
  install -m 0640 -o 1000 -g 1000 "$SOURCE_DIR/$name" "$TARGET_DIR/$name"
done
install -m 0640 -o 1000 -g 1000 "$TARGET_DIR/privkey.pem" "$TARGET_DIR/key.pem"
install -m 0640 -o 1000 -g 1000 "$TARGET_DIR/fullchain.pem" "$TARGET_DIR/cert.pem"
install -m 0640 -o 1000 -g 1000 "$TARGET_DIR/chain.pem" "$TARGET_DIR/cacert.pem"

docker compose -f /home/alex/coffee-emqx/compose.yaml restart emqx
