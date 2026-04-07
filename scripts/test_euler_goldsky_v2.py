"""Test Euler V2 Goldsky subgraph — query eulerVaults and related entities."""

import json
import urllib.request

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

EULER_GOLDSKY = "https://api.goldsky.com/api/public/project_cm4iagnemt1wp01xn4gh1agft/subgraphs/euler-v2-mainnet/latest/gn"


def gql(query: str) -> dict:
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(EULER_GOLDSKY, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


# ═══════════════════════════════════════════════════════════════════════
# 1. Introspect EulerVault type
# ═══════════════════════════════════════════════════════════════════════
print("=== Introspect EulerVault type ===")
result = gql("""
{
  __type(name: "EulerVault") {
    fields {
      name
      type { name kind ofType { name kind } }
    }
  }
}
""")
t = result.get("data", {}).get("__type")
if t:
    print(f"  EulerVault: {len(t['fields'])} fields")
    for f in t["fields"]:
        ft = f["type"]
        fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
        print(f"    {f['name']}: {fname} ({ft['kind']})")

# ═══════════════════════════════════════════════════════════════════════
# 2. Introspect VaultStatus type
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Introspect VaultStatus type ===")
result = gql("""
{
  __type(name: "VaultStatus") {
    fields {
      name
      type { name kind ofType { name kind } }
    }
  }
}
""")
t = result.get("data", {}).get("__type")
if t:
    print(f"  VaultStatus: {len(t['fields'])} fields")
    for f in t["fields"]:
        ft = f["type"]
        fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
        print(f"    {f['name']}: {fname} ({ft['kind']})")

# ═══════════════════════════════════════════════════════════════════════
# 3. Query eulerVaults
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Query eulerVaults (first 10) ===")
result = gql("""
{
  eulerVaults(first: 10) {
    id
  }
}
""")
if "errors" in result:
    print(f"  Error: {result['errors'][0].get('message', '')[:300]}")
else:
    vaults = result.get("data", {}).get("eulerVaults", [])
    print(f"  Got {len(vaults)} vaults")
    for v in vaults[:3]:
        print(f"    ID: {v['id']}")

# ═══════════════════════════════════════════════════════════════════════
# 4. Try to get vault details with available fields
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Query eulerVaults with details ===")
# Build query step by step based on introspected fields
result = gql("""
{
  eulerVaults(first: 20, orderBy: id, orderDirection: desc) {
    id
    address
    asset
    totalBorrowed
    totalSupplied
    interestRate
    borrowRate
    supplyRate
    totalShares
    name
    symbol
    decimals
  }
}
""")
if "errors" in result:
    err = result["errors"][0].get("message", "")[:500]
    print(f"  Error: {err}")
    
    # Try with only id and address
    print("\n  Trying id + address only...")
    result = gql("""
    {
      eulerVaults(first: 5) {
        id
        address
      }
    }
    """)
    if "errors" in result:
        print(f"  Error: {result['errors'][0].get('message', '')[:300]}")
    else:
        vaults = result.get("data", {}).get("eulerVaults", [])
        print(f"  Got {len(vaults)} vaults")
        for v in vaults[:3]:
            print(f"    {v}")
else:
    vaults = result.get("data", {}).get("eulerVaults", [])
    print(f"  Got {len(vaults)} vaults")
    for v in vaults[:10]:
        print(f"    {v.get('symbol', '?')} | Asset: {v.get('asset', '?')} | "
              f"Borrowed: {v.get('totalBorrowed')} | Supplied: {v.get('totalSupplied')} | "
              f"BorrowRate: {v.get('borrowRate')} | SupplyRate: {v.get('supplyRate')}")

# ═══════════════════════════════════════════════════════════════════════
# 5. Check vaultStatuses for current state
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Query vaultStatuses ===")
result = gql("""
{
  vaultStatuses(first: 10, orderBy: timestamp, orderDirection: desc) {
    id
    timestamp
    totalBorrows
    totalShares
    interestAccumulator
    cash
  }
}
""")
if "errors" in result:
    err = result["errors"][0].get("message", "")[:500]
    print(f"  Error: {err}")
    
    # Minimal
    result = gql("""
    {
      vaultStatuses(first: 3) {
        id
      }
    }
    """)
    if "errors" in result:
        print(f"  Minimal error: {result['errors'][0].get('message', '')[:300]}")
    else:
        statuses = result.get("data", {}).get("vaultStatuses", [])
        print(f"  Got {len(statuses)} statuses")
        for s in statuses[:3]:
            print(f"    {s}")
else:
    statuses = result.get("data", {}).get("vaultStatuses", [])
    print(f"  Got {len(statuses)} statuses")
    for s in statuses[:5]:
        print(f"    {json.dumps(s)[:200]}")

# ═══════════════════════════════════════════════════════════════════════
# 6. Introspect EulerEarnVault for earn vaults
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Introspect EulerEarnVault ===")
result = gql("""
{
  __type(name: "EulerEarnVault") {
    fields {
      name
      type { name kind ofType { name kind } }
    }
  }
}
""")
t = result.get("data", {}).get("__type")
if t:
    print(f"  EulerEarnVault: {len(t['fields'])} fields")
    for f in t["fields"][:20]:
        ft = f["type"]
        fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
        print(f"    {f['name']}: {fname} ({ft['kind']})")

# ═══════════════════════════════════════════════════════════════════════
# 7. Check borrows entity
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Introspect Borrow type ===")
result = gql("""
{
  __type(name: "Borrow") {
    fields {
      name
      type { name kind ofType { name kind } }
    }
  }
}
""")
t = result.get("data", {}).get("__type")
if t:
    print(f"  Borrow: {len(t['fields'])} fields")
    for f in t["fields"]:
        ft = f["type"]
        fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
        print(f"    {f['name']}: {fname} ({ft['kind']})")

print("\n=== Euler Goldsky v2 test complete ===")