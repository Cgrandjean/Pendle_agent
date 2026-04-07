"""Discover Euler V2 API — deep exploration of all possible endpoints."""

import json
import urllib.request
import urllib.error

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def fetch_raw(url: str, timeout: int = 15) -> tuple[int, str, str]:
    """Returns (status_code, content_type, body)"""
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
# 1. Check Euler docs pages for API references
# ═══════════════════════════════════════════════════════════════════════
print("=== Check Euler documentation pages ===")
doc_urls = [
    "https://docs.euler.finance/",
    "https://docs.euler.finance/developers/",
    "https://docs.euler.finance/developers/api",
    "https://docs.euler.finance/developers/subgraph",
    "https://docs.euler.finance/developers/sdk",
    "https://docs.euler.finance/euler-vault-kit/",
]

for url in doc_urls:
    status, ct, body = fetch_raw(url, timeout=10)
    is_html = "html" in ct.lower() if ct else "<!doctype" in body.lower()[:50]
    if status == 200 and not is_html:
        print(f"  {url}: {status} JSON - {body[:300]}")
    elif status == 200:
        # Look for API-related links in HTML
        api_refs = []
        for keyword in ["api.", "graphql", "subgraph", "endpoint", "sdk", "rest", "/v1/", "/v2/"]:
            idx = body.lower().find(keyword)
            if idx > 0:
                # Get surrounding context
                start = max(0, idx - 50)
                end = min(len(body), idx + 100)
                snippet = body[start:end].replace("\n", " ").strip()
                api_refs.append(f"    Found '{keyword}' at pos {idx}: ...{snippet}...")
        if api_refs:
            print(f"  {url}: {status} HTML - API refs found:")
            for ref in api_refs[:5]:
                print(ref)
        else:
            print(f"  {url}: {status} HTML - no API refs in body")
    else:
        print(f"  {url}: {status} - {body[:100]}")

# ═══════════════════════════════════════════════════════════════════════
# 2. Check Next.js _next/data pattern (app.euler.finance)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Check Next.js patterns on app.euler.finance ===")
nextjs_urls = [
    "https://app.euler.finance/api/trpc",
    "https://app.euler.finance/api/trpc/vaults.getAll",
    "https://app.euler.finance/api/trpc/markets.getAll",
    "https://app.euler.finance/_next/data",
]

for url in nextjs_urls:
    status, ct, body = fetch_raw(url, timeout=10)
    is_json = False
    try:
        parsed = json.loads(body)
        is_json = True
    except:
        pass
    
    if is_json:
        print(f"  {url}: {status} JSON!")
        if isinstance(parsed, dict):
            print(f"    Keys: {list(parsed.keys())[:10]}")
            print(f"    Preview: {body[:300]}")
        elif isinstance(parsed, list):
            print(f"    List with {len(parsed)} items")
    else:
        short = body[:150].replace("\n", " ").strip()
        print(f"  {url}: {status} - {short}")

# ═══════════════════════════════════════════════════════════════════════
# 3. Try known Euler V2 subgraph URLs (different providers)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Try Euler V2 subgraph URLs ===")
subgraph_urls = [
    # Decentralized network (needs API key)
    "https://gateway.thegraph.com/api/subgraphs/id/2oFYm5FGSzVEMEBpBXXadfdmQJVAMkPM8JfMvtJqMka9",
    # Euler-hosted
    "https://api.euler.finance/subgraph",
    # Various hosted service patterns
    "https://subgraph.euler.finance/graphql",
    "https://data.euler.finance/graphql",
]

gql_introspect = {"query": "{ __schema { queryType { fields { name } } } }"}

for url in subgraph_urls:
    status, ct, body = post_raw(url, gql_introspect, timeout=10)
    try:
        parsed = json.loads(body)
        if "data" in parsed:
            fields = parsed["data"].get("__schema", {}).get("queryType", {}).get("fields", [])
            print(f"  {url}: OK! {len(fields)} query fields")
            for f in fields[:15]:
                print(f"    - {f['name']}")
        elif "errors" in parsed:
            print(f"  {url}: {status} - {parsed['errors'][0].get('message', '')[:200]}")
        else:
            print(f"  {url}: {status} - {body[:200]}")
    except:
        print(f"  {url}: {status} - {body[:200]}")

# ═══════════════════════════════════════════════════════════════════════
# 4. Check Euler GitHub for API docs
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Check Euler GitHub repos for API info ===")
github_urls = [
    "https://api.github.com/repos/euler-xyz/euler-v2/contents",
    "https://api.github.com/repos/euler-xyz/euler-interfaces/contents",
    "https://api.github.com/repos/euler-xyz/euler-price-oracle/contents",
    "https://api.github.com/search/repositories?q=euler+api+org:euler-xyz",
]

for url in github_urls:
    status, ct, body = fetch_raw(url, timeout=10)
    try:
        parsed = json.loads(body)
        if isinstance(parsed, list):
            names = [item.get("name", "") for item in parsed]
            print(f"  {url.split('/')[-1]}: {names}")
        elif isinstance(parsed, dict) and "items" in parsed:
            repos = [r.get("full_name", "") for r in parsed["items"][:10]]
            print(f"  Search results: {repos}")
        else:
            print(f"  {url.split('/')[-1]}: {status} - {body[:200]}")
    except:
        print(f"  {url}: {status} - {body[:150]}")

# ═══════════════════════════════════════════════════════════════════════
# 5. Try Euler V2 Lens contract address discovery
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Euler V2 contract addresses (for on-chain reads) ===")
print("  Known Euler V2 contracts on Ethereum mainnet:")
print("  - EVC (Ethereum Vault Connector): 0x0C9a3dd6b8F28529d72d7f9cE918D493519EE383")
print("  - EulerVaultLens: need to find address")
print("  - EulerEarnVaultLens: need to find address")

# Try to find lens contract via GitHub
github_lens_urls = [
    "https://api.github.com/search/code?q=EulerVaultLens+org:euler-xyz",
    "https://raw.githubusercontent.com/euler-xyz/euler-v2/master/addresses.json",
    "https://raw.githubusercontent.com/euler-xyz/euler-v2/main/addresses.json",
]

for url in github_lens_urls:
    status, ct, body = fetch_raw(url, timeout=10)
    if status == 200:
        try:
            parsed = json.loads(body)
            print(f"\n  {url.split('/')[-1]}: {status} OK")
            if isinstance(parsed, dict):
                # Look for lens-related keys
                for key, val in parsed.items():
                    if "lens" in key.lower() or "euler" in key.lower():
                        print(f"    {key}: {val}")
            elif isinstance(parsed, list):
                print(f"    {len(parsed)} items")
        except:
            # Might not be JSON
            if "lens" in body.lower():
                idx = body.lower().find("lens")
                print(f"  Found 'lens' reference: {body[max(0,idx-30):idx+100]}")
    else:
        print(f"  {url.split('/')[-1]}: {status}")

# ═══════════════════════════════════════════════════════════════════════
# 6. Try Euler V2 alternative API patterns
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Alternative Euler API patterns ===")
alt_urls = [
    # Maybe they have an API at a CDN/static endpoint
    "https://raw.githubusercontent.com/euler-xyz/euler-v2/main/deployed.json",
    "https://raw.githubusercontent.com/euler-xyz/euler-v2/master/deployed.json",
    # Common DeFi API patterns
    "https://app.euler.finance/api/health",
    "https://app.euler.finance/api/config",
    # Euler V1 had an API, check if V2 has similar
    "https://api.euler.tools/v1/",
    "https://api.euler.tools/",
]

for url in alt_urls:
    status, ct, body = fetch_raw(url, timeout=10)
    is_json = False
    try:
        parsed = json.loads(body)
        is_json = True
    except:
        pass
    
    if is_json:
        print(f"  {url}: {status} JSON!")
        if isinstance(parsed, dict):
            print(f"    Keys: {list(parsed.keys())[:10]}")
            print(f"    Preview: {body[:300]}")
        elif isinstance(parsed, list):
            print(f"    List with {len(parsed)} items")
    else:
        short = body[:150].replace("\n", " ").strip()
        if "html" not in (ct or "").lower() and status == 200:
            print(f"  {url}: {status} - {short}")
        else:
            print(f"  {url}: {status}")

print("\n=== Euler API discovery complete ===")