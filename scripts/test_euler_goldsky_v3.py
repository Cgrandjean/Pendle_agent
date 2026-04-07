"""Test Euler V2 Goldsky subgraph — query vaults with borrow/supply data."""

import json
import urllib.request

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

EULER_GOLDSKY = "https://api.goldsky.com/api/public/project_cm4iagnemt1wp01xn4gh1agft/subgraphs/euler-v2-mainnet/latest/gn"


def gql(query: str) -> dict:
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(EULER_GOLDSKY, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


# ═══════════════════════════════════════════════════════════════════════
# 1. Query eulerVaults with state (borrowApy, supplyApy, etc.)
# ═══════════════════════════════════════════════════════════════════════
print("=== Euler Vaults with state ===")
result = gql("""
{
  eulerVaults(first: 50, orderBy: blockNumber, orderDirection: desc) {
    id
    name
    symbol
    asset
    decimals
    borrowCap
    supplyCap
    evault
    collaterals
    state {
      totalShares
      totalBorrows
      cash
      interestRate
      supplyApy
      borrowApy
      timestamp
    }
  }
}
""")

if "errors" in result:
    err = result["errors"][0].get("message", "")[:500]
    print(f"  Error: {err}")
else:
    vaults = result.get("data", {}).get("eulerVaults", [])
    print(f"  Got {len(vaults)} vaults\n")
    
    # Show all vaults with meaningful borrows
    active_vaults = []
    for v in vaults:
        state = v.get("state") or {}
        total_borrows = int(state.get("totalBorrows") or 0)
        cash = int(state.get("cash") or 0)
        borrow_apy = int(state.get("borrowApy") or 0)
        supply_apy = int(state.get("supplyApy") or 0)
        decimals = int(v.get("decimals") or 18)
        
        # Convert from raw to human-readable
        total_borrows_human = total_borrows / (10 ** decimals) if decimals else total_borrows
        cash_human = cash / (10 ** decimals) if decimals else cash
        
        # APY is likely in 1e27 (ray) format or similar
        # Let's check the raw values first
        
        collaterals = v.get("collaterals") or []
        name = v.get("name", "")
        symbol = v.get("symbol", "")
        asset = v.get("asset", "")
        
        if total_borrows > 0 or cash > 1000:
            active_vaults.append(v)
            print(
                f"  {symbol} ({name}) | Asset: {asset[:14]}... | "
                f"Borrows: {total_borrows} (raw) | Cash: {cash} (raw) | "
                f"BorrowAPY: {borrow_apy} | SupplyAPY: {supply_apy} | "
                f"Collaterals: {len(collaterals)} | Decimals: {decimals}"
            )
    
    print(f"\n  Active vaults (borrows>0 or cash>1000): {len(active_vaults)}")
    
    # Check APY format — show a few raw values
    print("\n  === APY Format Analysis ===")
    for v in active_vaults[:5]:
        state = v.get("state") or {}
        borrow_apy_raw = int(state.get("borrowApy") or 0)
        supply_apy_raw = int(state.get("supplyApy") or 0)
        interest_rate_raw = int(state.get("interestRate") or 0)
        
        # Try different scaling factors
        # 1e27 (ray) is common in DeFi
        borrow_apy_pct = borrow_apy_raw / 1e27 * 100 if borrow_apy_raw > 1e20 else borrow_apy_raw / 1e18 * 100 if borrow_apy_raw > 1e14 else borrow_apy_raw
        supply_apy_pct = supply_apy_raw / 1e27 * 100 if supply_apy_raw > 1e20 else supply_apy_raw / 1e18 * 100 if supply_apy_raw > 1e14 else supply_apy_raw
        
        print(
            f"    {v['symbol']}: BorrowAPY raw={borrow_apy_raw} → {borrow_apy_pct:.4f}% | "
            f"SupplyAPY raw={supply_apy_raw} → {supply_apy_pct:.4f}% | "
            f"InterestRate raw={interest_rate_raw}"
        )

# ═══════════════════════════════════════════════════════════════════════
# 2. Check collaterals structure
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Collaterals structure ===")
# Introspect the collateral type
result = gql("""
{
  __type(name: "EulerVault") {
    fields {
      name
      type { 
        name kind 
        ofType { 
          name kind 
          fields { name type { name kind } }
        } 
      }
    }
  }
}
""")
t = result.get("data", {}).get("__type")
if t:
    for f in t["fields"]:
        if f["name"] == "collaterals":
            print(f"  collaterals type: {json.dumps(f['type'], indent=2)[:500]}")

# ═══════════════════════════════════════════════════════════════════════
# 3. Search for PT tokens in vault names/symbols
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Search for PT tokens ===")
# Get ALL vaults and filter client-side
result = gql("""
{
  eulerVaults(first: 1000) {
    id
    name
    symbol
    asset
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

if "errors" in result:
    print(f"  Error: {result['errors'][0].get('message', '')[:300]}")
else:
    vaults = result.get("data", {}).get("eulerVaults", [])
    print(f"  Total vaults: {len(vaults)}")
    
    # Search for PT in names
    pt_vaults = [v for v in vaults if "PT" in (v.get("name") or "").upper() or "PT" in (v.get("symbol") or "").upper()]
    print(f"  PT vaults (name/symbol contains 'PT'): {len(pt_vaults)}")
    for v in pt_vaults[:10]:
        state = v.get("state") or {}
        print(f"    {v['symbol']} | {v['name']} | Asset: {v['asset'][:14]}... | "
              f"Borrows: {state.get('totalBorrows', 0)} | Cash: {state.get('cash', 0)}")
    
    # Search for stablecoin vaults (these are where you borrow)
    stable_keywords = ["usdc", "usdt", "dai", "usde", "pyusd", "gho", "frax"]
    stable_vaults = [
        v for v in vaults 
        if any(kw in (v.get("name") or "").lower() or kw in (v.get("symbol") or "").lower() 
               for kw in stable_keywords)
        and int((v.get("state") or {}).get("cash") or 0) > 0
    ]
    print(f"\n  Stablecoin vaults with cash: {len(stable_vaults)}")
    for v in stable_vaults[:15]:
        state = v.get("state") or {}
        borrows = int(state.get("totalBorrows") or 0)
        cash = int(state.get("cash") or 0)
        borrow_apy_raw = int(state.get("borrowApy") or 0)
        # Scale APY
        if borrow_apy_raw > 1e20:
            borrow_apy_pct = borrow_apy_raw / 1e27 * 100
        elif borrow_apy_raw > 1e14:
            borrow_apy_pct = borrow_apy_raw / 1e18 * 100
        else:
            borrow_apy_pct = borrow_apy_raw
        
        collaterals = v.get("collaterals") or []
        print(
            f"    {v['symbol']} ({v['name']}) | Asset: {v['asset'][:14]}... | "
            f"BorrowAPY: {borrow_apy_pct:.2f}% | Borrows: {borrows} | Cash: {cash} | "
            f"Collaterals: {len(collaterals)}"
        )

# ═══════════════════════════════════════════════════════════════════════
# 4. Check if PT tokens appear as collaterals
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Check collaterals for PT tokens ===")
for v in stable_vaults[:5]:
    collaterals = v.get("collaterals") or []
    if collaterals:
        print(f"\n  {v['symbol']} collaterals:")
        for c in collaterals[:10]:
            print(f"    {c}")

print("\n=== Euler Goldsky v3 test complete ===")