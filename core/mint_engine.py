"""Mint engine handling inscription construction, fees and retries."""
from __future__ import annotations

import binascii
import json
import time
from dataclasses import dataclass
from typing import Dict, Optional

import requests
from bitcoin.core import (
    COIN,
    CMutableTransaction,
    CMutableTxIn,
    CMutableTxOut,
    COutPoint,
    lx,
)
from bitcoin.wallet import CBitcoinAddress
from tenacity import Retrying, stop_after_attempt, wait_exponential

from .inscription import build_inscription_script
from .wallet import UTXO


@dataclass
class MintTarget:
    tick: str
    amount: int
    batch: int


class FeeEstimator:
    def __init__(
        self,
        rpc,
        logger,
        default_fee: float,
        dynamic: bool = True,
        tx_size_bytes: int = 400,
        external_fee_api: Optional[Dict[str, str]] = None,
    ) -> None:
        self.rpc = rpc
        self.logger = logger
        self.default_fee = default_fee
        self.dynamic = dynamic
        self.tx_size_bytes = tx_size_bytes
        self.external_fee_api = external_fee_api or {}

    def _estimate_from_rpc(self, target_blocks: int = 2) -> Optional[float]:
        try:
            result = self.rpc.call("estimatesmartfee", [target_blocks])
            feerate = result.get("feerate") if isinstance(result, dict) else None
            if feerate:
                return float(feerate) * (self.tx_size_bytes / 1000.0)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("RPC fee estimation failed: %s", exc)
        return None

    def _estimate_from_api(self) -> Optional[float]:
        url = self.external_fee_api.get("url")
        if not url:
            return None
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            fee_value = data.get(self.external_fee_api.get("field", "fee"))
            if fee_value:
                return float(fee_value)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("External fee API failed: %s", exc)
        return None

    def estimate(self) -> float:
        if not self.dynamic:
            return self.default_fee

        fee_sources = (
            self._estimate_from_rpc,
            self._estimate_from_api,
            lambda: self.default_fee,
        )
        for source in fee_sources:
            fee = source()
            if fee:
                self.logger.debug("Selected fee %.8f from %s", fee, source.__name__)
                return fee
        return self.default_fee


class MempoolScanner:
    def __init__(self, rpc, logger, max_scan: int = 100) -> None:
        self.rpc = rpc
        self.logger = logger
        self.max_scan = max_scan

    def contains_tick(self, tick: str) -> bool:
        try:
            txids = self.rpc.call("getrawmempool")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Mempool scan failed: %s", exc)
            return False

        for txid in txids[: self.max_scan]:
            try:
                raw = self.rpc.call("getrawtransaction", [txid])
                if tick.lower().encode() in bytes.fromhex(raw.lower()):
                    self.logger.info("Tick %s already in mempool via %s", tick, txid)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False


class ExternalTickerWatcher:
    def __init__(self, api_cfg: Optional[Dict[str, str]], logger) -> None:
        self.api_cfg = api_cfg or {}
        self.logger = logger

    def is_tick_live(self, tick: str) -> bool:
        url = self.api_cfg.get("url")
        if not url:
            return True
        params = {"tick": tick}
        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            return bool(data.get("live", True))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Ticker API unavailable: %s", exc)
            return True


class MintEngine:
    def __init__(
        self,
        rpc,
        logger,
        default_fee: float,
        retry_attempts: int,
        fee_dynamic: bool = True,
        rate_limit_seconds: Optional[float] = None,
        external_fee_api: Optional[Dict[str, str]] = None,
        mempool_scanner: Optional[MempoolScanner] = None,
        ticker_watcher: Optional[ExternalTickerWatcher] = None,
    ) -> None:
        self.rpc = rpc
        self.logger = logger
        self.rate_limit_seconds = rate_limit_seconds
        self.fee_estimator = FeeEstimator(
            rpc,
            logger,
            default_fee,
            dynamic=fee_dynamic,
            external_fee_api=external_fee_api,
        )
        self.retryer = Retrying(
            stop=stop_after_attempt(max(1, retry_attempts)),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            reraise=True,
        )
        self.mempool_scanner = mempool_scanner
        self.ticker_watcher = ticker_watcher
        self._last_mint_ts = 0.0

    def _respect_rate_limit(self) -> None:
        if not self.rate_limit_seconds:
            return
        elapsed = time.time() - self._last_mint_ts
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_mint_ts = time.time()

    def _should_proceed(self, tick: str) -> bool:
        if self.ticker_watcher and not self.ticker_watcher.is_tick_live(tick):
            self.logger.debug("Ticker %s not yet live per API", tick)
            return False
        if self.mempool_scanner and self.mempool_scanner.contains_tick(tick):
            self.logger.info("Ticker %s already in mempool, skipping to avoid duplicates", tick)
            return False
        return True

    def can_mint(self, tick: str) -> bool:
        """Public helper used by watchers to check gating conditions."""
        return self._should_proceed(tick)

    def _build_transaction(self, utxo: UTXO, dest_address: str, inscription_json: str, fee: float):
        txid = lx(utxo.txid)
        vout = utxo.vout
        send_val = utxo.amount - fee
        if send_val <= 0:
            raise RuntimeError("Selected UTXO does not cover fee")

        txin = CMutableTxIn(COutPoint(txid, vout))
        txin.scriptSig = build_inscription_script(inscription_json)
        txout = CMutableTxOut(int(send_val * COIN), CBitcoinAddress(dest_address).to_scriptPubKey())
        tx = CMutableTransaction([txin], [txout])
        return tx

    def mint(self, utxo: UTXO, tick: str, amount: int, dest_address: str) -> str:
        inscription_json = {
            "p": "zrc-20",
            "op": "mint",
            "tick": tick,
            "amt": str(amount),
        }
        if not self._should_proceed(tick):
            raise RuntimeError(f"Tick {tick} gated by watcher")

        fee = self.fee_estimator.estimate()
        self.logger.info(
            "Minting tick=%s amount=%s via UTXO %s:%s fee=%f",
            tick,
            amount,
            utxo.txid,
            utxo.vout,
            fee,
        )

        def _execute() -> str:
            tx = self._build_transaction(utxo, dest_address, json.dumps(inscription_json, separators=(",", ":")), fee)
            raw_hex = binascii.hexlify(tx.serialize()).decode()
            signed = self.rpc.call("signrawtransaction", [raw_hex])
            final_hex = signed.get("hex", raw_hex)
            txid_broadcast = self.rpc.call("sendrawtransaction", [final_hex])
            self.logger.info("Broadcasted %s", txid_broadcast)
            return txid_broadcast

        last_error: Optional[Exception] = None
        for attempt in self.retryer:
            with attempt:
                try:
                    self._respect_rate_limit()
                    return _execute()
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    self.logger.error("Mint attempt failed: %s", exc)
                    raise
        if last_error:
            raise last_error
        raise RuntimeError("Mint attempts exhausted")
