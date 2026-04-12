"""Telegram output formatting."""

from agents.config import CHAINS

# Reverse lookup: chain_id -> display name
CHAIN_NAMES = {}
for name, cid in CHAINS.items():
    if cid not in CHAIN_NAMES:
        CHAIN_NAMES[cid] = name.capitalize()


def _build_urls(c):
    """Build Pendle and protocol URLs from candidate data."""
    addr = c.get("address", "")
    chain_id = c.get("chain_id", 1)
    chain_name = CHAIN_NAMES.get(chain_id, "ethereum").lower()
    
    pendle_url = f"https://app.pendle.finance/trade/markets/{addr}/swap?view=pt"
    
    protocol = c.get("vault_id", "")
    vault_url = ""
    if protocol == "aavev3":
        vault_url = "https://app.aave.com"
    elif protocol == "euler":
        vault_url = "https://app.euler.finance"
    elif protocol == "morpho":
        vault_url = f"https://app.morpho.org/{chain_name}"
    
    return pendle_url, vault_url


def fmt_pct(val):
    try:
        return f"{float(val) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def fmt_usd(val):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if v >= 1e9: return f"${v/1e9:.1f}B"
    if v >= 1e6: return f"${v/1e6:.1f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def fmt_tokens(val, symbol=""):
    """Format token amount (non-USD)."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    suffix = f" {symbol}" if symbol else ""
    if v >= 1e9: return f"{v/1e9:.1f}B{suffix}"
    if v >= 1e6: return f"{v/1e6:.1f}M{suffix}"
    if v >= 1e3: return f"{v/1e3:.0f}K{suffix}"
    return f"{v:.0f}{suffix}"


def format_candidate(rank, c):
    chain = CHAIN_NAMES.get(c.get("chain_id", 0), "?")
    name = c.get("name") or "?"
    vault_name = c.get("vault_name", "")
    protocol = c.get("vault_id", "")

    # Compute on the fly
    lev = c.get("estimated_max_leverage", 0)
    theo = c.get("theoretical_max_yield", 0)
    borrow = c.get("borrow_cost_estimate", 0)
    days = c.get("days_to_expiry", 0)
    yield_at_expiry = theo * (days / 365) if days > 0 else 0

    lines = [
        f"*{rank}. {name}*",
        f"   📍 {chain}",
        f"   📊 Implied: {fmt_pct(c.get('implied_apy'))} | Underlying: {fmt_pct(c.get('underlying_apy'))}",
        f"   📈 Spread: {fmt_pct(c.get('spread'))} | PT discount: {fmt_pct(c.get('pt_discount'))}",
        f"   💰 TVL: {fmt_usd(c.get('tvl'))} | Liq: {fmt_usd(c.get('liquidity'))}",
        f"   ⏰ {days}d remaining",
    ]

    if vault_name:
        # Build borrow info string
        borrow_liq_usd = c.get("borrow_liquidity_usd", 0)
        borrow_liq_tokens = c.get("borrow_liquidity_tokens", 0)
        borrow_sym = c.get("borrow_token_symbol", "")
        
        if protocol == "euler" and borrow_liq_tokens > 0 and borrow_sym:
            borrow_info = f" (💧 {fmt_tokens(borrow_liq_tokens, borrow_sym)})"
        elif borrow_liq_usd > 0:
            borrow_info = f" (💧 {fmt_usd(borrow_liq_usd)})"
        elif borrow_liq_tokens > 0 and borrow_sym:
            borrow_info = f" (💧 {fmt_tokens(borrow_liq_tokens, borrow_sym)})"
        else:
            borrow_info = ""
        
        lines.append(f"   🔁 {vault_name}{borrow_info}")

    if lev > 0:
        lines.append(f"   🧮 {lev}x | Borrow: {fmt_pct(borrow)} | Theo: {fmt_pct(theo)}")
    else:
        lines.append(f"   🧮 Theo: {fmt_pct(theo)}")

    lines.append(f"   📅 Yield at expiry: {fmt_pct(yield_at_expiry)} ({days:.0f}d)")
    lines.append(f"   ⭐ {c.get('score', 0)}/100")

    # Compute URLs on the fly
    pendle_url, vault_url = _build_urls(c)
    label = {"morpho": "📗 Morpho", "euler": "📙 Euler", "aavev3": "📙 AAVE"}.get(protocol, "📙")
    lines.append(f"   [📘 Pendle]({pendle_url}) | [{label}]({vault_url})")

    return "\n".join(lines) + "\n"


def no_results_message(chain_name, asset_filter):
    chain = (chain_name or "all chains").capitalize()
    asset = asset_filter or "all assets"
    return (
        f"🔍 Nothing found for *{chain} / {asset}*.\n\n"
        "Try a different chain or fewer filters.\n"
        "Ex: `/loop top 5 eth arbitrum`"
    )
