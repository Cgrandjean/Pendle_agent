"""Pendle loop opportunity scanner using LangGraph."""

import logging

from langgraph.graph import END, START, StateGraph

from agents.config import MIN_TVL, MIN_DAYS_TO_EXPIRY, CHAINS, MIN_BORROW_LIQUIDITY_USD
from utils.fetch_pendle import fetch_all_markets as _fetch_all_pendle_markets
from schemas.agent_state import LoopScoutState
from utils.parsing import days_to_expiry, extract_ticker
from utils.formatting import format_candidate, no_results_message
from utils.fetch_aave import fetch_aave_data
from utils.fetch_morpho import fetch_morpho_data
from utils.fetch_euler import fetch_euler_data
from utils.database import save_scan, save_yield_history

log = logging.getLogger(__name__)

DEFAULT_LTV_FALLBACK = 0.70


def _build_candidate(market, theo_yield, borrow, ltv, leverage, days, spread, protocol, vault_name, 
                     borrow_liquidity=0, borrow_liquidity_tokens=0, borrow_token_symbol="",
                     morpho_unique_key="", morpho_collateral_symbol="", morpho_loan_symbol="",
                     euler_vault_address="", euler_collateral_address="",
                     pt_underlying="", pt_expiry="") -> dict:
    """Build a candidate dict for loop opportunities."""
    # vault_key uniquely identifies a (protocol, specific market) combo for DB history
    if protocol == "morpho":
        vault_key = morpho_unique_key or ""
    elif protocol == "euler":
        # When euler_vault_address is empty (e.g. borrowed asset not resolved),
        # add pt_underlying to ensure uniqueness per PT collateral
        base_key = euler_vault_address or ""
        vault_key = f"{base_key}:{pt_underlying}" if base_key else pt_underlying
    else:
        vault_key = f"{market.get('chainId', 1)}:{borrow_token_symbol}"

    return {
        "address": market.get("address", ""),
        "chain_id": market.get("chainId", 1),
        "name": market.get("name", "") or market.get("symbol", ""),
        "days_to_expiry": round(days, 1),
        "implied_apy": float(market.get("details_impliedApy") or 0),
        "underlying_apy": float(market.get("details_underlyingApy") or 0),
        "spread": spread,
        "pt_discount": float(market.get("details_ptDiscount") or 0),
        "tvl": float(market.get("details_totalTvl") or 0),
        "liquidity": float(market.get("details_liquidity") or 0),
        "theoretical_max_yield": theo_yield,
        "estimated_max_leverage": leverage,
        "estimated_ltv": ltv,
        "borrow_cost_estimate": borrow,
        "borrow_liquidity_usd": borrow_liquidity,
        "borrow_liquidity_tokens": borrow_liquidity_tokens,
        "borrow_token_symbol": borrow_token_symbol,
        "vault_name": vault_name,
        "vault_id": protocol,
        "vault_key": vault_key,
        "morpho_unique_key": morpho_unique_key,
        "morpho_collateral_symbol": morpho_collateral_symbol,
        "morpho_loan_symbol": morpho_loan_symbol,
        "euler_vault_address": euler_vault_address,
        "euler_collateral_address": euler_collateral_address,
        "pt_underlying": pt_underlying,
        "pt_expiry": pt_expiry,
    }




class LoopScoutAgent:
    """LangGraph-based agent for scanning Pendle loop opportunities."""

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self):
        g = StateGraph(LoopScoutState)

        g.add_node("skim_aave", self.skim_aave)
        g.add_node("skim_morpho", self.skim_morpho)
        g.add_node("skim_euler", self.skim_euler)
        g.add_node("collect_markets", self.collect_markets)
        g.add_node("analyze_loops", self.analyze_loops)
        g.add_node("synthesize", self.synthesize)

        g.add_edge(START, "skim_aave")
        g.add_edge(START, "skim_morpho")
        g.add_edge(START, "skim_euler")
        g.add_edge(START, "collect_markets")

        g.add_edge("skim_aave", "analyze_loops")
        g.add_edge("skim_morpho", "analyze_loops")
        g.add_edge("skim_euler", "analyze_loops")
        g.add_edge("collect_markets", "analyze_loops")

        g.add_conditional_edges("analyze_loops", lambda _: "synthesize")
        g.add_edge("synthesize", END)

        return g.compile()

    # -- Parallel fetch nodes --

    async def skim_aave(self, state):
        data = await fetch_aave_data()
        log.info("AAVE: %d PT tokens, %d stable rates",
                 len(data.get("pt_tokens", {})), len(data.get("stable_borrow", {})))
        return {"aave_data": data}

    async def skim_morpho(self, state):
        data = await fetch_morpho_data()
        log.info("Morpho: %d PT markets", len(data.get("pt_markets", [])))
        return {"morpho_data": data}

    async def skim_euler(self, state):
        data = await fetch_euler_data()
        log.info("Euler: %d PT vaults, %d stable vaults",
                 len(data.get("pt_vaults", [])), len(data.get("borrowable_vaults", [])))
        return {"euler_data": data}

    # -- Market collection --

    async def collect_markets(self, state):
        chain_id = state.get("chain_filter")
        chain_name = state.get("chain_name")

        all_markets = await _fetch_all_pendle_markets(
            chain_id, None, MIN_TVL, 0.001,
        )
        active = [m for m in all_markets if days_to_expiry(m.get("expiry")) >= MIN_DAYS_TO_EXPIRY]

        log.info("Markets: %d active / %d raw", len(active), len(all_markets))
        return {"markets": active, "chain_name": chain_name}

    # -- Loop analysis --

    async def analyze_loops(self, state):
        markets = state.get("markets", [])
        morpho_data = state.get("morpho_data") or {}
        aave_data  = state.get("aave_data")  or {}
        euler_data = state.get("euler_data") or {}

        morpho_markets = morpho_data.get("pt_markets", [])
        aave_pt        = aave_data.get("pt_tokens", {})
        euler_borrowable = euler_data.get("borrowable_vaults", [])

        candidates = []

        for market in markets:
            m_addr = market.get("address", "")
            m_chain = market.get("chainId", 1)
            implied = float(market.get("details_impliedApy") or 0)
            underlying = float(market.get("details_underlyingApy") or 0)
            tvl = float(market.get("details_totalTvl") or 0)
            mkt_liquidity = float(market.get("details_liquidity") or 0)
            days = days_to_expiry(market.get("expiry"))
            spread = implied - underlying

            # Pendle market identity (API returns underlying name, e.g. "USDG", "wstETH", not "PT-...-DATE")
            mkt_name = market.get("name", "") or market.get("symbol", "") or ""
            mkt_ticker = extract_ticker(mkt_name)  # already lowercase
            mkt_expiry = (market.get("expiry") or "")[:10]
            if not mkt_ticker or not mkt_expiry:
                continue

            # ── Morpho loops ────────────────────────────────────────────────
            for mm in morpho_markets:
                if mm.get("chain_id", 1) != m_chain:
                    continue

                if mm.get("pt_underlying", "").lower() != mkt_ticker.lower():
                    continue
                if mm.get("pt_expiry") != mkt_expiry:
                    continue

                morpho_liq = float(mm.get("liquidity_usd", 0))
                ltv = float(mm.get("lltv", 0)) or DEFAULT_LTV_FALLBACK
                borrow = float(mm.get("borrow_apy", 0))
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow
                theo_yield = implied + max(net, 0) * (leverage - 1)

                candidates.append(_build_candidate(
                    market, theo_yield, borrow, ltv, leverage, days, spread,
                    "morpho", f"Morpho {mm.get('collateral_symbol', '')}",
                    borrow_liquidity=morpho_liq,
                    borrow_liquidity_tokens=0,
                    morpho_unique_key=mm.get("unique_key", ""),
                    morpho_collateral_symbol=mm.get("collateral_symbol", ""),
                    morpho_loan_symbol=mm.get("loan_symbol", ""),
                    pt_underlying=mkt_ticker,
                    pt_expiry=mkt_expiry,
                ))

            # ── AAVE PT loops ────────────────────────────────────────────────
            stable_data = aave_data.get("stable_borrow") or {}
            for addr, pt_data in aave_pt.items():
                if pt_data.get("pt_underlying", "").lower() != mkt_ticker.lower():
                    continue
                if pt_data.get("pt_expiry") != mkt_expiry:
                    continue
                # Use LTV from AAVE if available, otherwise fallback (AAVE returns 0 for PT collaterals)
                ltv = float(pt_data.get("ltv", 0)) or DEFAULT_LTV_FALLBACK
                if ltv <= 0:
                    continue

                # Best stablecoin to borrow (any state, even low liquidity — keep for yield tracking)
                best_stable = None
                best_stable_liq = 0.0
                for sym, sdata in stable_data.items():
                    stable_liq = sdata.get("available_liquidity_usd", 0)
                    if sdata.get("borrowing_state") == "BORROWING":
                        if best_stable is None or stable_liq > best_stable_liq:
                            best_stable = sdata
                            best_stable_liq = stable_liq

                if best_stable is None:
                    continue

                borrow = float(best_stable.get("borrow_apy", 0))
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow
                theo_yield = implied + max(net, 0) * (leverage - 1)

                candidates.append(_build_candidate(
                    market, theo_yield, borrow, ltv, leverage, days, spread,
                    "aavev3", f"AAVE {pt_data.get('symbol', '')} / {best_stable['symbol']}",
                    borrow_liquidity=best_stable.get("available_liquidity_usd", 0),
                    borrow_liquidity_tokens=0,
                    borrow_token_symbol=best_stable.get("symbol", ""),
                    pt_underlying=mkt_ticker,
                    pt_expiry=mkt_expiry,
                ))

            # ── Euler borrowable vault loops ────────────────────────────────
            for bv in euler_borrowable:
                if bv.get("chain_id", 1) != m_chain:
                    continue
                borrow_pct = float(bv.get("borrow_apy_pct", 0)) / 100
                if borrow_pct <= 0:
                    continue

                # Check if this vault accepts a PT matching our market
                matched_pt_col = None
                for pt_col in bv.get("pt_collaterals", []):
                    if pt_col.get("pt_underlying", "").lower() == mkt_ticker.lower() and pt_col.get("pt_expiry") == mkt_expiry:
                        matched_pt_col = pt_col
                        break

                if not matched_pt_col:
                    continue

                # cash is in token units (not USD) — keep for display, flag via has_liquidity
                euler_cash_tokens = float(bv.get("cash", 0))
                ltv = DEFAULT_LTV_FALLBACK
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow_pct
                theo_yield = implied + max(net, 0) * (leverage - 1)

                borrow_vault = bv.get("symbol", "?")
                vault_name = f"Euler {borrow_vault} ({borrow_pct*100:.2f}%) ⟶ {matched_pt_col.get('symbol', '')}"
                euler_vault_address = bv.get("evault", "")
                euler_collateral_address = matched_pt_col.get("evault", "") or ""

                candidates.append(_build_candidate(
                    market, theo_yield, borrow_pct, ltv, leverage, days, spread,
                    "euler", vault_name,
                    borrow_liquidity=0,  # cash is in tokens, not USD — flag only
                    borrow_liquidity_tokens=euler_cash_tokens,
                    borrow_token_symbol=borrow_vault,
                    euler_vault_address=euler_vault_address,
                    euler_collateral_address=euler_collateral_address,
                    pt_underlying=mkt_ticker,
                    pt_expiry=mkt_expiry,
                ))

        candidates.sort(key=lambda c: c["theoretical_max_yield"], reverse=True)
        log.info("Found %d loop candidates", len(candidates))
        return {"loop_candidates": candidates}

    # -- Output synthesis --

    async def synthesize(self, state):
        candidates = state.get("loop_candidates", [])
        count = state.get("count", 5)
        top = candidates[:count]

        if not top:
            return {"output": no_results_message(state.get("chain_name"))}

        chain = (state.get("chain_name") or "all chains").capitalize()

        parts = [f"🔄 *Loop Scout — {chain}*\n_{len(candidates)} candidate(s), top {len(top)}:_\n"]
        for i, c in enumerate(top, 1):
            parts.append(format_candidate(i, c))
        parts.append("\n⚠️ *Disclaimer* — Theoretical estimated yields. Verify actual LTV/borrow rates. Bot is read-only. DYOR.")

        return {"output": "\n".join(parts)}

    # -- Public API --

    async def run(self, count: int = 5, chain: str | None = None) -> str:
        chain_id = CHAINS.get(chain) if chain else None
        chain_name = chain

        state: LoopScoutState = {
            "chain_filter": chain_id,
            "chain_name": chain_name,
            "count": count,
            "markets": [],
            "loop_candidates": [],
            "output": "",
        }
        result = await self.graph.ainvoke(state)
        candidates = result.get("loop_candidates", [])

        try:
            save_scan(
                query=f"count={count} chain={chain}",
                chain=chain_name,
                candidates=candidates,
            )
            save_yield_history(candidates)
        except Exception as e:
            log.warning("DB save failed: %s", e)

        return result.get("output", "Internal error.")
