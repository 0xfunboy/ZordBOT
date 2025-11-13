"""Wallet helpers for UTXO selection and balance checks."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import cycle
from typing import Dict, Iterable, List, Optional


@dataclass
class UTXO:
    txid: str
    vout: int
    amount: float
    address: str


class Wallet:
    def __init__(self, rpc, address: str, logger, label: Optional[str] = None) -> None:
        self.rpc = rpc
        self.address = address
        self.logger = logger
        self.label = label or address

    def list_utxos(self, min_conf: int = 1) -> List[UTXO]:
        params = [min_conf, 9999999, [self.address]]
        utxos = self.rpc.call("listunspent", params)
        return [
            UTXO(
                txid=u["txid"],
                vout=u["vout"],
                amount=float(u["amount"]),
                address=u.get("address", self.address),
            )
            for u in utxos
        ]

    def select_largest_utxo(self, min_conf: int = 1) -> UTXO:
        utxos = self.list_utxos(min_conf)
        if not utxos:
            raise RuntimeError(f"No spendable UTXOs for {self.label}")
        utxo = max(utxos, key=lambda u: u.amount)
        self.logger.info("Selected UTXO %s:%s for %s", utxo.txid, utxo.vout, self.label)
        return utxo

    def balance(self, min_conf: int = 1) -> float:
        return sum(u.amount for u in self.list_utxos(min_conf))


class MultiWallet:
    def __init__(self, wallets: Iterable[Wallet]) -> None:
        wallet_list = list(wallets)
        if not wallet_list:
            raise ValueError("At least one wallet must be provided")
        self.wallets = wallet_list
        self._round_robin = cycle(self.wallets)

    def next_wallet(self) -> Wallet:
        return next(self._round_robin)

    def richest_wallet(self, min_conf: int = 1) -> Wallet:
        balances = [(w, w.balance(min_conf)) for w in self.wallets]
        return max(balances, key=lambda item: item[1])[0]

    def all(self) -> List[Wallet]:
        return self.wallets
