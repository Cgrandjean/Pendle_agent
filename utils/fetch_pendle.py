"""Fetch Pendle markets via REST API (async with httpx)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ALL_CHAINS = [1, 10, 56, 146, 999, 5000, 8453, 9745, 42161, 80094]
_BASE = "https://api-v2.pendle.finance/core/v1"

CATEGORY_MAP: dict[str, str] = {
    "stable": "stables",
    "eth": "eth",
    "btc": "btc",
}


async def _fetch_chain(client: httpx.AsyncClient, chain_id: int) -> list[dict]:
    """Fetch active markets for one chain, flatten details."""
    response = await client.get(f"{_BASE}/{chain_id}/markets/active?limit=1000", timeout=30.0)
    response.raise_for_status()
    data = response.json()
    return [_flatten(m, chain_id) for m in data.get("markets", [])]


def _flatten(m: dict, chain_id: int) -> dict:
    flat: dict[str, Any] = {
        "address": m.get("address", ""),
        "chainId": chain_id,
        "name": m.get("name", ""),
        "symbol": m.get("name", ""),
        "expiry": m.get("expiry"),
        "pt": m.get("pt", ""),
        "yt": m.get("yt", ""),
        "sy": m.get("sy", ""),
        "underlyingAsset": m.get("underlyingAsset", ""),
        "protocol": m.get("protocol", ""),
        "isPrime": m.get("isPrime", 0),
        "categoryIds": m.get("categoryIds", []),
    }
    details = m.get("details") or {}
    for k, v in details.items():
        flat[f"details_{k}"] = v
    # REST API uses 'liquidity' — alias to 'totalTvl' for agent compatibility
    if "details_totalTvl" not in flat and "details_liquidity" in flat:
        flat["details_totalTvl"] = flat["details_liquidity"]
    # Set missing fields to 0 so agent doesn't break
    for field in ("underlyingApy", "ptDiscount", "ytFloatingApy", "swapFeeApy",
                   "tradingVolume", "voterApy", "lpRewardApy"):
        flat.setdefault(f"details_{field}", 0)
    return flat


async def fetch_all_markets(
    chain_id: int | None = None,
    category: str | None = None,
    min_tvl: float = 0,
    min_implied_apy: float = 0,
) -> list[dict]:
    """Fetch all active Pendle markets (parallel async per chain).

    Returns flattened dicts with ``details_impliedApy``, ``categoryIds``, etc.
    """
    chains = [chain_id] if chain_id else ALL_CHAINS
    all_markets: list[dict] = []

    async with httpx.AsyncClient() as client:
        tasks = [_fetch_chain(client, c) for c in chains]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("Chain %d: %s", chains[i], result)
            else:
                all_markets.extend(result)

    if category:
        cat = CATEGORY_MAP.get(category, category)
        all_markets = [m for m in all_markets if cat in m.get("categoryIds", [])]
    if min_tvl > 0:
        all_markets = [m for m in all_markets if (m.get("details_totalTvl") or 0) >= min_tvl]
    if min_implied_apy > 0:
        all_markets = [m for m in all_markets if (m.get("details_impliedApy") or 0) > min_implied_apy]

    logger.info("Pendle: %d markets (chains=%s, cat=%s)", len(all_markets), chains, category)
    return all_markets
