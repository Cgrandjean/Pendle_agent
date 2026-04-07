"""Test Euler V2 API — find PT markets with borrow data."""

import json
import urllib.request

# Euler V2 uses a subgraph or their own API
# Let's try multiple endpoints

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def fetch_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


# ── Approach 1: Euler V2 API (app.euler.finance uses this) ──────────
print("=== Euler API Discovery ===")

# Try known Euler endpoints
endpoints = [
    "https://app.euler.finance/api/v2/markets",
    "https://api.euler.finance/v1/markets",
    "https://euler-api.euler.finance/v1/markets",
]

for ep in endpoints:
    try:
        result = fetch_json(ep)
        print(f"  {ep}: OK - type={type(result).__name__}, len={len(result) if isinstance(result, (list, dict)) else '?'}")
        if isinstance(result, list) and result:
            print(f"    Sample keys: {list(result[0].keys())[:15]}")
        elif isinstance(result, dict):
            print(f"    Keys: {list(result.keys())[:15]}")
        break
    except Exception as e:
        print(f"  {ep}: {e}")

# ── Approach 2: Euler V2 Subgraph ──────────────────────────────────
print("\n=== Euler V2 Subgraph ===")
EULER_SUBGRAPH_URLS = [
    "https://api.thegraph.com/subgraphs/name/euler-xyz/euler-v2",
    "https://gateway.thegraph.com/api/subgraphs/id/euler-v2-ethereum",
]

for url in EULER_SUBGRAPH_URLS:
    try:
        result = post_json(url, {"query": "{ _meta { block { number } } }"})
        print(f"  {url}: OK - {json.dumps(result)[:200]}")
    except Exception as e:
        print(f"  {url}: {e}")

# ── Approach 3: DeFiLlama for Euler data ────────────────────────────
print("\n=== DeFiLlama: Euler pools ===")
try:
    req = urllib.request.Request("https://yields.llama.fi/pools", headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    data = json.loads(raw)
    pools = data.get("data", [])

    euler_pools = [p for p in pools if "euler" in p.get("project", "").lower()]
    print(f"  Total Euler pools on DeFiLlama: {len(euler_pools)}")

    # Show pools with PT tokens
    euler_pt = [p for p in euler_pools if "PT" in (p.get("symbol") or "").upper()]
    print(f"  Euler PT pools: {len(euler_pt)}")
    for p in euler_pt[:10]:
        print(
            f"    {p.get('symbol', 'N/A')} | chain: {p.get('chain', 'N/A')} | "
            f"TVL: ${p.get('tvlUsd') or 0:,.0f} | "
            f"APY: {p.get('apy') or 0:.2f}% | "
            f"apyBaseBorrow: {p.get('apyBaseBorrow') or 'N/A'} | "
            f"pool: {(p.get('pool') or '')[:40]}"
        )

    # Show top Euler pools by TVL to understand structure
    euler_pools_sorted = sorted(euler_pools, key=lambda p: p.get("tvlUsd") or 0, reverse=True)
    print(f"\n  Top 10 Euler pools by TVL:")
    for p in euler_pools_sorted[:10]:
        print(
            f"    {p.get('symbol', 'N/A')} | chain: {p.get('chain', 'N/A')} | "
            f"TVL: ${p.get('tvlUsd') or 0:,.0f} | "
            f"APY: {p.get('apy') or 0:.2f}% | "
            f"Borrow: {p.get('apyBaseBorrow') or 'N/A'} | "
            f"project: {p.get('project')}"
        )

    # Check field structure
    if euler_pools:
        sample = euler_pools[0]
        print(f"\n  Sample pool keys: {list(sample.keys())}")
        ltv_fields = {k: v for k, v in sample.items() if "ltv" in k.lower() or "liq" in k.lower() or "collateral" in k.lower() or "borrow" in k.lower()}
        print(f"  LTV/Borrow related fields: {ltv_fields}")

except Exception as e:
    print(f"  Error: {e}")

# ── Approach 4: Euler V2 Lens contract via public RPC ────────────────
print("\n=== Euler V2 REST API attempts ===")

# Try the Euler app API that the frontend uses
euler_app_urls = [
    "https://app.euler.finance/api/markets?chainId=1",
    "https://app.euler.finance/api/v1/markets?chainId=1",
]

for url in euler_app_urls:
    try:
        result = fetch_json(url)
        if isinstance(result, list):
            print(f"  {url}: OK - {len(result)} markets")
            if result:
                print(f"    Sample keys: {list(result[0].keys())[:20]}")
                # Find PT markets
                pt_markets = [m for m in result if "PT" in str(m.get("symbol", "") or m.get("name", "")).upper()]
                print(f"    PT markets: {len(pt_markets)}")
                for m in pt_markets[:5]:
                    print(f"      {m.get('symbol') or m.get('name', 'N/A')}")
        elif isinstance(result, dict):
            print(f"  {url}: OK - keys: {list(result.keys())[:15]}")
            if "data" in result:
                data = result["data"]
                if isinstance(data, list):
                    print(f"    data has {len(data)} items")
    except Exception as e:
        print(f"  {url}: {e}")

print("\n=== Euler API test complete ===")