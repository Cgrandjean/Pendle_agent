"""Test Aave V3 API — using their actual GraphQL endpoint + DeFiLlama."""

import json
import urllib.request

HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}


def post_json(url: str, payload: dict, timeout: int = 15) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={**HEADERS, "Content-Type": "application/json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def fetch_raw(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout).read().decode()


# ── Approach 1: Aave V3 GraphQL (found in sandbox HTML) ──────────
AAVE_GQL = "https://api.v3.aave.com/graphql"

print("=== Aave V3 GraphQL: introspect ===")
try:
    result = post_json(AAVE_GQL, {"query": "{ health }"})
    print(f"  health: {json.dumps(result)[:300]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== Aave V3 GraphQL: schema introspection ===")
try:
    result = post_json(AAVE_GQL, {
        "query": "{ __schema { queryType { fields { name } } } }"
    })
    fields = result.get("data", {}).get("__schema", {}).get("queryType", {}).get("fields", [])
    print(f"  Query fields ({len(fields)}):")
    for f in fields:
        print(f"    - {f['name']}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== Aave V3 GraphQL: try reserves/markets ===")
# Try common field names
queries_to_try = [
    ("reserves", '{ reserves(first: 3) { id symbol } }'),
    ("markets", '{ markets(first: 3) { id } }'),
    ("pools", '{ pools(first: 3) { id } }'),
    ("assets", '{ assets(first: 3) { id symbol } }'),
]
for name, q in queries_to_try:
    try:
        result = post_json(AAVE_GQL, {"query": q})
        if "errors" in result:
            print(f"  {name}: {result['errors'][0].get('message', '')[:200]}")
        else:
            print(f"  {name}: OK - {json.dumps(result.get('data', {}))[:300]}")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# ── Approach 2: DeFiLlama for Aave borrow rates ─────────────────
print("\n\n=== DeFiLlama: Aave V3 borrow rates ===")
try:
    raw = fetch_raw("https://yields.llama.fi/pools")
    data = json.loads(raw)
    pools = data.get("data", [])

    # PT tokens on Aave
    aave_pt = [
        p for p in pools
        if "aave" in p.get("project", "").lower()
        and "PT" in (p.get("symbol") or "").upper()
    ]
    print(f"  Aave PT pools: {len(aave_pt)}")
    for p in aave_pt[:10]:
        print(
            f"    {p.get('symbol', 'N/A')} | chain: {p.get('chain', 'N/A')} | "
            f"TVL: ${p.get('tvlUsd') or 0:,.0f} | "
            f"APY: {p.get('apy') or 0:.2f}% | "
            f"apyBaseBorrow: {p.get('apyBaseBorrow') or 'N/A'}"
        )

    # Show a pool's full structure to understand borrow data
    if aave_pt:
        print(f"\n  Full sample pool keys: {list(aave_pt[0].keys())}")

    # Stable borrow rates on Ethereum
    aave_stable_eth = [
        p for p in pools
        if "aave" in p.get("project", "").lower()
        and p.get("chain") == "Ethereum"
        and any(s in (p.get("symbol") or "").upper() for s in ["USDC", "USDT", "DAI"])
        and (p.get("tvlUsd") or 0) > 100_000_000
    ]
    print(f"\n  Aave major stable pools on Ethereum: {len(aave_stable_eth)}")
    for p in aave_stable_eth:
        print(
            f"    {p.get('symbol', 'N/A')} | TVL: ${p.get('tvlUsd') or 0:,.0f} | "
            f"Supply APY: {p.get('apyBase') or 0:.2f}% | "
            f"Borrow APY: {p.get('apyBaseBorrow') or 'N/A'} | "
            f"pool: {(p.get('pool') or '')[:30]}"
        )

    # Also check: does DeFiLlama expose LTV/LLTV for Aave?
    if aave_pt:
        sample = aave_pt[0]
        ltv_fields = {k: v for k, v in sample.items() if "ltv" in k.lower() or "liq" in k.lower() or "collateral" in k.lower()}
        print(f"\n  LTV-related fields in pool data: {ltv_fields}")

except Exception as e:
    print(f"  Error: {e}")

# ── Approach 3: DeFiLlama lend/borrow endpoint ──────────────────
print("\n\n=== DeFiLlama: lend-borrow data ===")
try:
    raw = fetch_raw("https://yields.llama.fi/lendBorrow")
    data = json.loads(raw)
    pools = data if isinstance(data, list) else data.get("data", data)
    if isinstance(pools, list):
        print(f"  Total lend-borrow pools: {len(pools)}")
        aave_lb = [
            p for p in pools
            if "aave" in str(p.get("project", "")).lower()
            and "PT" in str(p.get("symbol", "")).upper()
        ]
        print(f"  Aave PT lend-borrow: {len(aave_lb)}")
        for p in aave_lb[:5]:
            print(f"    {json.dumps(p)[:300]}")
    else:
        print(f"  Type: {type(pools)}, preview: {str(pools)[:300]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== Aave API test complete ===")