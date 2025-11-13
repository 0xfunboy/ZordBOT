# ZordBOT

A production-ready, modular ZRC-20 minting bot that bundles its own Zcash RPC node bootstrap, multi-wallet orchestration, retry/resume logic, and automation hooks (looping, scheduler, watchers, external APIs).

---

## Feature Highlights
- **End-to-end flow**: build mint JSON, fetch UTXO, craft Ordinal-style scriptSig, sign via local `zcashd`, and broadcast.
- **Multi-mint & multi-tick**: batch size per tick, multiple targets, and wallet strategies (`round_robin`/`richest`).
- **Resilience**: RPC failover, configurable retry/backoff, structured logging, rate limiting, and mempool guard rails.
- **Dynamic fees**: local `estimatesmartfee` with optional external API fallback.
- **Automation**: manual runs, continuous loop, watcher-based triggers, and cron-like scheduler.
- **Node bootstrap**: Docker Compose setup, `.env` + `config.local.yaml` scaffolding, and helper script to import the wallet WIF.

---

## Repository Layout
| Path | Purpose |
| --- | --- |
| `main.py` | CLI entrypoint, argument parsing, and orchestration of mint loops/watchers/scheduler. |
| `config.yaml` | Base (non-secret) configuration shared by all environments. |
| `config.local.yaml` | **Gitignored** overrides for secrets (RPC creds, WIF, labels, etc.). Sample provided. |
| `core/` | Modular bot logic: logging, RPC client, wallet helpers, mint engine, inscription builder, scheduler, config loader. |
| `scripts/setup_node.sh` | Generates `.env`, `node/zcash.conf`, and `config.local.yaml` if missing. |
| `scripts/import_wallet.py` | Imports the configured WIF into the running `zcashd` wallet. |
| `docker-compose.yml` | Spins up `zcashd` with the generated config and persistent data dir `./node`. |

---

## Requirements
- Python 3.10+
- Docker + Docker Compose plugin (for the bundled node)
- Git, curl, jq (optional but useful)
- Funded Zcash transparent address (t-address) whose private key you control

---

## Installation & First Run (≈10 minutes)
1. **Clone and install dependencies**
   ```bash
   git clone https://github.com/0xfunboy/ZordBOT.git
   cd ZordBOT/zrc20_bot
   pip install -r requirements.txt
   ```
2. **Scaffold secrets and node config**
   ```bash
   ./scripts/setup_node.sh
   # -> creates .env, node/zcash.conf, config.local.yaml (all gitignored)
   ```
   Edit the generated files:
   - `.env`: set `ZCASH_RPCUSER`, `ZCASH_RPCPASSWORD`, `ZCASH_RPCPORT`, optional `ZCASH_NETWORK`/`ZCASH_ADDITIONAL_ARGS`.
   - `config.local.yaml`: set `secrets.wallet_wif`, `secrets.wallet_label`, and override any bot settings if needed.
3. **Start the local RPC node**
   ```bash
   docker compose up -d zcashd
   docker compose logs -f zcashd   # watch sync progress
   ```
4. **Import the wallet** (after the node accepts RPCs)
   ```bash
   ./scripts/import_wallet.py --rescan   # use --rescan if the wallet already has history
   ```
5. **Fund the address** configured in `config.yaml` (or overrides). Confirm UTXOs:
   ```bash
   docker compose exec zcashd zcash-cli listunspent
   ```
6. **Run the bot**
   ```bash
   python main.py --once          # single batch run
   python main.py --loop          # continuous mint loop
   python main.py --watch         # watcher mode (API/mempool gate)
   python main.py --schedule      # scheduler-defined intervals
   ```

---

## Configuration Details
- **network.rpc_nodes**: ordered list of RPC endpoints (failover aware). When using the bundled node you typically keep a single entry pointing to `http://127.0.0.1:8232` plus the user/pass from `.env`.
- **bot** block:
  - `wallets`: array of labelled addresses for multi-wallet rotation.
  - `wallet_strategy`: `round_robin` or `richest` selection per mint.
  - `fee`, `fee_dynamic`, `rate_limit_seconds`, `retry`, etc. tune execution behavior.
  - `scheduler` and `auto_loop` toggles control automation modes.
- **mint** block: default tick/amount/batch plus optional `targets` array to mint several ticks per cycle.
- **mempool.enabled**: activate the lightweight mempool scanner to skip minting if the tick already appears in-flight.
- **external_api**: optional JSON endpoints for fee hints or “ticker live” statuses (used by watcher mode).
- **secrets** (in `config.local.yaml`):
  ```yaml
  secrets:
    wallet_wif: "L1abc..."
    wallet_label: "zordbot"
    wallet_rescan: false
  ```
  These values are merged into the main config at runtime via `core.config.load_config`.

---

## Operating Modes
| Command | Description |
| --- | --- |
| `python main.py --once` | One-time mint across all configured targets. |
| `python main.py --loop` | Continuous mint loop with sleep interval `bot.interval_seconds`. |
| `python main.py --watch` | Periodically checks external ticker API + mempool; mints only when allowed. |
| `python main.py --schedule` | Runs cron-like jobs defined in `bot.scheduler.intervals`. |
| `python main.py` | Default behavior (manual command) when no flags/auto-loop are enabled. |

---

## Embedded Node Operations
- **Start**: `docker compose up -d zcashd`
- **Stop**: `docker compose down`
- **Logs**: `docker compose logs -f zcashd`
- **CLI passthrough**: `docker compose exec zcashd zcash-cli <method>`
- **Config location**: `node/zcash.conf`

You can also run `zcashd` outside Docker (native install or another host) and just update `network.rpc_nodes` accordingly.

---

## Troubleshooting
- `Connection refused`: ensure the node is running, credentials match `.env`, and ports aren’t firewalled.
- `listunspent` returns empty: import the correct WIF (`scripts/import_wallet.py`) and wait for rescan; also fund the address.
- `signrawtransaction` missing keys: your node is stateless—switch to a wallet-enabled `zcashd` and import the private key.
- `Watcher gating`: enable `watcher.enabled` only if you configured `external_api.ticker`; otherwise leave it off.

---

## Security Notes
- Never commit `.env`, `config.local.yaml`, or any private key. The `.gitignore` already protects them—keep it that way.
- Restrict RPC exposure (`rpcallowip`) and use firewalls when deploying beyond localhost.
- Consider running on testnet/regtest while validating new ticks or strategies before touching mainnet funds.

---

## Next Steps & Ideas
- SQLite journal of minted transactions & balances.
- Dashboard or API for monitoring mint throughput.
- Telegram/Discord bot hooks for manual trigger & status updates.
- Proxy/Tor support for RPC routing.
- Target-supply logic (mint only under a given supply threshold).

Contributions and issues are welcome—feel free to fork and extend the modules under `core/`.
