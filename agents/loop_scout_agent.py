"""Pendle loop opportunity scanner using LangGraph."""

import logging

from langgraph.graph import END, START, StateGraph

from agents.config import MIN_TVL, MIN_DAYS_TO_EXPIRY, CHAINS, MIN_BORROW_LIQUIDITY_USD
from utils.fetch_pendle import fetch_all_markets as _fetch_all_pendle_markets
from schemas.agent_state import LoopScoutState
from utils.parsing import (
    days_to_expiry, matches_asset_family, detect_asset_family,
    extract_ticker, pt_matches_market,
)
from utils.formatting import format_candidate, no_results_message
from utils.scoring import score_candidate
from utils.fetch_aave import fetch_aave_data
from utils.fetch_morpho import fetch_morpho_data
from utils.fetch_euler import fetch_euler_data
from utils.database import save_scan, save_yield_history

log = logging.getLogger(__name__)

# Default LTV by asset family
DEFAULT_LTV = {"stable": 0.90, "eth": 0.80, "btc": 0.75}
DEFAULT_LTV_FALLBACK = 0.70


def _build_candidate(market, theo_yield, borrow, ltv, leverage, days, family, spread, score, protocol, vault_name, 
                     borrow_liquidity=0, borrow_liquidity_tokens=0, borrow_token_symbol="",
                     morpho_unique_key="", morpho_collateral_symbol="", morpho_loan_symbol="",
                     euler_vault_address="", euler_collateral_address="") -> dict:
    """Build a candidate dict for loop opportunities."""
    return {
        # Identity
        "address": market.get("address", ""),
        "chain_id": market.get("chainId", 1),
        "name": market.get("name", "") or market.get("symbol", ""),
        "days_to_expiry": round(days, 1),
        # Pendle market data
        "implied_apy": float(market.get("details_impliedApy") or 0),
        "underlying_apy": float(market.get("details_underlyingApy") or 0),
        "spread": spread,
        "pt_discount": float(market.get("details_ptDiscount") or 0),
        "tvl": float(market.get("details_totalTvl") or 0),
        "liquidity": float(market.get("details_liquidity") or 0),
        # Loop math
        "theoretical_max_yield": theo_yield,
        "estimated_max_leverage": leverage,
        "estimated_ltv": ltv,
        "borrow_cost_estimate": borrow,
        "borrow_liquidity_usd": borrow_liquidity,
        "borrow_liquidity_tokens": borrow_liquidity_tokens,
        "borrow_token_symbol": borrow_token_symbol,
        "asset_family": family,
        "score": score,
        # Protocol
        "vault_name": vault_name,
        "vault_id": protocol,
        # Morpho deep link
        "morpho_unique_key": morpho_unique_key,
        "morpho_collateral_symbol": morpho_collateral_symbol,
        "morpho_loan_symbol": morpho_loan_symbol,
        # Euler deep link
        "euler_vault_address": euler_vault_address,
        "euler_collateral_address": euler_collateral_address,
    }


class LoopScoutAgent:
    """LangGraph-based agent for scanning Pendle loop opportunities."""

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the LangGraph workflow."""
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
                 len(data.get("pt_vaults", [])), len(data.get("stable_vaults", [])))
        return {"euler_data": data}

    # -- Market collection --

    async def collect_markets(self, state):
        chain_id = state.get("chain_filter")
        asset_filter = state.get("asset_filter")
        chain_name = state.get("chain_name")

        all_markets = await _fetch_all_pendle_markets(
            chain_id, asset_filter, MIN_TVL, 0.001,
        )
        active = self._filter_markets(all_markets, asset_filter=None)

        log.info("Markets: %d active / %d raw", len(active), len(all_markets))
        return {"markets": active, "chain_name": chain_name}

    @staticmethod
    def _filter_markets(markets: list, asset_filter: str | None) -> list:
        active = []
        for m in markets:
            days = days_to_expiry(m.get("expiry"))
            if 0 <= days < MIN_DAYS_TO_EXPIRY:
                continue
            if asset_filter:
                name = m.get("name", "") or m.get("symbol", "") or ""
                if not matches_asset_family(name, asset_filter):
                    continue
            active.append(m)
        return active

    # -- Loop analysis --

    async def analyze_loops(self, state):
        """Find loops by matching Pendle markets against PT tokens from lending protocols."""
        markets = state.get("markets", [])
        morpho_data = state.get("morpho_data") or {}
        aave_data = state.get("aave_data") or {}
        euler_data = state.get("euler_data") or {}

        morpho = morpho_data.get("pt_markets", [])
        aave_pt = aave_data.get("pt_tokens", {})
        euler_borrowable = euler_data.get("borrowable_vaults", [])

        # Debug: log all PT markets from each protocol
        for mkt in morpho:
            log.debug("Morpho PT: %s (chain=%d, liq=$%.0f, borrow=%.2f%%)",
                      mkt.get("collateral_symbol"), mkt.get("chain_id", 0),
                      float(mkt.get("liquidity_usd", 0)), float(mkt.get("borrow_apy", 0)) * 100)
        for addr, pt in aave_pt.items():
            log.debug("AAVE PT: %s (collateral=%s, ltv=%.2f)",
                      pt.get("symbol"), pt.get("can_be_collateral"), float(pt.get("ltv", 0)))
        for bv in euler_borrowable:
            for pt_col in bv.get("pt_collaterals", []):
                log.debug("Euler borrowable: %s (chain=%d, borrow=%.2f%%) accepts %s",
                          bv.get("symbol"), bv.get("chain_id", 0),
                          float(bv.get("borrow_apy_pct", 0)), pt_col.get("symbol"))

        candidates = []

        for market in markets:
            m_name = market.get("name", "") or market.get("symbol", "") or ""
            m_chain = market.get("chainId", 1)
            implied = float(market.get("details_impliedApy") or 0)
            underlying = float(market.get("details_underlyingApy") or 0)
            tvl = float(market.get("details_totalTvl") or 0)
            liq = float(market.get("details_liquidity") or 0)
            days = days_to_expiry(market.get("expiry"))
            family = detect_asset_family(m_name)
            spread = implied - underlying
            default_ltv = DEFAULT_LTV.get(family, DEFAULT_LTV_FALLBACK)

            # ── Morpho loops ───────────────────────────────────────────────
            for mkt in morpho:
                if mkt.get("chain_id", 1) != m_chain:
                    continue
                col = mkt.get("collateral_symbol", "")
                if not pt_matches_market(col, m_name):
                    continue
                # Check borrow liquidity
                morpho_liq = float(mkt.get("liquidity_usd", 0))
                if morpho_liq < MIN_BORROW_LIQUIDITY_USD:
                    continue
                ltv = float(mkt.get("lltv", 0)) or default_ltv
                borrow = float(mkt.get("borrow_apy", 0))
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow
                theo_yield = implied + max(net, 0) * (leverage - 1)
                sc = score_candidate(implied, spread, tvl, liq, days, 1, 
                                     borrow_cost=borrow, pt_discount=market.get("details_ptDiscount", 0), 
                                     leverage=leverage)
                candidates.append(_build_candidate(
                    market, theo_yield, borrow, ltv, leverage, days, family, spread, sc,
                    "morpho", f"Morpho {col}", borrow_liquidity=morpho_liq,
                    morpho_unique_key=mkt.get("unique_key", ""),
                    morpho_collateral_symbol=mkt.get("collateral_symbol", ""),
                    morpho_loan_symbol=mkt.get("loan_symbol", "")))

            # ── AAVE PT loops ──────────────────────────────────────────────
            stable_data = aave_data.get("stable_borrow") or {}
            for addr, pt_data in aave_pt.items():
                pt_sym = pt_data.get("symbol", "")
                if not pt_matches_market(pt_sym, m_name):
                    continue
                if not pt_data.get("can_be_collateral", False):
                    continue
                ltv = float(pt_data.get("ltv", 0)) or default_ltv
                if ltv <= 0:
                    continue

                # Best stablecoin to borrow with sufficient liquidity
                best_stable = None
                for sym, sdata in stable_data.items():
                    liq = sdata.get("available_liquidity_usd", 0)
                    if liq >= MIN_BORROW_LIQUIDITY_USD and sdata.get("borrowing_state") == "BORROWING":
                        if best_stable is None or liq > best_stable["available_liquidity_usd"]:
                            best_stable = sdata

                if best_stable is None:
                    continue

                borrow = float(best_stable.get("borrow_apy", 0))
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow
                theo_yield = implied + max(net, 0) * (leverage - 1)
                sc = score_candidate(implied, spread, tvl, liq, days, 1, 
                                     borrow_cost=borrow, pt_discount=market.get("details_ptDiscount", 0), 
                                     leverage=leverage)
                candidates.append(_build_candidate(
                    market, theo_yield, borrow, ltv, leverage, days, family, spread, sc,
                    "aavev3", f"AAVE {pt_sym} / {best_stable['symbol']}", 
                    borrow_liquidity=best_stable.get("available_liquidity_usd", 0)))

            # ── Euler borrowable vault loops (PT as collateral) ─────────────
            # euler_borrowable contains vaults that accept PT as collateral
            # These have real borrow rates unlike PT vaults which are supply-only
            for bv in euler_borrowable:
                if bv.get("chain_id", 1) != m_chain:
                    continue
                borrow_pct = float(bv.get("borrow_apy_pct", 0)) / 100
                if borrow_pct <= 0:
                    continue
                
                # Check if this vault accepts a PT matching our market (by ticker + expiry)
                matched_pt = None
                matched_pt_evault = ""
                market_expiry = market.get("expiry")
                for pt_col in bv.get("pt_collaterals", []):
                    pt_sym = pt_col.get("symbol", "")
                    if pt_matches_market(pt_sym, m_name, market_expiry):
                        matched_pt = pt_sym
                        matched_pt_evault = pt_col.get("evault", "")
                        break
                
                if not matched_pt:
                    continue
                
                # Estimate liquidity (cash in vault as USD approximation)
                euler_liq_usd = float(bv.get("cash", 0))
                if euler_liq_usd < MIN_BORROW_LIQUIDITY_USD:
                    continue
                
                ltv = default_ltv
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow_pct
                theo_yield = implied + max(net, 0) * (leverage - 1)
                sc = score_candidate(implied, spread, tvl, liq, days, 1, 
                                     borrow_cost=borrow_pct, pt_discount=market.get("details_ptDiscount", 0), 
                                     leverage=leverage)
                # Show the borrow vault name (stable vault) with borrow rate
                borrow_vault = bv.get("symbol", "?")
                vault_name = f"Euler {borrow_vault} ({borrow_pct*100:.2f}%) ⟶ {matched_pt}"
                vault_symbol = borrow_vault
                # Get evault addresses for deep link
                euler_vault_address = bv.get("evault", "")
                euler_collateral_address = matched_pt_evault or ""
                candidates.append(_build_candidate(
                    market, theo_yield, borrow_pct, ltv, leverage, days, family, spread, sc,
                    "euler", vault_name, borrow_liquidity=euler_liq_usd,
                    borrow_liquidity_tokens=euler_liq_usd, borrow_token_symbol=vault_symbol,
                    euler_vault_address=euler_vault_address, euler_collateral_address=euler_collateral_address))

        candidates.sort(key=lambda c: c["theoretical_max_yield"], reverse=True)
        log.info("Found %d loop candidates", len(candidates))
        return {"loop_candidates": candidates}

    # -- Output synthesis --

    async def synthesize(self, state):
        candidates = state.get("loop_candidates", [])
        count = state.get("count", 5)
        top = candidates[:count]

        if not top:
            return {"output": no_results_message(state.get("chain_name"), state.get("asset_filter"))}

        chain = (state.get("chain_name") or "toutes chaînes").capitalize()
        asset = state.get("asset_filter") or "tous actifs"

        parts = [f"🔄 *Loop Scout — {chain} / {asset}*\n_{len(candidates)} candidat(s), top {len(top)} :_\n"]
        for i, c in enumerate(top, 1):
            parts.append(format_candidate(i, c))
        parts.append("\n⚠️ *Disclaimer* — Rendements théoriques estimés. Vérifiez LTV/borrow réels. Bot read-only. DYOR.")

        return {"output": "\n".join(parts)}

    # -- Public API --

    async def run(self, count: int = 5, asset: str | None = None, chain: str | None = None) -> str:
        """Run the loop scout with explicit parameters."""
        chain_id = CHAINS.get(chain) if chain else None
        chain_name = chain

        state: LoopScoutState = {
            "chain_filter": chain_id,
            "chain_name": chain_name,
            "asset_filter": asset,
            "count": count,
            "markets": [],
            "loop_candidates": [],
            "output": "",
        }
        result = await self.graph.ainvoke(state)
        candidates = result.get("loop_candidates", [])

        try:
            save_scan(
                query=f"count={count} asset={asset} chain={chain}",
                chain=chain_name,
                asset_filter=asset,
                candidates=candidates,
            )
            save_yield_history(candidates)
        except Exception as e:
            log.warning("DB save failed: %s", e)

        return result.get("output", "Erreur interne.")
