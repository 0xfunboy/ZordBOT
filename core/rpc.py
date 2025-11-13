"""RPC client with automatic failover, retry and rate limiting."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import requests
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed


class RPCError(Exception):
    """Raised when the RPC node returns an error."""


class RPCClient:
    def __init__(
        self,
        rpc_nodes: List[Dict[str, str]],
        logger,
        retry_attempts: int = 3,
        retry_wait_seconds: int = 1,
        timeout_seconds: int = 10,
        rate_limit_per_sec: Optional[float] = None,
    ) -> None:
        if not rpc_nodes:
            raise ValueError("At least one RPC node must be configured")
        self.nodes = rpc_nodes
        self.logger = logger
        self.index = 0
        self.timeout = timeout_seconds
        self.retry_attempts = max(1, retry_attempts)
        self.retry_wait_seconds = max(0, retry_wait_seconds)
        self.rate_limit_per_sec = rate_limit_per_sec
        self._rate_lock = threading.Lock()
        self._last_call_ts = 0.0

    def _switch_node(self) -> None:
        self.index = (self.index + 1) % len(self.nodes)
        self.logger.warning("Switching RPC to node %s", self.index)

    def _current_node(self) -> Dict[str, str]:
        return self.nodes[self.index]

    def _respect_rate_limit(self) -> None:
        if not self.rate_limit_per_sec:
            return
        min_interval = 1.0 / self.rate_limit_per_sec
        with self._rate_lock:
            now = time.time()
            elapsed = now - self._last_call_ts
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_call_ts = time.time()

    def _perform_request(self, method: str, params: Optional[List[Any]] = None) -> Any:
        node = self._current_node()
        url = node["url"]
        auth = (node.get("user"), node.get("pass")) if node.get("user") else None
        payload = {"jsonrpc": "1.0", "id": "bot", "method": method, "params": params or []}

        self._respect_rate_limit()
        response = requests.post(url, json=payload, auth=auth, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()
        if result.get("error"):
            raise RPCError(result["error"])
        return result["result"]

    def call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        attempts = Retrying(
            stop=stop_after_attempt(self.retry_attempts),
            wait=wait_fixed(self.retry_wait_seconds),
            retry=retry_if_exception_type((requests.RequestException, RPCError)),
            reraise=True,
        )

        for attempt in attempts:
            with attempt:
                try:
                    return self._perform_request(method, params)
                except Exception as exc:  # noqa: BLE001
                    self.logger.error("RPC error on %s: %s", method, exc)
                    self._switch_node()
                    raise
