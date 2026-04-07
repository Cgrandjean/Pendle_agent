"""Fetch AAVE V3 lending data for PT tokens and stablecoin borrow rates."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from utils.parsing import is_pt_not_expired

logger = logging.getLogger(__name__)

AAVE_GQL = "https://api.v3.aave.com/graphql"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _gql(query: str) -> dict:
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(AAVE_GQL, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def fetch_aave_data(chain_ids: list[int] | None = None) -> dict[str, Any]:
    """Fetch PT collateral data and stablecoin borrow rates from AAVE V3.
    
    Args:
        chain_ids: List of chain IDs to query. Defaults to [1, 42161, 8453, 10] (ETH, Arb, Base, OP).
    
    Returns:
        {
            "pt_tokens": {address: {symbol, ltv, liquidation_threshold, can_be_collateral, ...}},
            "stable_borrow": {symbol: {borrow_apy, available_liquidity_usd, borrowing_state}},
        }
    """
    if chain_ids is None:
        chain_ids = [1, 42161, 8453, 10]

    pt_tokens: dict[str, dict] = {}
    stable_borrow: dict[str, dict] = {}

    chain_ids_str = ", ".join(str(c) for c in chain_ids)

    try:
        result = _gql(f"""
        {{
          markets(request: {{ chainIds: [{chain_ids_str}] }}) {{
            name
            reserves {{
              underlyingToken {{ symbol address }}
              isFrozen
              isPaused
              supplyInfo {{
                canBeCollateral
                maxLTV {{ value }}
                liquidationThreshold {{ value }}
                liquidationBonus {{ value }}
              }}
              borrowInfo {{
                apy {{ value }}
                availableLiquidity {{ amount {{ value }} usd }}
                borrowingState
              }}
            }}
          }}
        }}
        """)

        if "errors" in result:
            logger.warning("AAVE detailed query failed: %s", result["errors"][0].get("message", "")[:200])
            # Fallback to minimal
            result = _gql(f"""
            {{
              markets(request: {{ chainIds: [{chain_ids_str}] }}) {{
                name
                reserves {{
                  underlyingToken {{ symbol address }}
                  isFrozen
                  isPaused
                }}
              }}
            }}
            """)

        if "errors" in result:
            logger.error("AAVE minimal query also failed: %s", result["errors"][0].get("message", "")[:200])
            return {"pt_tokens": pt_tokens, "stable_borrow": stable_borrow}

        for market in result.get("data", {}).get("markets", []):
            market_name = market.get("name", "")
            for r in market.get("reserves", []):
                sym = (r.get("underlyingToken", {}).get("symbol") or "").upper()
                addr = (r.get("underlyingToken", {}).get("address") or "").lower()
                si = r.get("supplyInfo") or {}
                bi = r.get("borrowInfo") or {}

                if "PT" in sym and is_pt_not_expired(sym):
                    ltv_obj = si.get("maxLTV") or {}
                    ltv = float(ltv_obj.get("value") or 0) if isinstance(ltv_obj, dict) else 0
                    liq_obj = si.get("liquidationThreshold") or {}
                    liq_threshold = float(liq_obj.get("value") or 0) if isinstance(liq_obj, dict) else 0

                    pt_tokens[addr] = {
                        "symbol": sym,
                        "address": addr,
                        "market": market_name,
                        "can_be_collateral": si.get("canBeCollateral", False),
                        "ltv": ltv,
                        "liquidation_threshold": liq_threshold,
                        "is_frozen": r.get("isFrozen", False),
                        "is_paused": r.get("isPaused", False),
                    }

                if sym in ("USDC", "USDT", "DAI", "GHO", "USDE", "PYUSD"):
                    borrow_apy_obj = bi.get("apy") or {}
                    borrow_apy = float(borrow_apy_obj.get("value") or 0) if isinstance(borrow_apy_obj, dict) else 0
                    avail_obj = bi.get("availableLiquidity") or {}
                    avail_usd = float(avail_obj.get("usd") or 0) if isinstance(avail_obj, dict) else 0

                    if sym not in stable_borrow or avail_usd > float(stable_borrow[sym].get("available_liquidity_usd") or 0):
                        stable_borrow[sym] = {
                            "symbol": sym,
                            "market": market_name,
                            "borrow_apy": borrow_apy,
                            "available_liquidity_usd": avail_usd,
                            "borrowing_state": bi.get("borrowingState", ""),
                        }

    except Exception as e:
        logger.error("AAVE fetch error: %s", e)

    logger.info("AAVE: %d PT tokens, %d stable borrow rates", len(pt_tokens), len(stable_borrow))
    return {"pt_tokens": pt_tokens, "stable_borrow": stable_borrow}