"""Unified skim v2 — AAVE + Morpho + Euler with correct API queries.

Fetches PT-stable data from all 3 lending protocols to find loop opportunities.
"""

import json
import urllib.request

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def fetch_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


# ═══════════════════════════════════════════════════════════════════════
# STEP 1: Fetch PT-stable markets from Pendle
# ═══════════════════════════════════════════════════════════════════════
print("=" * 80)
print("STEP 1: Fetch PT-stable markets from Pendle")
print("=" * 80)

PENDLE_API = "https://api-v2.pendle.finance/core/v1"
STABLE_KEYWORDS = ["usdc", "usdt", "dai", "usde", "susde", "gho", "frax", "lusd", "pyusd", "usd0", "usdtb"]

pendle_pt_markets = []
try:
    data = fetch_json(f"{PENDLE_API}/1/markets?order_by=name%3A1&skip=0&limit=500")
    all_markets = data.get("results", [])
    print(f"  Total Pendle markets on Ethereum: {len(all_markets)}")

    for m in all_markets:
        pt = m.get("pt", {})
        pt_symbol = (pt.get("symbol") or "").lower()
        name = (m.get("proSymbol") or m.get("symbol") or "").lower()
        
        # Check if PT has a stable underlying
        is_stable = any(kw in pt_symbol or kw in name for kw in STABLE_KEYWORDS)
        if is_stable and pt.get("address"):
            implied_apy = float(m.get("impliedApy") or 0)
            liquidity = m.get("liquidity", {})
            tvl = float(liquidity.get("usd", 0)) if isinstance(liquidity, dict) else 0
            
            pendle_pt_markets.append({
                "name": pt.get("symbol", ""),
                "pt_address": pt.get("address", "").lower(),
                "expiry": m.get("expiry", ""),
                "implied_apy": implied_apy,
                "tvl": tvl,
                "pro_symbol": m.get("proSymbol", ""),
                "market_address": m.get("address", ""),
            })

    print(f"  PT-stable markets: {len(pendle_pt_markets)}")
    # Show top ones by TVL
    pendle_pt_markets.sort(key=lambda x: x["tvl"], reverse=True)
    for m in pendle_pt_markets[:15]:
        print(f"    {m['name']} | APY: {m['implied_apy']*100:.2f}% | TVL: ${m['tvl']:,.0f} | PT: {m['pt_address'][:16]}...")

except Exception as e:
    print(f"  Error: {e}")
    import traceback; traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# STEP 2: Skim AAVE V3 — correct PercentValue fields
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 2: Skim AAVE V3 for PT tokens")
print("=" * 80)

AAVE_GQL = "https://api.v3.aave.com/graphql"
aave_pt_data = {}
aave_stable_borrow = {}

try:
    result = post_json(AAVE_GQL, {"query": """
    {
      markets(request: { chainIds: [1] }) {
        name
        reserves {
          underlyingToken { symbol address }
          isFrozen
          isPaused
          supplyInfo {
            canBeCollateral
            maxLTV { value }
            liquidationThreshold { value }
            liquidationBonus { value }
          }
          borrowInfo {
            apy { value }
            availableLiquidity { amount { value } usd }
            borrowingState
          }
        }
      }
    }
    """})

    if "errors" in result:
        err = result["errors"][0].get("message", "")[:300]
        print(f"  Query error: {err}")
        # Fallback to minimal
        result = post_json(AAVE_GQL, {"query": """
        {
          markets(request: { chainIds: [1] }) {
            name
            reserves {
              underlyingToken { symbol address }
              isFrozen
              isPaused
            }
          }
        }
        """})

    if "errors" not in result:
        markets = result.get("data", {}).get("markets", [])
        print(f"  Got {len(markets)} AAVE markets")

        for market in markets:
            market_name = market.get("name", "")
            for r in market.get("reserves", []):
                sym = (r.get("underlyingToken", {}).get("symbol") or "").upper()
                addr = (r.get("underlyingToken", {}).get("address") or "").lower()
                si = r.get("supplyInfo") or {}
                bi = r.get("borrowInfo") or {}

                if "PT" in sym:
                    ltv_obj = si.get("maxLTV") or {}
                    ltv = float(ltv_obj.get("value") or 0) if isinstance(ltv_obj, dict) else 0
                    liq_obj = si.get("liquidationThreshold") or {}
                    liq_threshold = float(liq_obj.get("value") or 0) if isinstance(liq_obj, dict) else 0

                    aave_pt_data[addr] = {
                        "symbol": sym, "address": addr, "market": market_name,
                        "can_be_collateral": si.get("canBeCollateral"),
                        "ltv": ltv, "liquidation_threshold": liq_threshold,
                        "is_frozen": r.get("isFrozen"), "is_paused": r.get("isPaused"),
                    }

                if sym in ("USDC", "USDT", "DAI", "GHO", "USDE", "PYUSD"):
                    borrow_apy_obj = bi.get("apy") or {}
                    borrow_apy = float(borrow_apy_obj.get("value") or 0) if isinstance(borrow_apy_obj, dict) else 0
                    avail_obj = bi.get("availableLiquidity") or {}
                    avail_usd = float(avail_obj.get("usd") or 0) if isinstance(avail_obj, dict) else 0

                    # Keep the best (most liquid) market per symbol
                    if sym not in aave_stable_borrow or avail_usd > float(aave_stable_borrow[sym].get("available_liquidity_usd") or 0):
                        aave_stable_borrow[sym] = {
                            "symbol": sym, "market": market_name,
                            "borrow_apy": borrow_apy, "available_liquidity_usd": avail_usd,
                            "borrowing_state": bi.get("borrowingState", ""),
                        }

        print(f"\n  PT tokens on AAVE: {len(aave_pt_data)}")
        for addr, pt in aave_pt_data.items():
            print(f"    {pt['symbol']} | LTV: {pt['ltv']} | LiqTh: {pt['liquidation_threshold']} | Collateral: {pt['can_be_collateral']} | Frozen: {pt['is_frozen']}")

        print(f"\n  Stablecoin borrow rates on AAVE:")
        for sym, d in aave_stable_borrow.items():
            print(f"    {d['symbol']} | BorrowAPY: {d['borrow_apy']} | Liquidity: ${d['available_liquidity_usd']:,.0f} | State: {d['borrowing_state']}")

except Exception as e:
    print(f"  AAVE error: {e}")
    import traceback; traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# STEP 3: Skim Morpho Blue
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 3: Skim Morpho Blue for PT markets")
print("=" * 80)

MORPHO_GQL = "https://blue-api.morpho.org/graphql"
morpho_pt_markets = []

try:
    result = post_json(MORPHO_GQL, {"query": """
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
    """})

    items = result.get("data", {}).get("markets", {}).get("items", [])
    print(f"  Found {len(items)} PT markets on Morpho")

    for m in items:
        col = m.get("collateralAsset") or {}
        loan = m.get("loanAsset") or {}
        state = m.get("state") or {}
        lltv = int(m.get("lltv") or 0) / 1e18 if m.get("lltv") else 0
        supply_usd = float(state.get("supplyAssetsUsd") or 0)
        liquidity_usd = float(state.get("liquidityAssetsUsd") or 0)
        borrow_apy = float(state.get("borrowApy") or 0)

        if supply_usd > 5000:
            morpho_pt_markets.append({
                "collateral_symbol": col.get("symbol", ""),
                "collateral_address": (col.get("address") or "").lower(),
                "loan_symbol": loan.get("symbol", ""),
                "lltv": lltv,
                "borrow_apy": borrow_apy,
                "supply_usd": supply_usd,
                "liquidity_usd": liquidity_usd,
            })
            print(f"    {col.get('symbol','?')} / {loan.get('symbol','?')} | LLTV: {lltv:.2%} | Borrow: {borrow_apy*100:.2f}% | Supply: ${supply_usd:,.0f} | Liq: ${liquidity_usd:,.0f}")

except Exception as e:
    print(f"  Morpho error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# STEP 4: Skim Euler V2 via Goldsky subgraph
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 4: Skim Euler V2 (Goldsky subgraph)")
print("=" * 80)

EULER_GOLDSKY = "https://api.goldsky.com/api/public/project_cm4iagnemt1wp01xn4gh1agft/subgraphs/euler-v2-mainnet/latest/gn"
euler_pt_vaults = []
euler_stable_vaults = []

try:
    result = post_json(EULER_GOLDSKY, {"query": """
    {
      eulerVaults(first: 1000) {
        id
        name
        symbol
        asset
        decimals
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
    """})

    if "errors" in result:
        print(f"  Error: {result['errors'][0].get('message', '')[:300]}")
    else:
        vaults = result.get("data", {}).get("eulerVaults", [])
        print(f"  Total Euler vaults: {len(vaults)}")

        for v in vaults:
            name = v.get("name", "")
            symbol = v.get("symbol", "")
            state = v.get("state") or {}
            decimals = int(v.get("decimals") or 18)
            borrow_apy_raw = int(state.get("borrowApy") or 0)
            cash_raw = int(state.get("cash") or 0)
            borrows_raw = int(state.get("totalBorrows") or 0)
            collaterals = v.get("collaterals") or []

            # Convert APY from ray (1e27) to percentage
            borrow_apy_pct = borrow_apy_raw / 1e27 * 100 if borrow_apy_raw > 1e20 else borrow_apy_raw / 1e18 * 100 if borrow_apy_raw > 1e14 else 0
            
            # Convert amounts from raw
            cash_human = cash_raw / (10 ** decimals)
            borrows_human = borrows_raw / (10 ** decimals)

            # PT vaults
            if "PT" in symbol.upper():
                euler_pt_vaults.append({
                    "symbol": symbol, "name": name,
                    "asset": v.get("asset", ""),
                    "cash": cash_human, "borrows": borrows_human,
                    "borrow_apy_pct": borrow_apy_pct,
                    "collaterals": collaterals,
                })

            # Stablecoin vaults (potential borrow sources)
            stable_kw = ["usdc", "usdt", "dai", "usde", "pyusd", "gho"]
            if any(kw in symbol.lower() for kw in stable_kw) and (cash_human > 100 or borrows_human > 100):
                euler_stable_vaults.append({
                    "symbol": symbol, "name": name,
                    "asset": v.get("asset", ""),
                    "cash": cash_human, "borrows": borrows_human,
                    "borrow_apy_pct": borrow_apy_pct,
                    "collaterals_count": len(collaterals),
                    "collaterals": collaterals,
                })

        print(f"\n  PT vaults on Euler: {len(euler_pt_vaults)}")
        for v in euler_pt_vaults[:15]:
            print(f"    {v['symbol']} | Cash: {v['cash']:.2f} | Borrows: {v['borrows']:.2f} | BorrowAPY: {v['borrow_apy_pct']:.2f}%")

        print(f"\n  Stablecoin vaults on Euler (cash/borrows > 100): {len(euler_stable_vaults)}")
        euler_stable_vaults.sort(key=lambda x: x["cash"] + x["borrows"], reverse=True)
        for v in euler_stable_vaults[:15]:
            print(f"    {v['symbol']} ({v['name']}) | BorrowAPY: {v['borrow_apy_pct']:.2f}% | Cash: {v['cash']:,.0f} | Borrows: {v['borrows']:,.0f} | Collaterals: {v['collaterals_count']}")

except Exception as e:
    print(f"  Euler error: {e}")
    import traceback; traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# STEP 5: Cross-reference — Loop Opportunities Summary
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 5: Cross-reference — Loop Opportunities")
print("=" * 80)

# Build PT address set from Pendle
pendle_pt_addresses = {m["pt_address"] for m in pendle_pt_markets}

print(f"\n  Pendle PT-stable tokens: {len(pendle_pt_addresses)}")
print(f"  AAVE PT tokens: {len(aave_pt_data)}")
print(f"  Morpho PT markets: {len(morpho_pt_markets)}")
print(f"  Euler PT vaults: {len(euler_pt_vaults)}")

# Check cross-references
print("\n  === AAVE loops (PT as collateral → borrow stable) ===")
for addr, pt in aave_pt_data.items():
    if pt.get("can_be_collateral") and not pt.get("is_frozen"):
        for sym, borrow in aave_stable_borrow.items():
            if borrow.get("available_liquidity_usd") and float(borrow["available_liquidity_usd"]) > 10000:
                print(f"    {pt['symbol']} → Borrow {sym} | LTV: {pt['ltv']} | BorrowAPY: {borrow['borrow_apy']} | Liq: ${float(borrow['available_liquidity_usd']):,.0f}")

print("\n  === Morpho loops (PT as collateral → borrow stable) ===")
for m in morpho_pt_markets:
    if m["liquidity_usd"] > 5000:
        print(f"    {m['collateral_symbol']} → Borrow {m['loan_symbol']} | LLTV: {m['lltv']:.2%} | BorrowAPY: {m['borrow_apy']*100:.2f}% | Liq: ${m['liquidity_usd']:,.0f}")

print("\n  === Euler loops (PT in collaterals of stablecoin vaults) ===")
# Check if any euler stable vault accepts PT tokens as collateral
for sv in euler_stable_vaults[:20]:
    collateral_addrs = [c.lower() for c in sv.get("collaterals", [])]
    # Check if any collateral is a PT vault
    pt_collaterals = []
    for pv in euler_pt_vaults:
        vault_id = pv.get("asset", "").lower()
        if vault_id in collateral_addrs:
            pt_collaterals.append(pv["symbol"])
    if pt_collaterals:
        print(f"    {sv['symbol']} accepts PT collateral: {pt_collaterals} | BorrowAPY: {sv['borrow_apy_pct']:.2f}% | Cash: {sv['cash']:,.0f}")

print("\n" + "=" * 80)
print("SKIM v2 COMPLETE")
print("=" * 80)