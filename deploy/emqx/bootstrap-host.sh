#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR=/home/alex/coffee-emqx
ENV_FILE="$DEPLOY_DIR/.env"

umask 077
if [[ ! -f "$ENV_FILE" ]]; then
  dashboard_password="$(openssl rand -base64 36 | tr -d '\n')"
  node_cookie="$(openssl rand -hex 32)"
  {
    printf 'EMQX_DASHBOARD_USERNAME=admin\n'
    printf 'EMQX_DASHBOARD_PASSWORD=%s\n' "$dashboard_password"
    printf 'EMQX_NODE_COOKIE=%s\n' "$node_cookie"
  } > "$ENV_FILE"
fi
if ! grep -q '^EMQX_NODE_COOKIE=' "$ENV_FILE"; then
  printf 'EMQX_NODE_COOKIE=%s\n' "$(openssl rand -hex 32)" >> "$ENV_FILE"
fi
chmod 0600 "$ENV_FILE"

sudo install -d -m 0750 -o 1000 -g 1000 "$DEPLOY_DIR/certs"
for name in fullchain.pem chain.pem privkey.pem; do
  sudo install -m 0640 -o 1000 -g 1000 "/etc/letsencrypt/live/mqtt-api.woodbridge.top/$name" "$DEPLOY_DIR/certs/$name"
done
sudo install -m 0640 -o 1000 -g 1000 "$DEPLOY_DIR/certs/privkey.pem" "$DEPLOY_DIR/certs/key.pem"
sudo install -m 0640 -o 1000 -g 1000 "$DEPLOY_DIR/certs/fullchain.pem" "$DEPLOY_DIR/certs/cert.pem"
sudo install -m 0640 -o 1000 -g 1000 "$DEPLOY_DIR/certs/chain.pem" "$DEPLOY_DIR/certs/cacert.pem"

sudo install -m 0750 -o root -g root "$DEPLOY_DIR/renew-certificate.sh" \
  /etc/letsencrypt/renewal-hooks/deploy/coffee-emqx.sh

docker compose -f "$DEPLOY_DIR/compose.yaml" pull
docker compose -f "$DEPLOY_DIR/compose.yaml" up -d
