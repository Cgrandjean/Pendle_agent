"""Fetch Morpho Blue lending data for PT-stable markets."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from utils.parsing import is_pt_not_expired

logger = logging.getLogger(__name__)

MORPHO_GQL = "https://blue-api.morpho.org/graphql"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _gql(query: str) -> dict:
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(MORPHO_GQL, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def fetch_morpho_data(min_supply_usd: float = 5000) -> dict[str, Any]:
    """Fetch PT markets from Morpho Blue.

    Returns:
        {
            "pt_markets": [
                {collateral_symbol, collateral_address, loan_symbol, lltv, borrow_apy, supply_usd, liquidity_usd},
                ...
            ]
        }
    """
    pt_markets: list[dict] = []

    try:
        result = _gql("""
        {
          markets(first: 100, where: { search: "PT" }) {
            items {
              uniqueKey
              collateralAsset { symbol address }
              loanAsset { symbol address }
              lltv
              state {
                borrowApy
                supplyApy
                supplyAssetsUsd
                borrowAssetsUsd
                liquidityAssetsUsd
                utilization
              }
            }
          }
        }
        """)

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
            if supply_usd > min_supply_usd and is_pt_not_expired(col_symbol):
                pt_markets.append({
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
                })

    except Exception as e:
        logger.error("Morpho fetch error: %s", e)

    logger.info("Morpho: %d PT markets (supply > $%.0f)", len(pt_markets), min_supply_usd)
    return {"pt_markets": pt_markets}