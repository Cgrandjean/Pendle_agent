"""State schema for the Loop Scout agent."""

from dataclasses import dataclass
from typing import TypedDict


@dataclass
class PTToken:
    """Simple PT token: underlying ticker + exact expiry."""
    underlying: str      # e.g. "susde", "usdg"
    expiry_iso: str       # ISO date "2026-05-07"


class LoopScoutState(TypedDict, total=False):
    chain_filter: int | None
    chain_name: str | None
    count: int
    markets: list[dict]
    aave_data: dict
    morpho_data: dict
    euler_data: dict
    loop_candidates: list[dict]
    output: str