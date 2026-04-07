"""Telegram output formatting."""

from agents.config import CHAINS

# Reverse lookup: chain_id -> display name
CHAIN_NAMES = {}
for name, cid in CHAINS.items():
    if cid not in CHAIN_NAMES:
        CHAIN_NAMES[cid] = name.capitalize()


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


def format_candidate(rank, c):
    chain = CHAIN_NAMES.get(c.get("chain_id", 0), "?")
    name = c.get("name") or c.get("symbol") or "?"
    proto = c.get("protocol") or ""

    lines = [
        f"*{rank}. {name}*",
        f"   📍 {chain}" + (f" | {proto}" if proto else ""),
        f"   📊 Implied: {fmt_pct(c.get('implied_apy'))} | Underlying: {fmt_pct(c.get('underlying_apy'))}",
        f"   📈 Spread: {fmt_pct(c.get('spread'))} | PT discount: {fmt_pct(c.get('pt_discount'))}",
        f"   💰 TVL: {fmt_usd(c.get('tvl'))} | Liq: {fmt_usd(c.get('liquidity'))}",
        f"   ⏰ {c.get('days_to_expiry', '?')}d remaining",
    ]

    for lp in c.get("loop_paths", []):
        lines.append(f"   🔁 {lp.get('protocol','?')} — {lp.get('type','')}")

    lev = c.get("estimated_max_leverage", 1)
    theo = c.get("theoretical_max_yield", 0)
    borrow = c.get("borrow_cost_estimate", 0)
    lines.append(f"   🧮 {lev}x | Borrow: {fmt_pct(borrow)} | Theo yield: {fmt_pct(theo)}")

    mms = c.get("money_markets", [])
    if mms:
        lines.append(f"   🏦 {', '.join(mms)}")
    if c.get("has_contango"):
        lines.append("   ⚡ Contango")

    lines.append(f"   ⭐ {c.get('score', 0)}/100")
    return "\n".join(lines) + "\n"


def no_results_message(chain_name, asset_filter):
    chain = (chain_name or "all chains").capitalize()
    asset = asset_filter or "all assets"
    return (
        f"🔍 Nothing found for *{chain} / {asset}*.\n\n"
        "Try a different chain or fewer filters.\n"
        "Ex: `/loop top 5 eth arbitrum`"
    )
