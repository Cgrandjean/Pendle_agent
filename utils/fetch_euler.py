"""Fetch Euler V2 lending data via Goldsky subgraphs (multi-chain, parallel)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from utils.parsing import is_pt_not_expired, parse_pt

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


# Euler V2 APY is stored in RAY format (1e27)
_RAY = 1e27


def _ray_to_pct(raw: int) -> float:
    """Convert Euler APY (RAY format) to percentage."""
    if raw > 1e20:
        return raw / _RAY * 100
    return 0.0


async def _fetch_chain(client: httpx.AsyncClient, chain_id: int, subgraph: str, min_cash: float) -> tuple[list[dict], list[dict]]:
    """Fetch PT vaults and borrowable vaults for a single chain."""
    all_pt_vaults: list[dict] = []
    all_borrowable: list[dict] = []
    
    try:
        result = await _gql(client, subgraph, """
        {
          eulerVaults(first: 500) {
            id
            name
            symbol
            asset
            decimals
            evault
            dToken
            collaterals
            state {
              totalBorrows
              cash
              borrowApy
              supplyApy
            }
          }
        }
        """)
    except Exception as e:
        logger.error("Euler %s fetch error: %s", subgraph, e)
        return [], []

    if "errors" in result:
        logger.error("Euler %s query error: %s", subgraph, result["errors"][0].get("message", "")[:200])
        return [], []

    vaults = result.get("data", {}).get("eulerVaults", [])
    if not vaults:
        return [], []

    # Build lookup maps by ALL identifiers
    vault_by_id = {}
    vault_by_evault = {}
    vault_by_dtoken = {}
    vault_by_asset = {}
    vault_by_symbol_lower = {}
    
    for v in vaults:
        vid = (v.get("id") or "").lower()
        ev = (v.get("evault") or "").lower()
        dt = (v.get("dToken") or "").lower()
        asset = (v.get("asset") or "").lower()
        sym = (v.get("symbol") or "").lower()
        
        if vid: vault_by_id[vid] = v
        if ev: vault_by_evault[ev] = v
        if dt: vault_by_dtoken[dt] = v
        if asset: vault_by_asset[asset] = v
        if sym: vault_by_symbol_lower[sym] = v

    # First pass: collect all non-expired PT vaults
    chain_pt_vaults = []
    for v in vaults:
        symbol = v.get("symbol", "")
        if "PT" not in symbol.upper():
            continue
        # Filter out expired PT tokens
        if not is_pt_not_expired(symbol):
            logger.debug("Skipping expired PT vault: %s", symbol)
            continue
            
        state = v.get("state") or {}
        decimals = int(v.get("decimals") or 18)
        borrow_apy_raw = int(state.get("borrowApy") or 0)
        cash_raw = int(state.get("cash") or 0)
        borrows_raw = int(state.get("totalBorrows") or 0)

        pt_vault = {
            "symbol": symbol,
            "name": v.get("name", ""),
            "asset": v.get("asset", ""),
            "evault": v.get("evault", ""),
            "dToken": v.get("dToken", ""),
            "decimals": decimals,
            "cash": cash_raw / (10 ** decimals),
            "borrows": borrows_raw / (10 ** decimals),
            "borrow_apy_pct": _ray_to_pct(borrow_apy_raw),
            "chain_id": chain_id,
        }
        chain_pt_vaults.append(pt_vault)
        all_pt_vaults.append(pt_vault)

    # Build PT lookup by evault, dToken, asset (all identifiers)
    pt_by_evault = {pv["evault"].lower(): pv for pv in chain_pt_vaults if pv["evault"]}
    pt_by_dtoken = {pv["dToken"].lower(): pv for pv in chain_pt_vaults if pv["dToken"]}
    pt_by_asset = {pv["asset"].lower(): pv for pv in chain_pt_vaults if pv["asset"]}

    # Second pass: collect ALL borrowable vaults that have PT as collateral
    for v in vaults:
        state = v.get("state") or {}
        decimals = int(v.get("decimals") or 18)
        borrow_apy_raw = int(state.get("borrowApy") or 0)
        borrow_apy_pct = _ray_to_pct(borrow_apy_raw)
        cash_raw = int(state.get("cash") or 0)
        borrows_raw = int(state.get("totalBorrows") or 0)
        cash_human = cash_raw / (10 ** decimals)

        # Skip if below thresholds
        if borrow_apy_pct == 0 and cash_human < min_cash:
            continue

        collaterals = v.get("collaterals") or []
        if not collaterals:
            continue
        
        # Find PT collaterals by resolving evault OR dToken addresses
        pt_collaterals = []
        for col_addr in collaterals:
            col_lower = col_addr.lower()
            
            # Try evault match first (most common)
            pt_vault = pt_by_evault.get(col_lower)
            if pt_vault:
                pt = parse_pt(pt_vault["symbol"])
                pt_collaterals.append({
                    "symbol": pt_vault["symbol"],
                    "evault": pt_vault["evault"],
                    "dToken": pt_vault["dToken"],
                    "asset": pt_vault["asset"],
                    "match_type": "evault",
                    "pt_underlying": pt.underlying if pt else "",
                    "pt_expiry": pt.expiry_iso if pt else "",
                })
                continue
            
            # Try dToken match
            pt_vault = pt_by_dtoken.get(col_lower)
            if pt_vault:
                pt = parse_pt(pt_vault["symbol"])
                pt_collaterals.append({
                    "symbol": pt_vault["symbol"],
                    "evault": pt_vault["evault"],
                    "dToken": pt_vault["dToken"],
                    "asset": pt_vault["asset"],
                    "match_type": "dToken",
                    "pt_underlying": pt.underlying if pt else "",
                    "pt_expiry": pt.expiry_iso if pt else "",
                })
                continue
            
            # Try asset match
            pt_vault = pt_by_asset.get(col_lower)
            if pt_vault:
                pt = parse_pt(pt_vault["symbol"])
                pt_collaterals.append({
                    "symbol": pt_vault["symbol"],
                    "evault": pt_vault["evault"],
                    "dToken": pt_vault["dToken"],
                    "asset": pt_vault["asset"],
                    "match_type": "asset",
                    "pt_underlying": pt.underlying if pt else "",
                    "pt_expiry": pt.expiry_iso if pt else "",
                })
                continue
            
            # Try by looking up in all vaults (filter out expired PT tokens)
            for lookup_map in [vault_by_id, vault_by_evault, vault_by_dtoken, vault_by_asset]:
                potential = lookup_map.get(col_lower)
                if potential and "PT" in potential.get("symbol", "").upper():
                    pt_sym = potential.get("symbol", "")
                    if is_pt_not_expired(pt_sym):
                        pt = parse_pt(pt_sym)
                        pt_collaterals.append({
                            "symbol": pt_sym,
                            "evault": potential.get("evault", ""),
                            "dToken": potential.get("dToken", ""),
                            "asset": potential.get("asset", ""),
                            "match_type": "lookup",
                            "pt_underlying": pt.underlying if pt else "",
                            "pt_expiry": pt.expiry_iso if pt else "",
                        })
                    break

        # Only include if it has PT collateral
        if not pt_collaterals:
            continue

        borrowable_vault = {
            "symbol": v.get("symbol", ""),
            "name": v.get("name", ""),
            "asset": v.get("asset", ""),
            "evault": v.get("evault", ""),
            "dToken": v.get("dToken", ""),
            "decimals": decimals,
            "cash": cash_human,
            "borrows": borrows_raw / (10 ** decimals),
            "borrow_apy_pct": borrow_apy_pct,
            "collaterals": collaterals,
            "collaterals_count": len(collaterals),
            "pt_collaterals": pt_collaterals,
            "chain_id": chain_id,
        }
        all_borrowable.append(borrowable_vault)

    return all_pt_vaults, all_borrowable


async def fetch_euler_data(
    chain_ids: list[int] | None = None,
    min_borrow_apy: float = 0,
    min_cash: float = 100,
) -> dict[str, Any]:
    """Fetch PT vaults and borrowable vaults from Euler V2 across multiple chains (parallel async).

    Args:
        chain_ids: List of chain IDs to query. Defaults to all supported Euler chains.
        min_borrow_apy: Minimum borrow APY (in %) to include a vault.
        min_cash: Minimum cash (in token units) to include a vault.

    Returns:
        {
            "pt_vaults": [{symbol, name, asset, evault, dToken, cash, borrows, borrow_apy_pct, chain_id}, ...],
            "borrowable_vaults": [{symbol, name, asset, evault, cash, borrows, borrow_apy_pct, pt_collaterals, chain_id}, ...],
            "summary": {total_vaults, total_pt_vaults, total_borrowable, with_pt_collateral}
        }
    """
    if chain_ids is None:
        chain_ids = list(EULER_SUBGRAPHS.keys())

    # Build task list for parallel execution
    tasks = []
    for chain_id in chain_ids:
        subgraph = EULER_SUBGRAPHS.get(chain_id)
        if subgraph:
            tasks.append((chain_id, subgraph))

    async with httpx.AsyncClient(headers=_HEADERS) as client:
        fetch_tasks = [_fetch_chain(client, cid, sub, min_cash) for cid, sub in tasks]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    all_pt_vaults: list[dict] = []
    all_borrowable: list[dict] = []
    total_vaults = 0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Euler chain %d failed: %s", tasks[i][0], result)
        else:
            pt_vaults, borrowable = result
            all_pt_vaults.extend(pt_vaults)
            all_borrowable.extend(borrowable)
            total_vaults += len(pt_vaults) + len(borrowable)

    # Sort by borrow APY
    all_borrowable.sort(key=lambda x: x["borrow_apy_pct"], reverse=True)

    with_pt = len(all_borrowable)

    logger.info(
        "Euler: %d total vaults, %d PT vaults, %d borrowable w/PT collateral across %d chains",
        total_vaults, len(all_pt_vaults), with_pt, len(chain_ids)
    )

    return {
        "pt_vaults": all_pt_vaults,
        "borrowable_vaults": all_borrowable,
        "summary": {
            "total_vaults": total_vaults,
            "total_pt_vaults": len(all_pt_vaults),
            "total_borrowable_with_pt": with_pt,
            "chains_queried": len(chain_ids),
        }
    }