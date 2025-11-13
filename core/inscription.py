"""Helpers to build Ordinal-style inscription payloads."""
from __future__ import annotations

import json
from typing import Dict


def build_inscription_script(data_json: str) -> bytes:
    magic = b"\x03ord\x11"
    mime = b"application/json"
    null = b"\x00"
    return magic + mime + null + data_json.encode()


def build_mint_json(tick: str, amount: int) -> str:
    payload: Dict[str, str] = {
        "p": "zrc-20",
        "op": "mint",
        "tick": tick,
        "amt": str(amount),
    }
    return json.dumps(payload, separators=(",", ":"))
