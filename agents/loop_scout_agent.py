"""Pendle loop opportunity scanner using LangGraph."""

import asyncio
import logging
import re

from langgraph.graph import END, START, StateGraph

from agents import pendle_mcp
from agents.config import CHAINS, ASSET_FAMILIES, MIN_TVL, MIN_DAYS_TO_EXPIRY
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

# Fallback chain IDs
FALLBACK_CHAINS = [1, 42161, 8453, 10, 56, 5000, 146]

# Market fetch limit per chain
MARKET_LIMIT = 50


class LoopScoutAgent:
    """LangGraph-based agent for scanning Pendle loop opportunities."""

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the LangGraph workflow."""
        g = StateGraph(LoopScoutState)

        # Nodes
        g.add_node("skim_aave", self.skim_aave)
        g.add_node("skim_morpho", self.skim_morpho)
        g.add_node("skim_euler", self.skim_euler)
        g.add_node("collect_markets", self.collect_markets)
        g.add_node("collect_protocols", self.collect_protocols)
        g.add_node("analyze_loops", self.analyze_loops)
        g.add_node("synthesize", self.synthesize)

        # Fan-out from START
        g.add_edge(START, "skim_aave")
        g.add_edge(START, "skim_morpho")
        g.add_edge(START, "skim_euler")
        g.add_edge(START, "collect_markets")

        # Fan-in before collect_protocols
        g.add_edge("skim_aave", "collect_protocols")
        g.add_edge("skim_morpho", "collect_protocols")
        g.add_edge("skim_euler", "collect_protocols")
        g.add_conditional_edges("collect_markets", self._after_markets)

        g.add_edge("collect_protocols", "analyze_loops")
        g.add_conditional_edges("analyze_loops", lambda _: "synthesize")
        g.add_edge("synthesize", END)

        return g.compile()

    @staticmethod
    def _after_markets(state):
        """Route to synthesize if no markets found, otherwise continue."""
        return "synthesize" if not state.get("markets") else "collect_protocols"

    # -- Skim nodes (parallel execution) --

    async def skim_aave(self, state):
        """Fetch AAVE data."""
        data = await self._run_sync(fetch_aave_data)
        log.info("AAVE: %d PT tokens, %d stable rates",
                 len(data.get("pt_tokens", {})), len(data.get("stable_borrow", {})))
        return {"aave_data": data}

    async def skim_morpho(self, state):
        """Fetch Morpho data."""
        data = await self._run_sync(fetch_morpho_data, 5000)
        log.info("Morpho: %d PT markets", len(data.get("pt_markets", [])))
        return {"morpho_data": data}

    async def skim_euler(self, state):
        """Fetch Euler data."""
        data = await self._run_sync(fetch_euler_data, 100)
        log.info("Euler: %d PT vaults, %d stable vaults",
                 len(data.get("pt_vaults", [])), len(data.get("stable_vaults", [])))
        return {"euler_data": data}

    @staticmethod
    async def _run_sync(func, *args):
        """Run a synchronous function in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args))

    # -- Query parsing --

    @staticmethod
    def _parse_query(query: str) -> dict:
        """Parse user query into chain, asset, and count filters."""
        low = query.lower().strip()

        # Parse chain
        chain_id = chain_name = None
        for kw, cid in CHAINS.items():
            if re.search(rf"\b{re.escape(kw)}\b", low):
                chain_id, chain_name = cid, kw
                break

        # Parse asset family
        asset_filter = None
        for family, keywords in ASSET_FAMILIES.items():
            if any(re.search(rf"\b{re.escape(k)}\b", low) for k in keywords):
                asset_filter = family
                break

        # Parse count (e.g., "top 10")
        count = 5
        m = re.search(r"top\s*(\d+)", low)
        if m:
            count = min(int(m.group(1)), 20)

        log.info("Intent: chain=%s asset=%s count=%d", chain_name, asset_filter, count)
        return {"chain_id": chain_id, "chain_name": chain_name, "asset_filter": asset_filter, "count": count}

    # -- Market collection --

    async def collect_markets(self, state):
        """Fetch and filter Pendle markets."""
        parsed = self._parse_query(state.get("query", ""))
        chain_id = parsed["chain_id"]
        chain_name = parsed["chain_name"]
        asset_filter = parsed["asset_filter"]
        count = parsed["count"]

        filters = [
            {"field": "details_impliedApy", "op": ">", "value": 0.001},
            {"field": "details_totalTvl", "op": ">=", "value": MIN_TVL},
        ]

        all_markets = await self._fetch_markets(chain_id, filters)
        active = self._filter_markets(all_markets, asset_filter)

        log.info("Markets: %d active / %d raw", len(active), len(all_markets))
        return {
            "markets": active,
            "chain_filter": chain_id,
            "chain_name": chain_name,
            "asset_filter": asset_filter,
            "count": count,
        }

    async def _fetch_markets(self, chain_id: int | None, filters: list) -> list:
        """Fetch markets from Pendle API."""
        if chain_id:
            return await self._fetch_single_chain(chain_id, filters)

        # Fetch from all chains
        try:
            chains = await pendle_mcp.get_chains()
            if not isinstance(chains, list):
                chains = FALLBACK_CHAINS
        except Exception:
            chains = FALLBACK_CHAINS

        all_markets = []
        for c in chains:
            try:
                markets = await self._fetch_single_chain(c, filters)
                all_markets.extend(markets)
            except Exception as e:
                log.warning("Markets chain %d: %s", c, e)
        return all_markets

    async def _fetch_single_chain(self, chain_id: int, filters: list) -> list:
        """Fetch markets for a single chain."""
        try:
            result = await pendle_mcp.get_markets(
                chain_id=chain_id,
                filters=filters,
                sort_field="details_impliedApy",
                sort_dir="desc",
                limit=MARKET_LIMIT,
            )
            return result if isinstance(result, list) else []
        except Exception as e:
            log.error("Markets chain %d: %s", chain_id, e)
            return []

    @staticmethod
    def _filter_markets(markets: list, asset_filter: str | None) -> list:
        """Filter markets by expiry and asset family."""
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

    # -- Protocol enrichment --

    async def collect_protocols(self, state):
        """Enrich markets with external protocol data."""
        markets = state.get("markets", [])
        enriched = []
        for m in markets:
            protos = await self._fetch_protocols(m.get("chainId"), m.get("address", ""))
            enriched.append({**m, "external_protocols": protos})

        log.info("Enriched %d markets", len(enriched))
        return {"enriched_markets": enriched}

    @staticmethod
    async def _fetch_protocols(chain_id: int, address: str) -> list:
        """Fetch external protocols for a market."""
        try:
            result = await pendle_mcp.get_external_protocols(chain_id=chain_id, market=address)
            if isinstance(result, dict):
                return result.get("protocols", [])
            if isinstance(result, list):
                return result
        except Exception as e:
            log.warning("Protocols %s: %s", address[:10], e)
        return []

    # -- Borrow rate lookup --

    @staticmethod
    def _build_borrow_lookup(state: dict) -> dict:
        """Build a lookup table for borrow rates across protocols."""
        lookup = {"morpho": [], "euler": [], "aave": []}

        # Morpho
        for mkt in (state.get("morpho_data") or {}).get("pt_markets", []):
            lookup["morpho"].append({
                "col": mkt.get("collateral_symbol", ""),
                "loan": mkt.get("loan_symbol", ""),
                "rate": mkt.get("borrow_apy", 0),
                "lltv": mkt.get("lltv", 0),
            })

        # Euler
        for v in (state.get("euler_data") or {}).get("stable_vaults", []):
            if v.get("rate_pct", 0) > 0.5 and v.get("cash", 0) > 100_000:
                lookup["euler"].append({
                    "sym": v.get("symbol", ""),
                    "rate": v.get("rate_pct", 0) / 100,
                })

        # AAVE
        for sym, d in (state.get("aave_data") or {}).get("stable_borrow", {}).items():
            if d.get("borrow_apy", 0) > 0:
                lookup["aave"].append({"sym": sym, "rate": d.get("borrow_apy", 0)})

        return lookup

    @staticmethod
    def _find_best_borrow(name: str, asset_family: str, protocol_id: str, lookup: dict) -> tuple:
        """Find the cheapest borrow rate for a protocol. Returns (rate, ltv, detail)."""
        low = name.lower()

        if protocol_id == "morpho":
            return LoopScoutAgent._find_morpho_borrow(low, lookup["morpho"])
        elif protocol_id == "euler":
            return LoopScoutAgent._find_euler_borrow(lookup["euler"])
        elif protocol_id in ("aave", "aavev3"):
            return LoopScoutAgent._find_aave_borrow(asset_family, lookup["aave"])
        return (0, 0, "")

    @staticmethod
    def _find_morpho_borrow(low: str, markets: list) -> tuple:
        """Find best Morpho borrow rate."""
        best = None
        for m in markets:
            col_parts = [k for k in m["col"].lower().split("-") if len(k) > 2]
            if any(k in low for k in col_parts):
                if best is None or m["rate"] < best[0]:
                    best = (m["rate"], m["lltv"], f"Morpho {m['col']}/{m['loan']}")
        return best or (0, 0, "")

    @staticmethod
    def _find_euler_borrow(vaults: list) -> tuple:
        """Find best Euler borrow rate."""
        best = None
        for v in vaults:
            if best is None or v["rate"] < best[0]:
                best = (v["rate"], 0.80, f"Euler {v['sym']}")
        return best or (0, 0, "")

    @staticmethod
    def _find_aave_borrow(asset_family: str, assets: list) -> tuple:
        """Find best AAVE borrow rate."""
        stables = ["USDC", "USDT", "USDS", "USDE", "GHO", "PYUSD"] if asset_family == "stable" else ["USDC", "USDT"]
        best = None
        for a in assets:
            if a["sym"] in stables:
                if best is None or a["rate"] < best[0]:
                    best = (a["rate"], 0, f"AAVE {a['sym']}")
        return best or (0, 0, "")

    # -- Loop analysis --

    async def analyze_loops(self, state):
        """Analyze loop opportunities across all markets."""
        enriched = state.get("enriched_markets", [])
        lookup = self._build_borrow_lookup(state)
        candidates = []

        for market in enriched:
            market_candidates = self._analyze_market(market, lookup)
            candidates.extend(market_candidates)

        # Deduplicate: keep best vault per (name, chain, vault) combo
        deduped = self._deduplicate_candidates(candidates)
        log.info("Found %d loop candidates", len(deduped))
        return {"loop_candidates": deduped}

    def _analyze_market(self, market: dict, lookup: dict) -> list:
        """Analyze a single market for loop opportunities."""
        protos = market.get("external_protocols", [])
        mms = [p for p in protos if p.get("category", "").lower() == "money market"]
        ys = [p for p in protos if p.get("category", "").lower() == "yield strategy"]
        has_contango = any(p.get("id") == "contango" for p in protos)

        if not mms and not has_contango:
            return []

        # Extract market data
        name = market.get("name", "") or market.get("symbol", "") or ""
        implied = float(market.get("details_impliedApy") or 0)
        underlying = float(market.get("details_underlyingApy") or 0)
        tvl = float(market.get("details_totalTvl") or 0)
        liq = float(market.get("details_liquidity") or 0)
        discount = float(market.get("details_ptDiscount") or 0)
        days = days_to_expiry(market.get("expiry"))
        spread = implied - underlying
        family = detect_asset_family(name)
        default_ltv = DEFAULT_LTV.get(family, DEFAULT_LTV_FALLBACK)

        # Build vault candidates
        vault_candidates = self._build_vault_candidates(mms, has_contango, implied, name, family, lookup, default_ltv)
        if not vault_candidates:
            return []

        # Sort by yield and create candidates
        vault_candidates.sort(key=lambda v: v["theoretical_max_yield"], reverse=True)
        return self._create_candidates(market, vault_candidates, mms, ys, has_contango, implied, underlying, spread, tvl, liq, discount, days, family)

    @staticmethod
    def _build_vault_candidates(mms: list, has_contango: bool, implied: float, name: str, family: str, lookup: dict, default_ltv: float) -> list:
        """Build vault candidates from money markets."""
        vaults = []

        for mm in mms:
            pid = mm.get("id", "")
            rate, real_ltv, detail = LoopScoutAgent._find_best_borrow(name, family, pid, lookup)
            if rate <= 0:
                continue

            ltv = real_ltv if real_ltv > 0 else default_ltv
            leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
            net = implied - rate
            theo_yield = implied + max(net, 0) * (leverage - 1)

            vaults.append({
                "vault_name": mm.get("name", ""),
                "vault_id": pid,
                "borrow_apy": rate,
                "ltv": ltv,
                "leverage": leverage,
                "theoretical_max_yield": theo_yield,
                "borrow_detail": detail,
            })

        if has_contango:
            vaults.append({
                "vault_name": "Contango",
                "vault_id": "contango",
                "borrow_apy": 0,
                "ltv": 0,
                "leverage": 0,
                "theoretical_max_yield": implied,
                "borrow_detail": "Automated loop",
            })

        return vaults

    @staticmethod
    def _create_candidates(market: dict, vaults: list, mms: list, ys: list, has_contango: bool, implied: float, underlying: float, spread: float, tvl: float, liq: float, discount: float, days: float, family: str) -> list:
        """Create candidate objects for each vault."""
        candidates = []
        mm_names = [p.get("name", "") for p in mms]
        ys_names = [p.get("name", "") for p in ys]

        for vc in vaults:
            sc = score_candidate(implied, spread, tvl, liq, days, len(mms), has_contango)
            candidates.append({
                "address": market.get("address", ""),
                "chain_id": market.get("chainId"),
                "name": market.get("name", "") or market.get("symbol", ""),
                "symbol": market.get("symbol", ""),
                "protocol": market.get("protocol", ""),
                "expiry": market.get("expiry"),
                "days_to_expiry": round(days, 1),
                "implied_apy": implied,
                "underlying_apy": underlying,
                "spread": spread,
                "pt_discount": discount,
                "tvl": tvl,
                "liquidity": liq,
                "yt_floating_apy": float(market.get("details_ytFloatingApy") or 0),
                "aggregated_apy": float(market.get("details_aggregatedApy") or 0),
                "pendle_apy": float(market.get("details_pendleApy") or 0),
                "max_boosted_apy": float(market.get("details_maxBoostedApy") or 0),
                "asset_family": family,
                "estimated_max_leverage": vc["leverage"],
                "estimated_ltv": vc["ltv"],
                "borrow_cost_estimate": vc["borrow_apy"],
                "theoretical_max_yield": vc["theoretical_max_yield"],
                "vault_name": vc["vault_name"],
                "vault_id": vc["vault_id"],
                "borrow_detail": vc["borrow_detail"],
                "money_markets": mm_names,
                "yield_strategies": ys_names,
                "has_contango": has_contango,
                "score": sc,
                "all_vaults": vaults,
            })
        return candidates

    @staticmethod
    def _deduplicate_candidates(candidates: list) -> list:
        """Remove duplicates, keeping best vault per (name, chain) combo."""
        seen = {}
        deduped = []
        for c in candidates:
            key = f"{c['name']}_{c['chain_id']}_{c['vault_id']}"
            if key not in seen:
                seen[key] = True
                deduped.append(c)
        deduped.sort(key=lambda c: c["theoretical_max_yield"], reverse=True)
        return deduped

    # -- Output synthesis --

    async def synthesize(self, state):
        """Format the final output for the user."""
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

    async def run(self, query: str) -> str:
        """Run the agent with a user query."""
        state: LoopScoutState = {
            "query": query,
            "chain_filter": None,
            "chain_name": None,
            "asset_filter": None,
            "count": 5,
            "chains": [],
            "markets": [],
            "enriched_markets": [],
            "loop_candidates": [],
            "output": "",
        }
        result = await self.graph.ainvoke(state)
        candidates = result.get("loop_candidates", [])

        try:
            save_scan(query=query, chain=result.get("chain_name"), asset_filter=result.get("asset_filter"), candidates=candidates)
            save_yield_history(candidates)
        except Exception as e:
            log.warning("DB save failed: %s", e)

        return result.get("output", "Erreur interne.")