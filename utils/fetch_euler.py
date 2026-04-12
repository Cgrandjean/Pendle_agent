"""Fetch Euler V2 lending data via Goldsky subgraphs (multi-chain)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from utils.parsing import is_pt_not_expired, is_pt_stablecoin

logger = logging.getLogger(__name__)

_HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

# Mapping from chain ID to Goldsky subgraph name
EULER_SUBGRAPHS: dict[int, str] = {
    1: "euler-v2-mainnet",
    42161: "euler-v2-arbitrum",
    8453: "euler-v2-base",
    56: "euler-v2-bsc",
    146: "euler-v2-sonic",
    5000: "euler-v2-mantle",
    9745: "euler-v2-plasma",
    80094: "euler-v2-berachain",
}


async def _gql(client: httpx.AsyncClient, subgraph: str, query: str) -> dict:
    url = f"https://api.goldsky.com/api/public/project_cm4iagnemt1wp01xn4gh1agft/subgraphs/{subgraph}/latest/gn"
    response = await client.post(url, json={"query": query}, timeout=30.0)
    response.raise_for_status()
    return response.json()


def _ray_to_pct(raw: int) -> float:
    """Convert ray-format APY (1e27) to percentage."""
    if raw > 1e20:
        return raw / 1e27 * 100
    elif raw > 1e14:
        return raw / 1e18 * 100
    return 0.0


async def fetch_euler_data(
    chain_ids: list[int] | None = None,
    min_cash_or_borrows: float = 100,
) -> dict[str, Any]:
    """Fetch PT vaults and stablecoin vaults from Euler V2 across multiple chains (async).

    Args:
        chain_ids: List of chain IDs to query. Defaults to all supported Euler chains.
        min_cash_or_borrows: Minimum cash or borrows (in token units) to include a vault.

    Returns:
        {
            "pt_vaults": [{symbol, name, asset, cash, borrows, borrow_apy_pct, collaterals, chain_id}, ...],
            "stable_vaults": [{symbol, name, asset, cash, borrows, borrow_apy_pct, collaterals_count, collaterals, chain_id}, ...],
        }
    """
    if chain_ids is None:
        chain_ids = list(EULER_SUBGRAPHS.keys())

    pt_vaults: list[dict] = []
    stable_vaults: list[dict] = []

    stable_kw = ["usdc", "usdt", "usds", "usde", "pyusd", "gho"]

    async with httpx.AsyncClient(headers=_HEADERS) as client:
        for chain_id in chain_ids:
            subgraph = EULER_SUBGRAPHS.get(chain_id)
            if not subgraph:
                logger.warning("No Euler subgraph for chain %d", chain_id)
                continue

            try:
                result = await _gql(client, subgraph, """
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
            except Exception as e:
                logger.error("Euler %s fetch error: %s", subgraph, e)
                continue

            if "errors" in result:
                logger.error("Euler %s query error: %s", subgraph, result["errors"][0].get("message", "")[:200])
                continue

            vaults = result.get("data", {}).get("eulerVaults", [])

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

                has_collaterals = len(collaterals) > 0
                has_activity = cash_human > 1000 or borrows_human > 100

                base = {
                    "symbol": symbol,
                    "name": name,
                    "asset": v.get("asset", ""),
                    "evault": v.get("evault", ""),
                    "cash": cash_human,
                    "borrows": borrows_human,
                    "borrow_apy_pct": borrow_apy_pct,
                    "collaterals": collaterals,
                    "chain_id": chain_id,
                }

                # PT vaults: must be non-expired stablecoin PT, have collaterals, and real activity
                if "PT" in symbol.upper() and is_pt_not_expired(symbol) and is_pt_stablecoin(symbol) and has_collaterals and has_activity:
                    pt_vaults.append({**base})

                # Stablecoin vaults
                if any(kw in symbol.lower() for kw in stable_kw) and (
                    cash_human > min_cash_or_borrows or borrows_human > min_cash_or_borrows
                ):
                    stable_vaults.append({
                        **base,
                        "collaterals_count": len(collaterals),
                    })

    # Sort stable vaults by total activity
    stable_vaults.sort(key=lambda x: x["cash"] + x["borrows"], reverse=True)

    logger.info("Euler: %d PT vaults, %d stable vaults across %d chains",
                len(pt_vaults), len(stable_vaults), len(chain_ids))
    return {"pt_vaults": pt_vaults, "stable_vaults": stable_vaults}
