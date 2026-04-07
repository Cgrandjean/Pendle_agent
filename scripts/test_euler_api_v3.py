"""Test Euler V2 API — try subgraph and on-chain data sources."""

import json
import urllib.request

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def fetch_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


# ── Approach 1: Euler V2 Subgraph on Decentralized Network ──────────
# Need API key for gateway.thegraph.com, try studio instead
print("=== Euler Subgraph attempts ===")
subgraph_urls = [
    # Try The Graph hosted service alternatives
    "https://api.studio.thegraph.com/query/euler/euler-v2-ethereum/version/latest",
    "https://api.studio.thegraph.com/query/euler-xyz/euler-v2/version/latest",
    # Goldsky (another indexer)
    "https://api.goldsky.com/api/public/project_euler/subgraphs/euler-v2-ethereum/latest/gn",
]

for url in subgraph_urls:
    try:
        result = post_json(url, {"query": "{ _meta { block { number } } }"})
        print(f"  {url}: OK - {json.dumps(result)[:300]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if hasattr(e, 'read') else ""
        print(f"  {url}: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"  {url}: {e}")

# ── Approach 2: Euler V2 uses EulerEarn vaults ──────────────────────
# Check if there's an Euler earn API
print("\n=== Euler Earn / EVC endpoints ===")
earn_urls = [
    "https://earn.euler.finance/api/vaults",
    "https://www.euler.finance/api/v1/vaults",
]

for url in earn_urls:
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers=HEADERS), timeout=15
        ).read().decode()
        data = json.loads(raw)
        print(f"  {url}: OK - {type(data).__name__}")
        if isinstance(data, list) and data:
            print(f"    {len(data)} items, keys: {list(data[0].keys())[:15]}")
        elif isinstance(data, dict):
            print(f"    keys: {list(data.keys())[:10]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if hasattr(e, 'read') else ""
        print(f"  {url}: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"  {url}: {e}")

# ── Approach 3: Check DeFiLlama config endpoint for Euler ───────────
print("\n=== DeFiLlama protocol info for Euler ===")
try:
    data = fetch_json("https://api.llama.fi/protocol/euler-v2")
    print(f"  Keys: {list(data.keys())[:15]}")
    print(f"  Name: {data.get('name')}")
    print(f"  Category: {data.get('category')}")
    print(f"  URL: {data.get('url')}")
    # Check if there are audit/methodology links
    print(f"  Methodology: {data.get('methodology', 'N/A')}")
except Exception as e:
    print(f"  Error: {e}")

# ── Approach 4: Check Euler's GitHub for API docs ────────────────────
# Euler V2 uses a "perspective" system for vaults
# Let's try known Euler V2 SDK/API patterns
print("\n=== Euler V2 Known Patterns ===")

# Euler V2 frontend might use Next.js API routes that proxy to on-chain data
# Or they might use a service like Alchemy/Infura + Lens contracts
# Let's check if there's an evk-periphery API

# Try to find the actual data source by checking the euler-v2 repository
# Their UI code often has API base URLs

# Alternative: Use the Euler V2 Oracle/Lens via a public RPC
# The EulerVaultLens contract on Ethereum mainnet
print("  Euler V2 uses on-chain Lens contracts for data")
print("  EulerVaultLens: reads vault state directly from blockchain")
print("  For our purposes, DeFiLlama + on-chain reads would be the approach")

# ── Approach 5: Try DeFiLlama /pools endpoint with more detail ──────
print("\n=== DeFiLlama Euler pools - detailed ===")
try:
    data = fetch_json("https://yields.llama.fi/pools")
    pools = data.get("data", [])
    
    euler_pools = [p for p in pools if "euler" in p.get("project", "").lower()]
    
    # Group by chain
    chains = {}
    for p in euler_pools:
        chain = p.get("chain", "Unknown")
        chains.setdefault(chain, []).append(p)
    
    print(f"  Total Euler pools: {len(euler_pools)}")
    for chain, chain_pools in sorted(chains.items()):
        print(f"\n  {chain}: {len(chain_pools)} pools")
        # Sort by TVL
        chain_pools.sort(key=lambda x: x.get("tvlUsd") or 0, reverse=True)
        for p in chain_pools[:5]:
            sym = p.get("symbol", "N/A")
            tvl = p.get("tvlUsd") or 0
            apy = p.get("apy") or 0
            borrow = p.get("apyBaseBorrow")
            meta = p.get("poolMeta") or ""
            pool_id = (p.get("pool") or "")[:50]
            print(
                f"    {sym} | TVL: ${tvl:,.0f} | APY: {apy:.2f}% | "
                f"Borrow: {borrow or 'N/A'} | meta: {meta} | {pool_id}"
            )
    
    # Check for stablecoin pools where we could borrow
    stable_euler = [
        p for p in euler_pools
        if p.get("chain") == "Ethereum"
        and any(s in (p.get("symbol") or "").upper() for s in ["USDC", "USDT", "DAI", "USDE", "PYUSD"])
        and (p.get("tvlUsd") or 0) > 1_000_000
    ]
    print(f"\n  === Ethereum stablecoin Euler pools (TVL > $1M) ===")
    for p in stable_euler:
        print(
            f"    {p.get('symbol')} | TVL: ${p.get('tvlUsd') or 0:,.0f} | "
            f"APY: {p.get('apy') or 0:.2f}% | "
            f"Borrow: {p.get('apyBaseBorrow') or 'N/A'} | "
            f"pool: {(p.get('pool') or '')[:50]}"
        )

except Exception as e:
    print(f"  Error: {e}")

# ── Approach 6: Check individual Euler pool on DeFiLlama ────────────
print("\n=== Check Euler pool detail on DeFiLlama ===")
try:
    data = fetch_json("https://yields.llama.fi/pools")
    pools = data.get("data", [])
    
    euler_eth = [p for p in pools if "euler" in p.get("project", "").lower() and p.get("chain") == "Ethereum"]
    if euler_eth:
        # Get the pool ID of the biggest pool
        euler_eth.sort(key=lambda x: x.get("tvlUsd") or 0, reverse=True)
        pool_id = euler_eth[0]["pool"]
        print(f"  Checking pool: {pool_id}")
        
        # Try to get chart/historical data for this pool
        detail = fetch_json(f"https://yields.llama.fi/chart/{pool_id}")
        if isinstance(detail, dict) and "data" in detail:
            points = detail["data"]
            if points:
                latest = points[-1]
                print(f"  Latest data point keys: {list(latest.keys())}")
                print(f"  Latest: {json.dumps(latest)[:500]}")
        else:
            print(f"  Chart data: {str(detail)[:300]}")

except Exception as e:
    print(f"  Error: {e}")

print("\n=== Euler API v3 test complete ===")