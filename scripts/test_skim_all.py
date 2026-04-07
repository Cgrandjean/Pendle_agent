"""Unified skim across AAVE, Morpho, and Euler — find PT-stable loop opportunities.

This script:
1. Fetches all PT-stable markets from Pendle (via their public API)
2. For each PT, checks AAVE, Morpho, and Euler for lending conditions
3. Outputs a comparison table
"""

import json
import urllib.request
import asyncio
from concurrent.futures import ThreadPoolExecutor

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def fetch_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


# ═══════════════════════════════════════════════════════════════════════
# STEP 1: Get all PT-stable markets from Pendle
# ═══════════════════════════════════════════════════════════════════════
print("=" * 80)
print("STEP 1: Fetch PT-stable markets from Pendle")
print("=" * 80)

PENDLE_API = "https://api-v2.pendle.finance/core/v1"
STABLE_KEYWORDS = ["usdc", "usdt", "dai", "usde", "susde", "gho", "frax", "lusd", "pyusd", "usd0", "usdtb", "usd"]

try:
    # Fetch markets from Ethereum (chainId=1) 
    markets_data = fetch_json(f"{PENDLE_API}/1/markets?order_by=name%3A1&skip=0&limit=100")
    if isinstance(markets_data, dict):
        markets = markets_data.get("results", markets_data.get("data", []))
    else:
        markets = markets_data
    
    print(f"  Total Pendle markets on Ethereum: {len(markets)}")
    
    # Filter for PT-stable markets
    pt_stable_markets = []
    for m in markets:
        name = (m.get("name") or m.get("symbol") or "").lower()
        # Check if it's a PT with a stable underlying
        is_stable = any(kw in name for kw in STABLE_KEYWORDS)
        if is_stable:
            pt_stable_markets.append(m)
    
    print(f"  PT-stable markets: {len(pt_stable_markets)}")
    for m in pt_stable_markets[:15]:
        name = m.get("name") or m.get("symbol") or "N/A"
        pt_address = m.get("pt", {}).get("address", "") if isinstance(m.get("pt"), dict) else ""
        implied_apy = m.get("impliedApy") or m.get("details", {}).get("impliedApy") or 0
        tvl = m.get("liquidity", {}).get("usd", 0) if isinstance(m.get("liquidity"), dict) else m.get("totalTvl", 0)
        print(f"    {name} | PT: {pt_address[:20]}... | APY: {float(implied_apy)*100:.2f}% | TVL: ${float(tvl or 0):,.0f}")

except Exception as e:
    print(f"  Error fetching Pendle markets: {e}")
    pt_stable_markets = []

# Also try the newer API format
if not pt_stable_markets:
    print("\n  Trying alternative Pendle API format...")
    try:
        markets_data = fetch_json(f"{PENDLE_API}/1/markets/active")
        if isinstance(markets_data, dict):
            markets = markets_data.get("results", markets_data.get("data", []))
        else:
            markets = markets_data if isinstance(markets_data, list) else []
        
        print(f"  Active markets: {len(markets)}")
        if markets:
            sample = markets[0]
            print(f"  Sample keys: {list(sample.keys())[:20]}")
    except Exception as e:
        print(f"  Alt API error: {e}")

# ═══════════════════════════════════════════════════════════════════════
# STEP 2: Skim AAVE for PT tokens
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 2: Skim AAVE V3 for PT tokens")
print("=" * 80)

AAVE_GQL = "https://api.v3.aave.com/graphql"


def gql_aave(query: str) -> dict:
    return post_json(AAVE_GQL, {"query": query})


# Get all AAVE markets with PT reserves and borrow data for stables
aave_pt_data = {}
aave_stable_borrow = {}

try:
    # First get markets with reserve details using correct fields
    result = gql_aave("""
    {
      markets(request: { chainIds: [1] }) {
        name
        address
        reserves {
          underlyingToken { symbol name address decimals }
          aToken { symbol address }
          isFrozen
          isPaused
          supplyInfo {
            apy { base total }
            maxLTV { base total }
            liquidationThreshold { base total }
            liquidationBonus { base total }
            canBeCollateral
            supplyCap { amount usd }
            total { amount usd }
          }
          borrowInfo {
            apy { base total }
            total { amount usd }
            availableLiquidity { amount usd }
            borrowingState
            borrowCap { amount usd }
            utilizationRate { base total }
          }
        }
      }
    }
    """)
    
    if "errors" in result:
        err = result["errors"][0].get("message", "")[:500]
        print(f"  Detailed query error: {err}")
        
        # Fallback: try with simpler field names
        print("  Trying simplified query...")
        result = gql_aave("""
        {
          markets(request: { chainIds: [1] }) {
            name
            reserves {
              underlyingToken { symbol address }
              supplyInfo {
                canBeCollateral
                maxLTV { base }
                liquidationThreshold { base }
              }
              borrowInfo {
                apy { base }
                availableLiquidity { usd }
                borrowingState
              }
            }
          }
        }
        """)
    
    if "errors" in result:
        err = result["errors"][0].get("message", "")[:500]
        print(f"  Simplified query error: {err}")
        
        # Ultra minimal fallback
        print("  Trying ultra-minimal query...")
        result = gql_aave("""
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
        """)

    if "errors" not in result:
        markets = result.get("data", {}).get("markets", [])
        print(f"  Got {len(markets)} AAVE markets")
        
        for market in markets:
            market_name = market.get("name", "")
            reserves = market.get("reserves", [])
            
            for r in reserves:
                sym = (r.get("underlyingToken", {}).get("symbol") or "").upper()
                addr = (r.get("underlyingToken", {}).get("address") or "").lower()
                
                # Track PT tokens
                if "PT" in sym:
                    si = r.get("supplyInfo") or {}
                    bi = r.get("borrowInfo") or {}
                    ltv = si.get("maxLTV", {})
                    if isinstance(ltv, dict):
                        ltv = ltv.get("base") or ltv.get("total") or 0
                    
                    liq_threshold = si.get("liquidationThreshold", {})
                    if isinstance(liq_threshold, dict):
                        liq_threshold = liq_threshold.get("base") or liq_threshold.get("total") or 0
                    
                    aave_pt_data[addr] = {
                        "symbol": sym,
                        "address": addr,
                        "market": market_name,
                        "can_be_collateral": si.get("canBeCollateral"),
                        "ltv": ltv,
                        "liquidation_threshold": liq_threshold,
                        "is_frozen": r.get("isFrozen"),
                        "is_paused": r.get("isPaused"),
                    }
                
                # Track stablecoin borrow rates
                if sym in ("USDC", "USDT", "DAI", "GHO", "USDE", "PYUSD"):
                    bi = r.get("borrowInfo") or {}
                    borrow_apy = bi.get("apy", {})
                    if isinstance(borrow_apy, dict):
                        borrow_apy = borrow_apy.get("base") or borrow_apy.get("total") or 0
                    
                    avail_liq = bi.get("availableLiquidity", {})
                    if isinstance(avail_liq, dict):
                        avail_liq = avail_liq.get("usd") or 0
                    
                    aave_stable_borrow[sym] = {
                        "symbol": sym,
                        "market": market_name,
                        "borrow_apy": borrow_apy,
                        "available_liquidity_usd": avail_liq,
                        "borrowing_state": (bi.get("borrowingState") or ""),
                    }
        
        print(f"\n  PT tokens on AAVE: {len(aave_pt_data)}")
        for addr, pt in aave_pt_data.items():
            print(
                f"    {pt['symbol']} | Market: {pt['market']} | "
                f"Collateral: {pt['can_be_collateral']} | LTV: {pt['ltv']} | "
                f"LiqThreshold: {pt['liquidation_threshold']} | "
                f"Frozen: {pt['is_frozen']}"
            )
        
        print(f"\n  Stablecoin borrow rates on AAVE:")
        for sym, data in aave_stable_borrow.items():
            print(
                f"    {data['symbol']} | Market: {data['market']} | "
                f"Borrow APY: {data['borrow_apy']} | "
                f"Liquidity: ${float(data['available_liquidity_usd'] or 0):,.0f} | "
                f"State: {data['borrowing_state']}"
            )

except Exception as e:
    print(f"  AAVE error: {e}")
    import traceback
    traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# STEP 3: Skim Morpho for PT markets
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 3: Skim Morpho Blue for PT markets")
print("=" * 80)

MORPHO_GQL = "https://blue-api.morpho.org/graphql"


def gql_morpho(query: str) -> dict:
    return post_json(MORPHO_GQL, {"query": query})


morpho_pt_markets = []

try:
    # Search for PT markets on Morpho
    result = gql_morpho("""
    {
      markets(first: 50, where: { search: "PT" }) {
        items {
          uniqueKey
          collateralAsset { symbol address name }
          loanAsset { symbol address name }
          lltv
          state {
            borrowApy
            supplyApy
            netBorrowApy
            netSupplyApy
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
    print(f"  Found {len(items)} PT markets on Morpho")
    
    for m in items:
        col = m.get("collateralAsset", {})
        loan = m.get("loanAsset", {})
        state = m.get("state", {})
        lltv = int(m.get("lltv") or 0) / 1e18 if m.get("lltv") else 0
        supply_usd = float(state.get("supplyAssetsUsd") or 0)
        liquidity_usd = float(state.get("liquidityAssetsUsd") or 0)
        borrow_apy = float(state.get("borrowApy") or 0)
        
        # Only show markets with meaningful supply
        if supply_usd > 1000:
            market_info = {
                "unique_key": m.get("uniqueKey", ""),
                "collateral_symbol": col.get("symbol", ""),
                "collateral_address": col.get("address", ""),
                "loan_symbol": loan.get("symbol", ""),
                "loan_address": loan.get("address", ""),
                "lltv": lltv,
                "borrow_apy": borrow_apy,
                "supply_usd": supply_usd,
                "liquidity_usd": liquidity_usd,
                "utilization": float(state.get("utilization") or 0),
            }
            morpho_pt_markets.append(market_info)
            print(
                f"    {col.get('symbol', '?')} / {loan.get('symbol', '?')} | "
                f"LLTV: {lltv:.2%} | Borrow APY: {borrow_apy*100:.2f}% | "
                f"Supply: ${supply_usd:,.0f} | Liquidity: ${liquidity_usd:,.0f}"
            )
    
    # Also get specific PT-stable searches
    for search_term in ["PT-sUSDE", "PT-USDe", "PT-GHO", "PT-cUSD"]:
        result = gql_morpho(f"""
        {{
          markets(first: 20, where: {{ search: "{search_term}" }}) {{
            items {{
              uniqueKey
              collateralAsset {{ symbol address }}
              loanAsset {{ symbol address }}
              lltv
              state {{
                borrowApy
                supplyAssetsUsd
                liquidityAssetsUsd
              }}
            }}
          }}
        }}
        """)
        items = result.get("data", {}).get("markets", {}).get("items", [])
        active = [m for m in items if float(m.get("state", {}).get("supplyAssetsUsd") or 0) > 1000]
        if active:
            print(f"\n  {search_term}: {len(active)} active markets (supply > $1K)")
            for m in active:
                col = m["collateralAsset"]["symbol"]
                loan = m["loanAsset"]["symbol"]
                lltv = int(m.get("lltv") or 0) / 1e18 if m.get("lltv") else 0
                state = m.get("state", {})
                borrow_apy = float(state.get("borrowApy") or 0)
                supply_usd = float(state.get("supplyAssetsUsd") or 0)
                liq_usd = float(state.get("liquidityAssetsUsd") or 0)
                print(
                    f"      {col} / {loan} | LLTV: {lltv:.2%} | "
                    f"Borrow: {borrow_apy*100:.2f}% | Supply: ${supply_usd:,.0f} | Liq: ${liq_usd:,.0f}"
                )

except Exception as e:
    print(f"  Morpho error: {e}")
    import traceback
    traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# STEP 4: Skim Euler (via DeFiLlama — limited data)
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 4: Skim Euler (via DeFiLlama)")
print("=" * 80)

euler_pools = []

try:
    data = fetch_json("https://yields.llama.fi/pools")
    all_pools = data.get("data", [])
    
    euler_eth = [
        p for p in all_pools
        if "euler" in p.get("project", "").lower()
        and p.get("chain") == "Ethereum"
    ]
    
    print(f"  Euler Ethereum pools on DeFiLlama: {len(euler_eth)}")
    
    # Check for PT tokens
    euler_pt = [p for p in euler_eth if "PT" in (p.get("symbol") or "").upper()]
    print(f"  Euler PT pools: {len(euler_pt)}")
    
    # Show stablecoin pools (potential borrow sources)
    euler_stables = [
        p for p in euler_eth
        if any(s in (p.get("symbol") or "").upper() for s in ["USDC", "USDT", "DAI", "USDE", "PYUSD"])
        and (p.get("tvlUsd") or 0) > 500_000
    ]
    
    print(f"  Euler stablecoin pools (TVL > $500K): {len(euler_stables)}")
    for p in euler_stables:
        print(
            f"    {p.get('symbol')} | TVL: ${p.get('tvlUsd') or 0:,.0f} | "
            f"APY: {p.get('apy') or 0:.2f}% | "
            f"Borrow APY: {p.get('apyBaseBorrow') or 'N/A'} | "
            f"Meta: {p.get('poolMeta', '')}"
        )
    
    print("\n  ⚠️  Euler V2 has no public API for borrow rates.")
    print("  Need on-chain reads via EulerVaultLens contract for full data.")

except Exception as e:
    print(f"  Euler/DeFiLlama error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# STEP 5: Cross-reference — find loop opportunities
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STEP 5: Cross-reference — Loop Opportunities")
print("=" * 80)

print("\n  === PT tokens available as collateral on AAVE ===")
for addr, pt in aave_pt_data.items():
    if pt.get("can_be_collateral") and not pt.get("is_frozen"):
        # Find matching borrow for the underlying
        underlying = pt["symbol"].replace("PT-", "").split("-")[0]  # e.g. "USDe" from "PT-USDe-25SEP2025"
        
        # Check what stables can be borrowed against this PT
        for sym, borrow in aave_stable_borrow.items():
            if borrow.get("borrowing_state") and float(borrow.get("available_liquidity_usd") or 0) > 10000:
                print(
                    f"    LOOP: Deposit {pt['symbol']} → Borrow {sym} on AAVE | "
                    f"LTV: {pt['ltv']} | Borrow APY: {borrow['borrow_apy']} | "
                    f"Liquidity: ${float(borrow['available_liquidity_usd'] or 0):,.0f}"
                )

print("\n  === PT→Stable loop paths on Morpho ===")
for m in morpho_pt_markets:
    if m["supply_usd"] > 10000 and m["liquidity_usd"] > 1000:
        print(
            f"    LOOP: {m['collateral_symbol']} → Borrow {m['loan_symbol']} on Morpho | "
            f"LLTV: {m['lltv']:.2%} | Borrow APY: {m['borrow_apy']*100:.2f}% | "
            f"Liquidity: ${m['liquidity_usd']:,.0f}"
        )

print("\n" + "=" * 80)
print("SKIM COMPLETE")
print("=" * 80)