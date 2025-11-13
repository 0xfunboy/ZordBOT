from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List

import yaml

from core.logger import get_logger
from core.mint_engine import ExternalTickerWatcher, MempoolScanner, MintEngine, MintTarget
from core.rpc import RPCClient
from core.scheduler import ManualCommand, Scheduler, run_auto_loop
from core.wallet import Wallet, MultiWallet


class WalletSelector:
    def __init__(self, wallets: List[Wallet], strategy: str = "round_robin") -> None:
        self.wallets = wallets
        self.strategy = strategy
        self.multi = MultiWallet(wallets) if len(wallets) > 1 else None

    def pick(self, min_conf: int = 1) -> Wallet:
        if not self.multi:
            return self.wallets[0]
        if self.strategy == "richest":
            return self.multi.richest(min_conf)
        return self.multi.next_wallet()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ZRC-20 mint automation bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--once", action="store_true", help="Run a single mint cycle")
    parser.add_argument("--loop", action="store_true", help="Run continuous mint loop")
    parser.add_argument("--watch", action="store_true", help="Watch tick and mint when live")
    parser.add_argument("--schedule", action="store_true", help="Run scheduler defined in config")
    return parser.parse_args()


def load_config(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open() as fp:
        return yaml.safe_load(fp)


def resolve_log_level(cfg: dict) -> int:
    level = cfg.get("logging", {}).get("level", "INFO")
    return getattr(logging, str(level).upper(), logging.INFO)


def build_rpc(cfg: dict, logger) -> RPCClient:
    net_cfg = cfg["network"]
    retry_attempts = cfg.get("bot", {}).get("retry", 3)
    return RPCClient(
        net_cfg["rpc_nodes"],
        logger,
        retry_attempts=retry_attempts,
        retry_wait_seconds=net_cfg.get("retry_wait", 1),
        timeout_seconds=net_cfg.get("timeout", 10),
        rate_limit_per_sec=net_cfg.get("rate_limit_per_sec"),
    )


def build_wallets(cfg: dict, rpc, logger) -> List[Wallet]:
    bot_cfg = cfg.get("bot", {})
    wallets_cfg = bot_cfg.get("wallets")
    if wallets_cfg:
        return [Wallet(rpc, w["address"], logger, w.get("label")) for w in wallets_cfg]
    return [Wallet(rpc, bot_cfg["wallet_address"], logger, bot_cfg.get("label"))]


def build_targets(cfg: dict) -> List[MintTarget]:
    mint_cfg = cfg.get("mint", {})
    targets_cfg = mint_cfg.get("targets")
    if targets_cfg:
        return [
            MintTarget(
                tick=t.get("tick", mint_cfg.get("tick", "ZERO")),
                amount=t.get("amount", mint_cfg.get("amount", 0)),
                batch=t.get("batch", mint_cfg.get("batch", 1)),
            )
            for t in targets_cfg
        ]
    return [
        MintTarget(
            tick=mint_cfg.get("tick", "ZERO"),
            amount=mint_cfg.get("amount", 0),
            batch=mint_cfg.get("batch", 1),
        )
    ]


def build_engine(cfg: dict, rpc, logger) -> MintEngine:
    bot_cfg = cfg.get("bot", {})
    fee_default = bot_cfg.get("fee", bot_cfg.get("default_fee", 0.0001))
    mempool_cfg = cfg.get("mempool", {})
    external_api_cfg = cfg.get("external_api", {})

    mempool_scanner = None
    if mempool_cfg.get("enabled", False):
        mempool_scanner = MempoolScanner(rpc, logger, max_scan=mempool_cfg.get("max_scan", 100))

    ticker_watcher = None
    ticker_cfg = external_api_cfg.get("ticker") if external_api_cfg else None
    if ticker_cfg:
        ticker_watcher = ExternalTickerWatcher(ticker_cfg, logger)

    return MintEngine(
        rpc,
        logger,
        default_fee=fee_default,
        retry_attempts=bot_cfg.get("retry", 3),
        fee_dynamic=bot_cfg.get("fee_dynamic", True),
        rate_limit_seconds=bot_cfg.get("rate_limit_seconds"),
        external_fee_api=external_api_cfg.get("fee") if external_api_cfg else None,
        mempool_scanner=mempool_scanner,
        ticker_watcher=ticker_watcher,
    )


def run_mint_cycle(engine: MintEngine, selector: WalletSelector, targets: List[MintTarget], min_conf: int, logger) -> None:
    for target in targets:
        for _ in range(target.batch):
            wallet = selector.pick(min_conf)
            try:
                utxo = wallet.select_largest_utxo(min_conf)
            except Exception as exc:  # noqa: BLE001
                logger.error("UTXO selection failed for %s: %s", wallet.label, exc)
                continue
            try:
                engine.mint(utxo, target.tick, target.amount, wallet.address)
            except Exception as exc:  # noqa: BLE001
                logger.error("Mint failed (wallet=%s tick=%s): %s", wallet.label, target.tick, exc)


def run_scheduler(bot_fn, intervals: List[int], logger) -> None:
    scheduler = Scheduler(logger)
    for idx, interval in enumerate(intervals):
        scheduler.add_interval_job(bot_fn, interval, name=f"scheduled-{idx}")
    scheduler.start()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    logger = get_logger(level=resolve_log_level(cfg))

    rpc = build_rpc(cfg, logger)
    wallets = build_wallets(cfg, rpc, logger)
    selector = WalletSelector(wallets, cfg.get("bot", {}).get("wallet_strategy", "round_robin"))
    targets = build_targets(cfg)
    engine = build_engine(cfg, rpc, logger)

    min_conf = cfg.get("bot", {}).get("min_confirmations", 1)
    bot_fn = lambda: run_mint_cycle(engine, selector, targets, min_conf, logger)

    def make_target_runner(target: MintTarget):
        return lambda t=target: run_mint_cycle(engine, selector, [t], min_conf, logger)

    target_runners = {target.tick: make_target_runner(target) for target in targets}

    manual = ManualCommand(bot_fn, logger)

    bot_cfg = cfg.get("bot", {})
    watcher_cfg = cfg.get("watcher", {})
    scheduler_cfg = bot_cfg.get("scheduler", {})

    if args.once:
        manual.run()
        return

    if args.watch or watcher_cfg.get("enabled", False):
        interval = watcher_cfg.get("interval_seconds", 10)
        scheduler = Scheduler(logger)
        for target in targets:
            runner = target_runners[target.tick]

            def make_job(t=target, run_target=runner):
                def _job() -> None:
                    if engine.can_mint(t.tick):
                        logger.info("Watcher ready for tick %s", t.tick)
                        run_target()
                return _job

            scheduler.add_interval_job(make_job(), interval, name=f"watch-{target.tick}")
        scheduler.start()
        return

    if args.schedule or scheduler_cfg.get("enabled", False):
        intervals = scheduler_cfg.get("intervals", [bot_cfg.get("interval_seconds", 60)])
        run_scheduler(bot_fn, intervals, logger)
        return

    if args.loop or bot_cfg.get("auto_loop", False):
        interval = bot_cfg.get("interval_seconds", 20)
        run_auto_loop(bot_fn, interval, logger)
        return

    manual.run()


if __name__ == "__main__":
    main()
