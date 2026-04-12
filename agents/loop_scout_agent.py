"""Pendle loop opportunity scanner using LangGraph."""

import logging

from langgraph.graph import END, START, StateGraph

from agents.config import MIN_TVL, MIN_DAYS_TO_EXPIRY
from utils.fetch_pendle import fetch_all_markets as _fetch_all_pendle_markets
from schemas.agent_state import LoopScoutState
from utils.parsing import days_to_expiry, matches_asset_family, detect_asset_family
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


def _pt_matches(pt_sym: str, market_name: str) -> bool:
    """Check if a PT collateral symbol matches a Pendle market name."""
    key = pt_sym.lower().replace("-", " ").replace("pt-", "").replace("pt", "")
    name = market_name.lower().replace("-", " ").replace("pt-", "").replace("pt", "")
    return key in name or name in key


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
        count = state.get("count", 5)
        chain_name = state.get("chain_name")

        all_markets = await _fetch_all_pendle_markets(
            chain_id,
            asset_filter,
            MIN_TVL,
            0.001,
        )
        active = self._filter_markets(all_markets, asset_filter=None)

        log.info("Markets: %d active / %d raw", len(active), len(all_markets))
        return {
            "markets": active,
            "chain_name": chain_name,
        }

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
        euler_pt = euler_data.get("pt_vaults", [])
        euler_stable = euler_data.get("stable_vaults", [])

        # Build Euler vault address -> vault map for resolving collateral vaults
        euler_vault_map = {}
        for v in euler_pt + euler_stable:
            ev = v.get("evault", "")
            if ev:
                euler_vault_map[ev.lower()] = v

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
                if not _pt_matches(col, m_name):
                    continue
                ltv = float(mkt.get("lltv", 0)) or default_ltv
                borrow = float(mkt.get("borrow_apy", 0))
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow
                theo_yield = implied + max(net, 0) * (leverage - 1)
                score = score_candidate(implied, spread, tvl, liq, days, 1, False)
                pendle_url, vault_url = self._build_urls(market, "morpho", mkt)
                candidates.append(self._make_candidate(market, theo_yield, borrow, ltv, leverage, days, family, spread, score, "morpho", f"Morpho {col}", pendle_url, vault_url))

            # ── AAVE PT loops ──────────────────────────────────────────────
            # AAVE: deposit PT as collateral, borrow stablecoin (USDC/USDT/etc.)
            # For each PT token that can be collateral, find the best stablecoin borrow rate
            stable_data = aave_data.get("stable_borrow") or {}
            for addr, pt_data in aave_pt.items():
                pt_sym = pt_data.get("symbol", "")
                if not _pt_matches(pt_sym, m_name):
                    continue
                # Only consider PT tokens that can be used as collateral on AAVE
                if not pt_data.get("can_be_collateral", False):
                    continue
                ltv = float(pt_data.get("ltv", 0)) or default_ltv
                if ltv <= 0:
                    continue

                # Find the best stablecoin to borrow (highest available liquidity)
                best_stable = None
                for sym, sdata in stable_data.items():
                    if sdata.get("borrowing_state") == "BORROWING" and sdata.get("available_liquidity_usd", 0) > 0:
                        if best_stable is None or sdata["available_liquidity_usd"] > best_stable["available_liquidity_usd"]:
                            best_stable = sdata

                if best_stable is None:
                    continue

                borrow = float(best_stable.get("borrow_apy", 0))
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow
                theo_yield = implied + max(net, 0) * (leverage - 1)
                score = score_candidate(implied, spread, tvl, liq, days, 1, False)
                pendle_url, vault_url = self._build_urls(market, "aavev3", pt_data)
                candidates.append(self._make_candidate(market, theo_yield, borrow, ltv, leverage, days, family, spread, score, "aavev3", f"AAVE {pt_sym} / {best_stable['symbol']}", pendle_url, vault_url))

            # ── Euler PT vault loops ─────────────────────────────────────────
            for v in euler_pt:
                if v.get("chain_id", 1) != m_chain:
                    continue
                vault_sym = v.get("symbol", "")
                if not _pt_matches(vault_sym, m_name):
                    continue
                ltv = default_ltv
                borrow_pct = float(v.get("borrow_apy_pct", 0)) / 100
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow_pct
                theo_yield = implied + max(net, 0) * (leverage - 1)
                score = score_candidate(implied, spread, tvl, liq, days, 1, False)
                pendle_url, vault_url = self._build_urls(market, "euler", v)
                candidates.append(self._make_candidate(market, theo_yield, borrow_pct, ltv, leverage, days, family, spread, score, "euler", f"Euler {vault_sym}", pendle_url, vault_url))

            # ── Euler stable vault loops (reverse: stable vault accepts PT collateral) ──
            # Build Pendle PT address lookup for this market's chain
            chain_prefix = f"{m_chain}-"
            pt_addr_raw = (market.get("pt") or "").lower()
            pt_addr_key = (chain_prefix + pt_addr_raw) if not pt_addr_raw.startswith(chain_prefix) else pt_addr_raw

            for sv in euler_stable:
                if sv.get("chain_id", 1) != m_chain:
                    continue
                if float(sv.get("borrow_apy_pct", 0)) <= 0:
                    continue
                collaterals = sv.get("collaterals") or []
                if not collaterals:
                    continue

                matched_col_vault = None
                for col_addr in collaterals:
                    col_lower = col_addr.lower()
                    # Check direct PT address match (Pendle may use chain prefix like "1-0x...")
                    if col_lower == pt_addr_raw or col_lower == pt_addr_key:
                        matched_col_vault = None  # direct PT match, no intermediate vault
                        break
                    # Check if collateral is an Euler PT vault whose underlying is this PT
                    col_vault = euler_vault_map.get(col_lower)
                    if col_vault and _pt_matches(col_vault.get("symbol", ""), m_name):
                        matched_col_vault = col_vault
                        break

                if matched_col_vault is None and col_lower != pt_addr_raw and col_lower != pt_addr_key:
                    continue  # no match found for this stable vault

                borrow_pct = float(sv.get("borrow_apy_pct", 0)) / 100
                ltv = default_ltv
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - borrow_pct
                theo_yield = implied + max(net, 0) * (leverage - 1)
                score = score_candidate(implied, spread, tvl, liq, days, 1, False)
                vault_name = f"Euler {sv.get('symbol', '?')} (collateral: {market.get('name', m_name)[:30]})"
                pendle_url, vault_url = self._build_urls(market, "euler", sv)
                candidates.append(self._make_candidate(market, theo_yield, borrow_pct, ltv, leverage, days, family, spread, score, "euler", vault_name, pendle_url, vault_url))

        # Sort but don't dedupe — list all vault variants separately
        candidates.sort(key=lambda c: c["theoretical_max_yield"], reverse=True)

        log.info("Found %d loop candidates", len(candidates))
        return {"loop_candidates": candidates}

    def _build_urls(self, market, protocol, proto_data):
        """Build Pendle and protocol URLs for a candidate."""
        from agents.config import CHAINS

        addr = market.get("address", "")
        chain_id = market.get("chainId", 1)
        # Chain name for Pendle URL (e.g., "ethereum", "arbitrum")
        chain_name = next((k for k, v in CHAINS.items() if v == chain_id), "ethereum")

        pendle_url = f"https://app.pendle.finance/trade/markets/{addr}/swap?view=pt"

        # Protocol-specific URL
        vault_url = ""
        if protocol == "morpho":
            morpho_addr = proto_data.get("unique_key", "")
            morpho_symbol = proto_data.get("collateral_symbol", "").lower().replace(" ", "-").replace("_", "-")
            if morpho_addr and morpho_symbol:
                vault_url = f"https://app.morpho.org/{chain_name}/market/{morpho_addr}/{morpho_symbol}#overview"
        elif protocol == "euler":
            evault = proto_data.get("evault", "")
            vault_url = f"https://app.euler.finance/vault/{evault}" if evault else ""
        elif protocol == "aavev3":
            vault_url = "https://app.aave.com"

        return pendle_url, vault_url

    @staticmethod
    def _make_candidate(market, theo_yield, borrow, ltv, leverage, days, family, spread, score, protocol, vault_name, pendle_url, vault_url) -> dict:
        yield_at_expiry = theo_yield * (days / 365) if days > 0 else 0
        return {
            "address": market.get("address", ""),
            "chain_id": market.get("chainId"),
            "name": market.get("name", "") or market.get("symbol", ""),
            "symbol": market.get("symbol", ""),
            "protocol": market.get("protocol", ""),
            "expiry": market.get("expiry"),
            "days_to_expiry": round(days, 1),
            "implied_apy": float(market.get("details_impliedApy") or 0),
            "underlying_apy": float(market.get("details_underlyingApy") or 0),
            "spread": spread,
            "pt_discount": float(market.get("details_ptDiscount") or 0),
            "tvl": float(market.get("details_totalTvl") or 0),
            "liquidity": float(market.get("details_liquidity") or 0),
            "yt_floating_apy": float(market.get("details_ytFloatingApy") or 0),
            "aggregated_apy": float(market.get("details_aggregatedApy") or 0),
            "pendle_apy": float(market.get("details_pendleApy") or 0),
            "max_boosted_apy": float(market.get("details_maxBoostedApy") or 0),
            "asset_family": family,
            "estimated_max_leverage": leverage,
            "estimated_ltv": ltv,
            "borrow_cost_estimate": borrow,
            "theoretical_max_yield": theo_yield,
            "yield_at_expiry": yield_at_expiry,
            "vault_name": vault_name,
            "vault_id": protocol,
            "borrow_detail": f"{protocol} borrow",
            "money_markets": [vault_name],
            "yield_strategies": [],
            "has_contango": False,
            "score": score,
            "pendle_url": pendle_url,
            "vault_url": vault_url,
        }

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
        """Run the loop scout with explicit parameters.

        Args:
            count: number of top results to return
            asset: asset family filter ("stable", "eth", "btc")
            chain: chain name ("ethereum", "arbitrum", "base", etc.)
        """
        from agents.config import CHAINS

        chain_id = CHAINS.get(chain) if chain else None
        chain_name = chain

        state: LoopScoutState = {
            "chain_filter": chain_id,
            "chain_name": chain_name,
            "asset_filter": asset,
            "count": count,
            "chains": [],
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
