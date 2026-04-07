"""Test Aave V3 GraphQL at api.v3.aave.com/graphql — explore markets schema."""

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


# Step 1: Introspect the 'markets' query argument type
print("=== Introspect 'markets' query ===")
try:
    result = gql("""
    {
      __type(name: "Query") {
        fields(includeDeprecated: false) {
          name
          args {
            name
            type { name kind ofType { name kind ofType { name } } }
          }
        }
      }
    }
    """)
    fields = result.get("data", {}).get("__type", {}).get("fields", [])
    for f in fields:
        if f["name"] in ("markets", "market", "reserve", "borrow", "supply", "userSupplies", "userBorrows"):
            print(f"\n  {f['name']}:")
            for a in f.get("args", []):
                t = a["type"]
                type_name = t.get("name") or (t.get("ofType", {}) or {}).get("name", "?")
                print(f"    arg: {a['name']} -> {type_name} ({t['kind']})")
except Exception as e:
    print(f"  Error: {e}")

# Step 2: Introspect the MarketsRequestInput type
print("\n=== Introspect MarketsRequestInput ===")
for type_name in ["MarketsRequestInput", "MarketsRequest", "MarketRequest", "Query"]:
    try:
        result = gql(f"""
        {{
          __type(name: "{type_name}") {{
            name
            kind
            inputFields {{
              name
              type {{ name kind ofType {{ name kind }} }}
            }}
            fields {{
              name
              type {{ name kind ofType {{ name kind }} }}
            }}
          }}
        }}
        """)
        t = result.get("data", {}).get("__type")
        if t and (t.get("inputFields") or t.get("fields")):
            print(f"\n  {type_name} ({t['kind']}):")
            for f in (t.get("inputFields") or t.get("fields") or []):
                ft = f["type"]
                fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
                print(f"    {f['name']}: {fname} ({ft['kind']})")
    except Exception as e:
        print(f"  {type_name}: Error - {e}")

# Step 3: Try to query markets with minimal args
print("\n=== Try markets query ===")
queries = [
    ('empty request', '{ markets(request: {}) { id } }'),
    ('chainId 1', '{ markets(request: { chainId: 1 }) { id } }'),
]
for label, q in queries:
    try:
        result = gql(q)
        if "errors" in result:
            err = result["errors"][0].get("message", "")[:300]
            print(f"  {label}: ERROR - {err}")
        else:
            print(f"  {label}: OK - {json.dumps(result.get('data', {}))[:500]}")
    except Exception as e:
        print(f"  {label}: Error - {e}")

# Step 4: Introspect Market type to see what fields are available
print("\n=== Introspect Market type ===")
try:
    result = gql("""
    {
      __type(name: "Market") {
        name
        kind
        fields {
          name
          type { name kind ofType { name kind } }
        }
      }
    }
    """)
    t = result.get("data", {}).get("__type")
    if t:
        print(f"  {t['name']} ({t['kind']}):")
        for f in (t.get("fields") or []):
            ft = f["type"]
            fname = ft.get("name") or (ft.get("ofType", {}) or {}).get("name", "?")
            print(f"    {f['name']}: {fname} ({ft['kind']})")
except Exception as e:
    print(f"  Error: {e}")

# Step 5: Introspect 'reserve' query
print("\n=== Try reserve query ===")
try:
    result = gql("""
    {
      __type(name: "Query") {
        fields(includeDeprecated: false) {
          name
          args {
            name
            type { name kind ofType { name kind ofType { name } } }
          }
        }
      }
    }
    """)
    fields = result.get("data", {}).get("__type", {}).get("fields", [])
    reserve_field = next((f for f in fields if f["name"] == "reserve"), None)
    if reserve_field:
        print(f"  reserve args:")
        for a in reserve_field.get("args", []):
            t = a["type"]
            type_name = t.get("name") or (t.get("ofType", {}) or {}).get("name", "?")
            print(f"    {a['name']}: {type_name} ({t['kind']})")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== Done ===")