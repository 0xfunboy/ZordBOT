#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_SAMPLE="$ROOT_DIR/.env.sample"
ENV_FILE="$ROOT_DIR/.env"
CONFIG_DIR="$ROOT_DIR/node"
CONFIG_FILE="$CONFIG_DIR/zcash.conf"
LOCAL_CFG_SAMPLE="$ROOT_DIR/config.local.example.yaml"
LOCAL_CFG="$ROOT_DIR/config.local.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ENV_SAMPLE" "$ENV_FILE"
  echo "[setup-node] Created .env from sample. Please edit $ENV_FILE before continuing."
  exit 0
fi

source "$ENV_FILE"

mkdir -p "$CONFIG_DIR"

NETWORK_FLAGS=""
case "${ZCASH_NETWORK:-mainnet}" in
  mainnet)
    NETWORK_FLAGS=""
    ;;
  testnet)
    NETWORK_FLAGS=$'testnet=1\naddnode=testnet.z.cash'
    ;;
  regtest)
    NETWORK_FLAGS=$'regtest=1'
    ;;
  *)
    echo "[setup-node] Unknown ZCASH_NETWORK value: ${ZCASH_NETWORK}. Using mainnet."
    ;;
 esac

cat > "$CONFIG_FILE" <<EOF
server=1
listen=1
rpcuser=${ZCASH_RPCUSER}
rpcpassword=${ZCASH_RPCPASSWORD}
rpcallowip=0.0.0.0/0
rpcbind=0.0.0.0
rpcport=${ZCASH_RPCPORT:-8232}
txindex=1
addnode=mainnet.z.cash
${NETWORK_FLAGS}
EOF

echo "[setup-node] Wrote $CONFIG_FILE"

if [[ ! -f "$LOCAL_CFG" ]]; then
  cp "$LOCAL_CFG_SAMPLE" "$LOCAL_CFG"
  echo "[setup-node] Created $LOCAL_CFG. Fill in wallet_wif before importing."
fi

echo "[setup-node] Node config ready. Start it with:"
echo "  docker compose up -d zcashd"
