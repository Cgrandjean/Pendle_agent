"""Discover Euler V2 API — follow up on leads from first discovery."""

import json
import urllib.request
import urllib.error

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def fetch_raw(url: str, timeout: int = 15) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.headers.get("content-type", ""), resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if hasattr(e, "read") else ""
        return e.code, "", body
    except Exception as e:
        return 0, "", str(e)


def post_raw(url: str, payload: dict, timeout: int = 15) -> tuple[int, str, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.headers.get("content-type", ""), resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if hasattr(e, "read") else ""
        return e.code, "", body
    except Exception as e:
        return 0, "", str(e)


# ═══════════════════════════════════════════════════════════════════════
# 1. Check euler-interfaces addresses folder
# ═══════════════════════════════════════════════════════════════════════
print("=== euler-interfaces/addresses folder ===")
status, ct, body = fetch_raw("https://api.github.com/repos/euler-xyz/euler-interfaces/contents/addresses")
try:
    files = json.loads(body)
    if isinstance(files, list):
        print(f"  Files in addresses/: {[f['name'] for f in files]}")
        # Get each JSON file
        for f in files:
            if f["name"].endswith(".json"):
                _, _, content = fetch_raw(f["download_url"], timeout=10)
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        # Look for lens or vault-related keys
                        lens_keys = [k for k in data.keys() if "lens" in k.lower()]
                        vault_keys = [k for k in data.keys() if "vault" in k.lower() or "evk" in k.lower()]
                        all_keys = list(data.keys())[:20]
                        print(f"\n  {f['name']}: {len(data)} entries")
                        print(f"    All keys (first 20): {all_keys}")
                        if lens_keys:
                            print(f"    Lens keys: {lens_keys}")
                            for k in lens_keys:
                                print(f"      {k}: {data[k]}")
                        if vault_keys:
                            print(f"    Vault keys: {vault_keys[:5]}")
                    elif isinstance(data, list):
                        print(f"  {f['name']}: list with {len(data)} items")
                        if data:
                            print(f"    First item keys: {list(data[0].keys()) if isinstance(data[0], dict) else type(data[0])}")
                except:
                    print(f"  {f['name']}: not valid JSON")
except Exception as e:
    print(f"  Error: {e}")

# ═══════════════════════════════════════════════════════════════════════
# 2. Check euler-history-api repo
# ═══════════════════════════════════════════════════════════════════════
print("\n=== euler-history-api repo ===")
status, ct, body = fetch_raw("https://api.github.com/repos/euler-xyz/euler-history-api/contents")
try:
    files = json.loads(body)
    if isinstance(files, list):
        names = [f["name"] for f in files]
        print(f"  Root files: {names}")
        
        # Check README for API endpoint info
        readme_file = next((f for f in files if f["name"].lower() in ("readme.md", "readme")), None)
        if readme_file:
            _, _, readme = fetch_raw(readme_file["download_url"], timeout=10)
            print(f"\n  README.md preview:\n{readme[:2000]}")
except Exception as e:
    print(f"  Error: {e}")

# ═══════════════════════════════════════════════════════════════════════
# 3. Check the Euler docs subgraph page
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Euler docs - subgraph page ===")
status, ct, body = fetch_raw("https://docs.euler.finance/developers/data-querying/subgraphs", timeout=15)
if status == 200:
    # Extract useful content from HTML
    # Look for subgraph URLs, API endpoints, etc.
    keywords = ["thegraph.com", "subgraph", "api.", "endpoint", "graphql", "query", "https://"]
    for kw in keywords:
        idx = 0
        found = []
        while True:
            idx = body.lower().find(kw.lower(), idx)
            if idx < 0:
                break
            start = max(0, idx - 30)
            end = min(len(body), idx + 150)
            snippet = body[start:end].replace("\n", " ").replace("<", " <").strip()
            found.append(snippet)
            idx += len(kw)
        if found:
            print(f"\n  '{kw}' occurrences ({len(found)}):")
            for s in found[:5]:
                print(f"    {s[:200]}")
else:
    print(f"  Status: {status}")

# ═══════════════════════════════════════════════════════════════════════
# 4. Check EulerChains.json from euler-interfaces
# ═══════════════════════════════════════════════════════════════════════
print("\n=== EulerChains.json ===")
status, ct, body = fetch_raw("https://raw.githubusercontent.com/euler-xyz/euler-interfaces/master/EulerChains.json")
if status == 200:
    try:
        data = json.loads(body)
        print(f"  Type: {type(data).__name__}")
        print(f"  Content: {json.dumps(data, indent=2)[:2000]}")
    except:
        print(f"  Raw: {body[:500]}")
else:
    print(f"  Status: {status}")

# ═══════════════════════════════════════════════════════════════════════
# 5. Try the Euler V2 subgraph with known IDs
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Try Euler subgraphs with different IDs ===")
# Try common subgraph ID patterns for Euler
subgraph_attempts = [
    # Euler V2 on The Graph Studio
    "https://api.studio.thegraph.com/query/22452/euler-v2-ethereum/version/latest",
    "https://api.studio.thegraph.com/query/22452/euler-v2/version/latest",
    # Different org IDs
    "https://api.studio.thegraph.com/query/euler-finance/euler-v2-ethereum/version/latest",
    "https://api.studio.thegraph.com/query/euler-xyz/euler-v2-ethereum/version/latest",
    # Chainstack / other providers
    "https://subgraph.satsuma-prod.com/euler/euler-v2-ethereum/api",
]

for url in subgraph_attempts:
    status, ct, body = post_raw(url, {"query": "{ _meta { block { number } } }"}, timeout=10)
    try:
        parsed = json.loads(body)
        if "data" in parsed:
            print(f"  {url}: OK! Block: {parsed['data'].get('_meta', {}).get('block', {}).get('number')}")
        elif "errors" in parsed:
            msg = parsed["errors"][0].get("message", "")[:150]
            print(f"  {url}: Error - {msg}")
        else:
            print(f"  {url}: {body[:150]}")
    except:
        short = body[:100] if body else "empty"
        print(f"  {url}: {status} - {short}")

print("\n=== Euler discovery v2 complete ===")