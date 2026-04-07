"""Test Euler V2 via Goldsky subgraph — found in Euler docs."""

import json
import urllib.request

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

EULER_GOLDSKY = "https://api.goldsky.com/api/public/project_cm4iagnemt1wp01xn4gh1agft/subgraphs/euler-v2-mainnet/latest/gn"


def gql(query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode()
    req = urllib.request.Request(EULER_GOLDSKY, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


# ═══════════════════════════════════════════════════════════════════════
# 1. Check connection + introspect schema
# ═══════════════════════════════════════════════════════════════════════
print("=== Euler V2 Goldsky Subgraph — Connection test ===")
try:
    result = gql("{ _meta { block { number } } }")
    block = result.get("data", {}).get("_meta", {}).get("block", {}).get("number")
    print(f"  Connected! Latest block: {block}")
except Exception as e:
    print(f"  Connection error: {e}")
    exit(1)

# ═══════════════════════════════════════════════════════════════════════
# 2. Introspect query types
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Schema introspection: Query fields ===")
result = gql("{ __schema { queryType { fields { name } } } }")
fields = result.get("data", {}).get("__schema", {}).get("queryType", {}).get("fields", [])
print(f"  {len(fields)} query fields:")
for f in fields:
    print(f"    - {f['name']}")

# ═══════════════════════════════════════════════════════════════════════
# 3. Introspect Vault type (main entity)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Introspect Vault type ===")
result = gql("""
{
  __type(name: "Vault") {
    fields {
      name
      type { name kind ofType { name kind } }
    }
  }
}
""")
vault_type = result.get("data", {}).get("__type")
if vault_type:
    print(f"  Vault fields:")
    for f in vault_type.get("fields", []):
        t = f["type"]
        tname = t.get("name") or (t.get("ofType", {}) or {}).get("name", "?")
        print(f"    {f['name']}: {tname} ({t['kind']})")
else:
    print("  Vault type not found")

# ═══════════════════════════════════════════════════════════════════════
# 4. Try to list vaults / markets
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Try listing vaults ===")

# Try common entity names
for entity_name in ["vaults", "markets", "pools", "evaults", "positions"]:
    try:
        result = gql(f"{{ {entity_name}(first: 2) {{ id }} }}")
        if "errors" in result:
            print(f"  {entity_name}: {result['errors'][0].get('message', '')[:150]}")
        else:
            data = result.get("data", {}).get(entity_name, [])
            print(f"  {entity_name}: OK! {len(data)} items")
    except Exception as e:
        print(f"  {entity_name}: {e}")

# ═══════════════════════════════════════════════════════════════════════
# 5. Query vaults with details
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Query vaults with details ===")
try:
    result = gql("""
    {
      vaults(first: 10, orderBy: totalBorrows, orderDirection: desc) {
        id
        address
        name
        symbol
        asset {
          id
          symbol
          name
          decimals
        }
        totalBorrows
        totalAssets
        interestRate
        interestAccumulator
        totalShares
        supplyAPY
        borrowAPY
        ltv
      }
    }
    """)
    
    if "errors" in result:
        err = result["errors"][0].get("message", "")[:500]
        print(f"  Error: {err}")
        
        # Try minimal query first
        print("\n  Trying minimal vault query...")
        result = gql("""
        {
          vaults(first: 5) {
            id
          }
        }
        """)
        if "errors" in result:
            print(f"  Minimal error: {result['errors'][0].get('message', '')[:300]}")
        else:
            vaults = result.get("data", {}).get("vaults", [])
            print(f"  Got {len(vaults)} vaults")
            if vaults:
                # Get full vault details one at a time
                vid = vaults[0]["id"]
                print(f"  First vault ID: {vid}")
    else:
        vaults = result.get("data", {}).get("vaults", [])
        print(f"  Got {len(vaults)} vaults")
        for v in vaults[:5]:
            asset = v.get("asset", {})
            print(
                f"    {v.get('symbol', 'N/A')} | Asset: {asset.get('symbol', '?')} | "
                f"TotalBorrows: {v.get('totalBorrows')} | TotalAssets: {v.get('totalAssets')} | "
                f"BorrowAPY: {v.get('borrowAPY')} | SupplyAPY: {v.get('supplyAPY')} | "
                f"LTV: {v.get('ltv')}"
            )

except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════════════════
# 6. If vault type exists, introspect related types
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Introspect related types ===")
for type_name in ["Asset", "Token", "Market", "Position", "Account", "InterestRate", "EVault"]:
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
    if t and t.get("fields"):
        print(f"\n  {t['name']} ({t['kind']}): {len(t['fields'])} fields")
        for f in t["fields"][:15]:
            ft = f["type"]
            fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
            print(f"    {f['name']}: {fname} ({ft['kind']})")

print("\n=== Euler Goldsky test complete ===")