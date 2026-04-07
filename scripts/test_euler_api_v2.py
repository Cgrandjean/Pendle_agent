"""Test Euler V2 API — deeper exploration."""

import json
import urllib.request

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def fetch_raw(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=timeout)
    print(f"  Status: {resp.status}, Content-Type: {resp.headers.get('content-type')}")
    return resp.read().decode()


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


# ── Approach 1: Euler V2 app.euler.finance internal API ──────────────
# The frontend at app.euler.finance likely has an internal API
# Let's check what the page returns
print("=== Check app.euler.finance responses ===")
urls_to_check = [
    "https://app.euler.finance/api/v2/markets",
    "https://app.euler.finance/api/markets",
    "https://app.euler.finance/api/vaults",
    "https://app.euler.finance/api/v2/vaults",
]

for url in urls_to_check:
    try:
        raw = fetch_raw(url)
        if raw.strip():
            print(f"  {url}: {raw[:300]}")
        else:
            print(f"  {url}: empty response")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if hasattr(e, 'read') else ""
        print(f"  {url}: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"  {url}: {e}")

# ── Approach 2: Euler V2 uses EVC (Ethereum Vault Connector) ────────
# Their API might be at a different domain
print("\n=== Try Euler backend API ===")
backend_urls = [
    "https://backend.euler.finance/api/v1/vaults?chainId=1",
    "https://api-v2.euler.finance/vaults?chainId=1",
    "https://euler.finance/api/vaults",
]

for url in backend_urls:
    try:
        raw = fetch_raw(url)
        data = json.loads(raw)
        if isinstance(data, list):
            print(f"  {url}: {len(data)} items")
            if data:
                print(f"    Keys: {list(data[0].keys())[:15]}")
        elif isinstance(data, dict):
            print(f"  {url}: {list(data.keys())[:10]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if hasattr(e, 'read') else ""
        print(f"  {url}: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"  {url}: {e}")

# ── Approach 3: Euler V2 GraphQL (some protocols use this) ──────────
print("\n=== Try Euler GraphQL endpoints ===")
gql_urls = [
    "https://app.euler.finance/graphql",
    "https://app.euler.finance/api/graphql",
]

for url in gql_urls:
    try:
        result = post_json(url, {"query": "{ __schema { queryType { fields { name } } } }"})
        fields = result.get("data", {}).get("__schema", {}).get("queryType", {}).get("fields", [])
        print(f"  {url}: {len(fields)} query fields")
        for f in fields[:20]:
            print(f"    - {f['name']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if hasattr(e, 'read') else ""
        print(f"  {url}: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"  {url}: {e}")

# ── Approach 4: Use DeFiLlama lendBorrow for Euler ──────────────────
print("\n=== DeFiLlama lendBorrow for Euler ===")
try:
    req = urllib.request.Request("https://yields.llama.fi/lendBorrow", headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    data = json.loads(raw)
    pools = data if isinstance(data, list) else data.get("data", data)

    if isinstance(pools, list):
        euler_lb = [p for p in pools if "euler" in str(p.get("project", "")).lower()]
        print(f"  Euler lend-borrow pools: {len(euler_lb)}")
        for p in euler_lb[:10]:
            print(f"    {json.dumps(p)[:300]}")
    else:
        print(f"  Type: {type(pools)}, preview: {str(pools)[:300]}")
except Exception as e:
    print(f"  Error: {e}")

# ── Approach 5: DeFiLlama pools with borrow data ────────────────────
print("\n=== DeFiLlama pools with borrow data for Euler ===")
try:
    req = urllib.request.Request("https://yields.llama.fi/pools", headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    data = json.loads(raw)
    pools = data.get("data", [])

    euler_with_borrow = [
        p for p in pools
        if "euler" in p.get("project", "").lower()
        and p.get("apyBaseBorrow") is not None
    ]
    print(f"  Euler pools with borrow data: {len(euler_with_borrow)}")
    for p in euler_with_borrow[:15]:
        print(
            f"    {p.get('symbol', 'N/A')} | chain: {p.get('chain', 'N/A')} | "
            f"TVL: ${p.get('tvlUsd') or 0:,.0f} | "
            f"Supply APY: {p.get('apyBase') or 0:.2f}% | "
            f"Borrow APY: {p.get('apyBaseBorrow') or 0:.2f}% | "
            f"pool: {(p.get('pool') or '')[:40]}"
        )

    # Check if any Euler pool has collateral info
    if euler_with_borrow:
        sample = euler_with_borrow[0]
        print(f"\n  Full sample pool:")
        for k, v in sample.items():
            print(f"    {k}: {v}")

except Exception as e:
    print(f"  Error: {e}")

print("\n=== Euler API v2 test complete ===")