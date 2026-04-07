
"""Fix AAVE PercentValue fields and Pendle API response format."""

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
# FIX 1: Pendle API — check actual response format
# ═══════════════════════════════════════════════════════════════════════
print("=== Pendle API response format ===")
PENDLE_API = "https://api-v2.pendle.finance/core/v1"

try:
    data = fetch_json(f"{PENDLE_API}/1/markets?order_by=name%3A1&skip=0&limit=5")
    print(f"  Type: {type(data).__name__}")
    if isinstance(data, dict):
        print(f"  Keys: {list(data.keys())}")
        # Check if results are nested
        for key in data:
            val = data[key]
            if isinstance(val, list) and val:
                print(f"  [{key}] has {len(val)} items")
                sample = val[0]
                print(f"  [{key}][0] keys: {list(sample.keys())[:25]}")
                print(f"  [{key}][0] name: {sample.get('name')}")
                print(f"  [{key}][0] symbol: {sample.get('symbol')}")
                # Check PT fields
                if "pt" in sample:
                    print(f"  [{key}][0] pt: {json.dumps(sample['pt'])[:200]}")
                if "proSymbol" in sample:
                    print(f"  [{key}][0] proSymbol: {sample['proSymbol']}")
                # Print full first market
                print(f"\n  Full first market:")
                print(json.dumps(sample, indent=2)[:1500])
                break
            elif isinstance(val, (int, float, str, bool)):
                print(f"  {key}: {val}")
    elif isinstance(data, list):
        print(f"  List with {len(data)} items")
        if data:
            sample = data[0]
            print(f"  [0] keys: {list(sample.keys())[:25]}")
except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════════════════
# FIX 2: AAVE — introspect PercentValue and DecimalValue types
# ═══════════════════════════════════════════════════════════════════════
print("\n=== AAVE: Introspect PercentValue and related types ===")
AAVE_GQL = "https://api.v3.aave.com/graphql"

for type_name in ["PercentValue", "DecimalValue", "BigDecimal", "TokenAmount"]:
    try:
        result = post_json(AAVE_GQL, {"query": f"""
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
        """})
        t = result.get("data", {}).get("__type")
        if t:
            print(f"\n  {t['name']} ({t['kind']}):")
            for f in (t.get("fields") or []):
                ft = f["type"]
                fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
                print(f"    {f['name']}: {fname} ({ft['kind']})")
    except Exception as e:
        print(f"  {type_name}: Error - {e}")

# Now try a query with the correct PercentValue fields
print("\n=== AAVE: Try query with correct PercentValue fields ===")
try:
    result = post_json(AAVE_GQL, {"query": """
    {
      markets(request: { chainIds: [1] }) {
        name
        reserves {
          underlyingToken { symbol address }
          supplyInfo {
            canBeCollateral
            maxLTV { value }
            liquidationThreshold { value }
          }
          borrowInfo {
            apy { value }
            availableLiquidity { amount usd }
            borrowingState
          }
        }
      }
    }
    """})
    
    if "errors" in result:
        err = result["errors"][0].get("message", "")[:500]
        print(f"  Error with 'value': {err}")
        
        # Try without subfields (maybe PercentValue is a scalar)
        print("  Trying PercentValue as scalar...")
        result = post_json(AAVE_GQL, {"query": """
        {
          markets(request: { chainIds: [1] }) {
            name
            reserves {
              underlyingToken { symbol address }
              supplyInfo {
                canBeCollateral
                maxLTV
                liquidationThreshold
                liquidationBonus
              }
              borrowInfo {
                apy
                availableLiquidity { amount usd }
                borrowingState
              }
            }
          }
        }
        """})
        
        if "errors" in result:
            err = result["errors"][0].get("message", "")[:500]
            print(f"  Error as scalar: {err}")
        else:
            markets = result.get("data", {}).get("markets", [])
            print(f"  OK! Got {len(markets)} markets")
            for market in markets[:2]:
                for r in (market.get("reserves") or [])[:3]:
                    sym = r.get("underlyingToken", {}).get("symbol", "?")
                    si = r.get("supplyInfo", {})
                    bi = r.get("borrowInfo", {})
                    print(f"    {sym}: LTV={si.get('maxLTV')} LiqTh={si.get('liquidationThreshold')} BorrowAPY={bi.get('apy')} Collateral={si.get('canBeCollateral')} BorrowState={bi.get('borrowingState')}")
                    if bi.get("availableLiquidity"):
                        print(f"      AvailLiq: {bi['availableLiquidity']}")
    else:
        markets = result.get("data", {}).get("markets", [])
        print(f"  OK with 'value'! Got {len(markets)} markets")
        for market in markets[:2]:
            for r in (market.get("reserves") or [])[:3]:
                sym = r.get("underlyingToken", {}).get("symbol", "?")
                si = r.get("supplyInfo", {})
                bi = r.get("borrowInfo", {})
                print(f"    {sym}: LTV={si.get('maxLTV')} BorrowAPY={bi.get('apy')} Collateral={si.get('canBeCollateral')}")

except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Fix test complete ===")