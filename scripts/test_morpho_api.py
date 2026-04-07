"""Test Morpho Blue GraphQL API — find PT markets with borrow data."""

import json
import urllib.request

MORPHO_GQL = "https://blue-api.morpho.org/graphql"


def gql(query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        MORPHO_GQL, data=data, headers={"Content-Type": "application/json"}
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


# Step 1: Explore the Market type schema
print("=== Schema introspection: Market fields ===")
schema_q = """
{
  __type(name: "Market") {
    fields {
      name
      type { name kind ofType { name } }
    }
  }
}
"""
schema = gql(schema_q)
fields = schema.get("data", {}).get("__type", {}).get("fields", [])
for f in fields:
    t = f["type"]
    type_name = t.get("name") or (t.get("ofType", {}) or {}).get("name", "?")
    print(f"  {f['name']}: {type_name} ({t['kind']})")

# Step 2: Explore MarketState fields
print("\n=== Schema introspection: MarketState fields ===")
state_q = """
{
  __type(name: "MarketState") {
    fields {
      name
      type { name kind ofType { name } }
    }
  }
}
"""
state_schema = gql(state_q)
state_fields = state_schema.get("data", {}).get("__type", {}).get("fields", [])
for f in state_fields:
    t = f["type"]
    type_name = t.get("name") or (t.get("ofType", {}) or {}).get("name", "?")
    print(f"  {f['name']}: {type_name} ({t['kind']})")

# Step 3: Search for PT markets
print("\n=== PT markets (search='PT', first=10) ===")
markets_q = """
{
  markets(first: 10, where: { search: "PT" }) {
    items {
      uniqueKey
      collateralAsset { symbol address }
      loanAsset { symbol address }
      lltv
      state {
        borrowApy
        supplyApy
        netBorrowApy
        netSupplyApy
        supplyAssetsUsd
        borrowAssetsUsd
        liquidityAssetsUsd
      }
    }
  }
}
"""
result = gql(markets_q)
items = result.get("data", {}).get("markets", {}).get("items", [])
print(f"Found {len(items)} PT markets")
for m in items:
    col = m["collateralAsset"]["symbol"]
    loan = m["loanAsset"]["symbol"]
    lltv = int(m["lltv"]) / 1e18 if m["lltv"] else 0
    state = m["state"]
    borrow_apy = state.get("borrowApy", 0)
    supply_usd = state.get("supplyAssetsUsd", 0)
    liquidity = state.get("liquidityAssetsUsd", 0)
    if supply_usd and supply_usd > 1000:  # Skip dust markets
        print(
            f"  {col} / {loan} | LLTV: {lltv:.2%} | "
            f"Borrow APY: {borrow_apy:.4f} ({borrow_apy*100:.2f}%) | "
            f"Supply: ${supply_usd:,.0f} | Liquidity: ${liquidity:,.0f}"
        )

# Step 4: Get bigger PT markets (with more supply)
print("\n=== Top PT markets by supply (search='PT-sUSDE') ===")
susde_q = """
{
  markets(first: 10, where: { search: "PT-sUSDE" }) {
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
      }
    }
  }
}
"""
result2 = gql(susde_q)
items2 = result2.get("data", {}).get("markets", {}).get("items", [])
print(f"Found {len(items2)} PT-sUSDE markets")
for m in items2:
    col = m["collateralAsset"]["symbol"]
    loan = m["loanAsset"]["symbol"]
    lltv = int(m["lltv"]) / 1e18 if m["lltv"] else 0
    state = m["state"]
    borrow_apy = state.get("borrowApy", 0)
    supply_usd = state.get("supplyAssetsUsd", 0)
    liquidity = state.get("liquidityAssetsUsd", 0)
    print(
        f"  {col} / {loan} | LLTV: {lltv:.2%} | "
        f"Borrow APY: {borrow_apy:.4f} ({borrow_apy*100:.2f}%) | "
        f"Supply: ${supply_usd:,.0f} | Liquidity: ${liquidity:,.0f}"
    )

print("\n=== Morpho API test complete ===")