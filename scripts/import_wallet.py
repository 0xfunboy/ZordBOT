#!/usr/bin/env python3
"""Utility script to import the bot's WIF into the local zcashd wallet."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config  # noqa: E402
from core.logger import get_logger  # noqa: E402
from core.rpc import RPCClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import wallet key into zcashd")
    parser.add_argument("--config", default="config.yaml", help="Base config path")
    parser.add_argument(
        "--local-config",
        default="config.local.yaml",
        help="Secret overrides path (must contain wallet_wif)",
    )
    parser.add_argument("--rescan", action="store_true", help="Force rescan after importing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config, args.local_config)
    secrets = cfg.get("secrets", {})
    wif = secrets.get("wallet_wif")
    label = secrets.get("wallet_label", "zordbot")
    rescan = args.rescan or secrets.get("wallet_rescan", False)

    if not wif or "PASTE" in wif:
        raise SystemExit("wallet_wif missing. Edit config.local.yaml before running.")

    logger = get_logger(name="wallet-import")
    rpc = RPCClient(cfg["network"]["rpc_nodes"], logger)

    logger.info("Importing key for label %s", label)
    rpc.call("importprivkey", [wif, label, bool(rescan)])
    logger.info("Key imported. Run 'zcash-cli listunspent' to verify balances.")


if __name__ == "__main__":
    main()
