"""Fetch Morpho Blue lending data for PT-stable markets (multi-chain)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from utils.parsing import is_pt_not_expired, is_pt_stablecoin

logger = logging.getLogger(__name__)

MORPHO_GQL = "https://blue-api.morpho.org/graphql"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

# Morpho chains that have PT markets
MORPHO_CHAIN_IDS = [1, 8453, 42161]


async def _gql(client: httpx.AsyncClient, query: str) -> dict:
    response = await client.post(MORPHO_GQL, json={"query": query}, timeout=30.0)
    response.raise_for_status()
    return response.json()


async def fetch_morpho_data(
    chain_ids: list[int] | None = None,
    min_supply_usd: float = 5000,
) -> dict[str, Any]:
    """Fetch PT markets from Morpho Blue across multiple chains (async).

    Args:
        chain_ids: List of chain IDs to query. Defaults to all Morpho chains with PT markets.
        min_supply_usd: Minimum supply in USD to include a market.

    Returns:
        {
            "pt_markets": [
                {collateral_symbol, collateral_address, loan_symbol, lltv, borrow_apy, supply_usd, liquidity_usd, chain_id},
                ...
            ]
        }
    """
    if chain_ids is None:
        chain_ids = MORPHO_CHAIN_IDS

    all_markets: list[dict] = []

    async with httpx.AsyncClient(headers=HEADERS) as client:
        for chain_id in chain_ids:
            try:
                result = await _gql(client, f"""
                {{
                  markets(first: 100, where: {{ search: "PT", chainId_in: [{chain_id}] }}) {{
                    items {{
                      uniqueKey
                      collateralAsset {{ symbol address }}
                      loanAsset {{ symbol address }}
                      lltv
                      state {{
                        borrowApy
                        supplyApy
                        supplyAssetsUsd
                        borrowAssetsUsd
                        liquidityAssetsUsd
                        utilization
                      }}
                    }}
                  }}
                }}
                """)
            except Exception as e:
                logger.error("Morpho chain %d fetch error: %s", chain_id, e)
                continue

            items = result.get("data", {}).get("markets", {}).get("items", [])
            for m in items:
                col = m.get("collateralAsset") or {}
                loan = m.get("loanAsset") or {}
                state = m.get("state") or {}
                lltv = int(m.get("lltv") or 0) / 1e18 if m.get("lltv") else 0
                supply_usd = float(state.get("supplyAssetsUsd") or 0)
                liquidity_usd = float(state.get("liquidityAssetsUsd") or 0)
                borrow_apy = float(state.get("borrowApy") or 0)

                col_symbol = col.get("symbol", "")
                if supply_usd > min_supply_usd and is_pt_not_expired(col_symbol) and is_pt_stablecoin(col_symbol):
                    all_markets.append({
                        "unique_key": m.get("uniqueKey", ""),
                        "collateral_symbol": col.get("symbol", ""),
                        "collateral_address": (col.get("address") or "").lower(),
                        "loan_symbol": loan.get("symbol", ""),
                        "loan_address": (loan.get("address") or "").lower(),
                        "lltv": lltv,
                        "borrow_apy": borrow_apy,
                        "supply_usd": supply_usd,
                        "liquidity_usd": liquidity_usd,
                        "utilization": float(state.get("utilization") or 0),
                        "chain_id": chain_id,
                    })

    logger.info("Morpho: %d PT markets across %d chains", len(all_markets), len(chain_ids))
    return {"pt_markets": all_markets}
