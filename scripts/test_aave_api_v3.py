"""Test Aave V3 GraphQL — query with correct Reserve schema."""

import json
import urllib.request

AAVE_GQL = "https://api.v3.aave.com/graphql"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def gql(query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode()
    req = urllib.request.Request(AAVE_GQL, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


# Step 1: Introspect sub-types
print("=== Introspect sub-types ===")
for type_name in ["ReserveSupplyInfo", "ReserveBorrowInfo", "Currency", "TokenAmount", "MarketInfo", "ReserveIsolationModeConfig"]:
    result = gql(f"""
    {{
      __type(name: "{type_name}") {{
        name
        kind
        fields {{
          name
          type {{ name kind ofType {{ name kind }} }}
        }}
      }}
    }}
    """)
    t = result.get("data", {}).get("__type")
    if t:
        print(f"\n  {t['name']} ({t['kind']}):")
        for f in (t.get("fields") or []):
            ft = f["type"]
            fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
            print(f"    {f['name']}: {fname} ({ft['kind']})")

# Step 2: Query markets with correct Reserve fields
print("\n\n=== Query markets(chainIds: [1]) with correct fields ===")
result = gql("""
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
        totalSupply { amount }
        ltv
        liquidationThreshold
        liquidationBonus
        usageAsCollateralEnabled
      }
      borrowInfo {
        totalBorrow { amount }
        borrowAPY
        variableAPY
        availableLiquidity { amount }
        borrowingEnabled
      }
    }
  }
}
""")
if "errors" in result:
    err = result["errors"][0].get("message", "")[:500]
    print(f"  Error: {err}")
    
    # Try even more minimal
    print("\n  Trying minimal...")
    result = gql("""
    {
      markets(request: { chainIds: [1] }) {
        name
        address
        reserves {
          underlyingToken { symbol address }
        }
      }
    }
    """)
    if "errors" in result:
        print(f"  Error: {result['errors'][0].get('message', '')[:500]}")
    else:
        markets = result.get("data", {}).get("markets", [])
        print(f"  Got {len(markets)} markets")
        for m in markets:
            reserves = m.get("reserves", [])
            pt = [r for r in reserves if "PT" in (r.get("underlyingToken", {}).get("symbol") or "").upper()]
            print(f"    {m['name']}: {len(reserves)} reserves, {len(pt)} PT")
            for r in pt[:5]:
                print(f"      {r['underlyingToken']['symbol']} ({r['underlyingToken']['address'][:20]}...)")
else:
    markets = result.get("data", {}).get("markets", [])
    print(f"  Got {len(markets)} markets")
    for m in markets:
        reserves = m.get("reserves", [])
        pt = [r for r in reserves if "PT" in (r.get("underlyingToken", {}).get("symbol") or "").upper()]
        if pt:
            print(f"\n  Market: {m['name']}")
            for r in pt[:5]:
                sym = r["underlyingToken"]["symbol"]
                si = r.get("supplyInfo", {})
                bi = r.get("borrowInfo") or {}
                print(
                    f"    {sym} | LTV: {si.get('ltv')} | LiqThreshold: {si.get('liquidationThreshold')} | "
                    f"BorrowAPY: {bi.get('borrowAPY') or bi.get('variableAPY') or 'N/A'} | "
                    f"Collateral: {si.get('usageAsCollateralEnabled')}"
                )

        # Show stable borrow rates too
        for r in reserves:
            sym = (r.get("underlyingToken", {}).get("symbol") or "").upper()
            bi = r.get("borrowInfo") or {}
            if sym in ("USDC", "USDT", "DAI", "GHO") and bi.get("borrowingEnabled"):
                print(
                    f"    [borrow] {r['underlyingToken']['symbol']} | "
                    f"BorrowAPY: {bi.get('borrowAPY') or bi.get('variableAPY')}"
                )

print("\n=== Done ===")