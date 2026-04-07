"""Fetch Euler V2 lending data via Goldsky subgraph."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from utils.parsing import is_pt_not_expired

logger = logging.getLogger(__name__)

EULER_GOLDSKY = "https://api.goldsky.com/api/public/project_cm4iagnemt1wp01xn4gh1agft/subgraphs/euler-v2-mainnet/latest/gn"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _gql(query: str) -> dict:
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(EULER_GOLDSKY, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _ray_to_pct(raw: int) -> float:
    """Convert ray-format APY (1e27) to percentage."""
    if raw > 1e20:
        return raw / 1e27 * 100
    elif raw > 1e14:
        return raw / 1e18 * 100
    return 0.0


def fetch_euler_data(min_cash_or_borrows: float = 100) -> dict[str, Any]:
    """Fetch PT vaults and stablecoin vaults from Euler V2.

    Returns:
        {
            "pt_vaults": [{symbol, name, asset, cash, borrows, borrow_apy_pct, collaterals}, ...],
            "stable_vaults": [{symbol, name, asset, cash, borrows, borrow_apy_pct, collaterals_count, collaterals}, ...],
        }
    """
    pt_vaults: list[dict] = []
    stable_vaults: list[dict] = []

    try:
        result = _gql("""
        {
          eulerVaults(first: 1000) {
            id
            name
            symbol
            asset
            decimals
            evault
            collaterals
            state {
              totalBorrows
              cash
              borrowApy
              supplyApy
              interestRate
            }
          }
        }
        """)

        if "errors" in result:
            logger.error("Euler query error: %s", result["errors"][0].get("message", "")[:200])
            return {"pt_vaults": pt_vaults, "stable_vaults": stable_vaults}

        vaults = result.get("data", {}).get("eulerVaults", [])
        logger.info("Euler: fetched %d vaults total", len(vaults))

        stable_kw = ["usdc", "usdt", "usds", "usde", "pyusd", "gho"]

        for v in vaults:
            symbol = v.get("symbol", "")
            name = v.get("name", "")
            state = v.get("state") or {}
            decimals = int(v.get("decimals") or 18)
            borrow_apy_raw = int(state.get("borrowApy") or 0)
            cash_raw = int(state.get("cash") or 0)
            borrows_raw = int(state.get("totalBorrows") or 0)
            collaterals = v.get("collaterals") or []

            borrow_apy_pct = _ray_to_pct(borrow_apy_raw)
            cash_human = cash_raw / (10 ** decimals)
            borrows_human = borrows_raw / (10 ** decimals)

            # PT vaults (only non-expired)
            if "PT" in symbol.upper() and is_pt_not_expired(symbol):
                pt_vaults.append({
                    "symbol": symbol,
                    "name": name,
                    "asset": v.get("asset", ""),
                    "evault": v.get("evault", ""),
                    "cash": cash_human,
                    "borrows": borrows_human,
                    "borrow_apy_pct": borrow_apy_pct,
                    "collaterals": collaterals,
                })

            # Stablecoin vaults
            if any(kw in symbol.lower() for kw in stable_kw) and (cash_human > min_cash_or_borrows or borrows_human > min_cash_or_borrows):
                stable_vaults.append({
                    "symbol": symbol,
                    "name": name,
                    "asset": v.get("asset", ""),
                    "cash": cash_human,
                    "borrows": borrows_human,
                    "borrow_apy_pct": borrow_apy_pct,
                    "collaterals_count": len(collaterals),
                    "collaterals": collaterals,
                })

        stable_vaults.sort(key=lambda x: x["cash"] + x["borrows"], reverse=True)

    except Exception as e:
        logger.error("Euler fetch error: %s", e)

    logger.info("Euler: %d PT vaults, %d stable vaults", len(pt_vaults), len(stable_vaults))
    return {"pt_vaults": pt_vaults, "stable_vaults": stable_vaults}