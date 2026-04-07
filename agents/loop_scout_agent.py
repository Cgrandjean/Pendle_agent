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


class LoopScoutAgent:
    def __init__(self):
        g = StateGraph(LoopScoutState)

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

        self.graph = g.compile()

    def _after_markets(self, state):
        return "synthesize" if not state.get("markets") else "collect_protocols"

    # -- Skim nodes (parallel) --

    async def skim_aave(self, state):
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, fetch_aave_data)
        log.info("AAVE: %d PT tokens, %d stable rates",
                 len(data.get("pt_tokens", {})), len(data.get("stable_borrow", {})))
        return {"aave_data": data}

    async def skim_morpho(self, state):
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, fetch_morpho_data, 5000)
        log.info("Morpho: %d PT markets", len(data.get("pt_markets", [])))
        return {"morpho_data": data}

    async def skim_euler(self, state):
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, fetch_euler_data, 100)
        log.info("Euler: %d PT vaults, %d stable vaults",
                 len(data.get("pt_vaults", [])), len(data.get("stable_vaults", [])))
        return {"euler_data": data}

    # -- Collect Pendle markets --

    async def collect_markets(self, state):
        query = state.get("query", "")
        low = query.lower().strip()

        # Parse chain
        chain_id = chain_name = None
        for kw, cid in CHAINS.items():
            if re.search(rf"\b{re.escape(kw)}\b", low):
                chain_id, chain_name = cid, kw
                break

        # Parse asset
        asset_filter = None
        for family, keywords in ASSET_FAMILIES.items():
            if any(re.search(rf"\b{re.escape(k)}\b", low) for k in keywords):
                asset_filter = family
                break

        # Parse count
        count = 5
        m = re.search(r"top\s*(\d+)", low)
        if m:
            count = min(int(m.group(1)), 20)

        log.info("Intent: chain=%s asset=%s count=%d", chain_name, asset_filter, count)

        filters = [
            {"field": "details_impliedApy", "op": ">", "value": 0.001},
            {"field": "details_totalTvl", "op": ">=", "value": MIN_TVL},
        ]

        all_markets = []

        if chain_id:
            try:
                mkts = await pendle_mcp.get_markets(
                    chain_id=chain_id, filters=filters,
                    sort_field="details_impliedApy", sort_dir="desc", limit=50)
                if isinstance(mkts, list):
                    all_markets.extend(mkts)
            except Exception as e:
                log.error("Markets chain %d: %s", chain_id, e)
        else:
            try:
                chains = await pendle_mcp.get_chains()
                if not isinstance(chains, list):
                    chains = [1, 42161, 8453, 10, 56, 5000, 146]
            except Exception:
                chains = [1, 42161, 8453, 10, 56, 5000, 146]

            for c in chains:
                try:
                    r = await pendle_mcp.get_markets(
                        chain_id=c, filters=filters,
                        sort_field="details_impliedApy", sort_dir="desc", limit=50)
                    if isinstance(r, list):
                        all_markets.extend(r)
                except Exception as e:
                    log.warning("Markets chain %d: %s", c, e)

        # Filter by expiry + asset
        active = []
        for m in all_markets:
            days = days_to_expiry(m.get("expiry"))
            if 0 <= days < MIN_DAYS_TO_EXPIRY:
                continue
            if asset_filter:
                name = m.get("name", "") or m.get("symbol", "") or ""
                if not matches_asset_family(name, asset_filter):
                    continue
            active.append(m)

        log.info("Markets: %d active / %d raw", len(active), len(all_markets))
        return {
            "markets": active, "chain_filter": chain_id, "chain_name": chain_name,
            "asset_filter": asset_filter, "count": count,
        }

    # -- Enrich with external protocols --

    async def collect_protocols(self, state):
        markets = state.get("markets", [])
        enriched = []
        for m in markets:
            addr = m.get("address", "")
            cid = m.get("chainId")
            protos = []
            try:
                r = await pendle_mcp.get_external_protocols(chain_id=cid, market=addr)
                if isinstance(r, dict):
                    protos = r.get("protocols", [])
                elif isinstance(r, list):
                    protos = r
            except Exception as e:
                log.warning("Protocols %s: %s", addr[:10], e)
            enriched.append({**m, "external_protocols": protos})

        log.info("Enriched %d markets", len(enriched))
        return {"enriched_markets": enriched}

    # -- Analyze loops --

    def _borrow_lookup(self, state):
        lookup = {"morpho": [], "euler": [], "aave": []}

        for mkt in (state.get("morpho_data") or {}).get("pt_markets", []):
            lookup["morpho"].append({
                "col": mkt.get("collateral_symbol", ""),
                "loan": mkt.get("loan_symbol", ""),
                "rate": mkt.get("borrow_apy", 0),
                "lltv": mkt.get("lltv", 0),
            })

        for v in (state.get("euler_data") or {}).get("stable_vaults", []):
            lookup["euler"].append({
                "sym": v.get("symbol", ""),
                "rate_pct": v.get("borrow_apy_pct", 0),
                "cash": v.get("cash", 0),
            })

        for sym, d in (state.get("aave_data") or {}).get("stable_borrow", {}).items():
            lookup["aave"].append({
                "sym": sym,
                "rate": d.get("borrow_apy", 0),
            })

        return lookup

    def _best_borrow(self, name, asset_family, pid, lookup):
        """Find cheapest borrow rate. Returns (rate, ltv, detail)."""
        low = name.lower()

        if pid == "morpho":
            best = None
            for m in lookup["morpho"]:
                if any(k in low for k in m["col"].lower().split("-") if len(k) > 2):
                    if best is None or m["rate"] < best[0]:
                        best = (m["rate"], m["lltv"], f"Morpho {m['col']}/{m['loan']}")
            if best:
                return best

        if pid == "euler":
            best = None
            for v in lookup["euler"]:
                if v["rate_pct"] > 0.5 and v["cash"] > 100_000:
                    rate = v["rate_pct"] / 100
                    if best is None or rate < best[0]:
                        best = (rate, 0.80, f"Euler {v['sym']}")
            if best:
                return best

        if pid in ("aave", "aavev3"):
            stables = ["USDC", "USDT", "USDS", "USDE", "GHO", "PYUSD"] if asset_family == "stable" else ["USDC", "USDT"]
            best = None
            for e in lookup["aave"]:
                if e["sym"] in stables and e["rate"] > 0:
                    if best is None or e["rate"] < best[0]:
                        best = (e["rate"], 0, f"AAVE {e['sym']}")
            if best:
                return best

        return (0, 0, "")

    async def analyze_loops(self, state):
        enriched = state.get("enriched_markets", [])
        lookup = self._borrow_lookup(state)
        candidates = []

        for m in enriched:
            protos = m.get("external_protocols", [])
            mms = [p for p in protos if p.get("category", "").lower() == "money market"]
            ys = [p for p in protos if p.get("category", "").lower() == "yield strategy"]
            has_contango = any(p.get("id") == "contango" for p in protos)

            if not mms and not has_contango:
                continue

            name = m.get("name", "") or m.get("symbol", "") or ""
            implied = float(m.get("details_impliedApy") or 0)
            underlying = float(m.get("details_underlyingApy") or 0)
            tvl = float(m.get("details_totalTvl") or 0)
            liq = float(m.get("details_liquidity") or 0)
            discount = float(m.get("details_ptDiscount") or 0)
            days = days_to_expiry(m.get("expiry"))

            spread = implied - underlying
            family = detect_asset_family(name)

            # Default LTV by asset type
            default_ltv = {"stable": 0.90, "eth": 0.80, "btc": 0.75}.get(family, 0.70)

            # Build per-vault candidates
            vault_candidates = []
            for mm in mms:
                pid = mm.get("id", "")
                rate, real_ltv, detail = self._best_borrow(name, family, pid, lookup)
                
                if rate <= 0:
                    continue
                    
                # Calculate leverage and yield for this specific vault
                ltv = real_ltv if real_ltv > 0 else default_ltv
                leverage = int(1 / (1 - ltv)) if ltv < 1 else 10
                net = implied - rate
                theo_yield = implied + max(net, 0) * (leverage - 1)
                
                vault_candidates.append({
                    "vault_name": mm.get("name", ""),
                    "vault_id": pid,
                    "borrow_apy": rate,
                    "ltv": ltv,
                    "leverage": leverage,
                    "theoretical_max_yield": theo_yield,
                    "borrow_detail": detail,
                })

            # Add Contango as a separate option
            if has_contango:
                ct = next((p for p in protos if p.get("id") == "contango"), {})
                vault_candidates.append({
                    "vault_name": "Contango",
                    "vault_id": "contango",
                    "borrow_apy": 0,
                    "ltv": 0,
                    "leverage": 0,
                    "theoretical_max_yield": implied,  # No leverage, just implied
                    "borrow_detail": "Automated loop",
                })

            if not vault_candidates:
                continue

            # Sort vault candidates by theoretical yield
            vault_candidates.sort(key=lambda v: v["theoretical_max_yield"], reverse=True)

            # Create one candidate per vault
            for vc in vault_candidates:
                sc = score_candidate(implied, spread, tvl, liq, days, len(mms), has_contango)

                candidates.append({
                    "address": m.get("address", ""), "chain_id": m.get("chainId"),
                    "name": name, "symbol": m.get("symbol", ""), "protocol": m.get("protocol", ""),
                    "expiry": m.get("expiry"), "days_to_expiry": round(days, 1),
                    "implied_apy": implied, "underlying_apy": underlying,
                    "spread": spread, "pt_discount": discount,
                    "tvl": tvl, "liquidity": liq,
                    "yt_floating_apy": float(m.get("details_ytFloatingApy") or 0),
                    "aggregated_apy": float(m.get("details_aggregatedApy") or 0),
                    "pendle_apy": float(m.get("details_pendleApy") or 0),
                    "max_boosted_apy": float(m.get("details_maxBoostedApy") or 0),
                    "asset_family": family,
                    "estimated_max_leverage": vc["leverage"], "estimated_ltv": vc["ltv"],
                    "borrow_cost_estimate": vc["borrow_apy"], "theoretical_max_yield": vc["theoretical_max_yield"],
                    "vault_name": vc["vault_name"], "vault_id": vc["vault_id"],
                    "borrow_detail": vc["borrow_detail"],
                    "money_markets": [p.get("name", "") for p in mms],
                    "yield_strategies": [p.get("name", "") for p in ys],
                    "has_contango": has_contango, "score": sc,
                    # Keep all vaults for display
                    "all_vaults": vault_candidates,
                })

        # Deduplicate: keep only the best vault candidate per unique (name, chain) combo
        seen = {}
        deduped = []
        for c in candidates:
            key = f"{c['name']}_{c['chain_id']}_{c['vault_id']}"
            if key not in seen:
                seen[key] = True
                deduped.append(c)
        
        deduped.sort(key=lambda c: c["theoretical_max_yield"], reverse=True)
        log.info("Found %d loop candidates", len(deduped))
        return {"loop_candidates": deduped}

    # -- Synthesize output --

    async def synthesize(self, state):
        candidates = state.get("loop_candidates", [])
        count = state.get("count", 5)
        top = candidates[:count]

        if not top:
            return {"output": no_results_message(
                state.get("chain_name"), state.get("asset_filter"))}

        chain = (state.get("chain_name") or "toutes chaînes").capitalize()
        asset = state.get("asset_filter") or "tous actifs"

        parts = [
            f"🔄 *Loop Scout — {chain} / {asset}*\n"
            f"_{len(candidates)} candidat(s), top {len(top)} :_\n"
        ]
        for i, c in enumerate(top, 1):
            parts.append(format_candidate(i, c))

        parts.append(
            "\n⚠️ *Disclaimer* — Rendements théoriques estimés. "
            "Vérifiez LTV/borrow réels. Bot read-only. DYOR."
        )
        return {"output": "\n".join(parts)}

    # -- Public API --

    async def run(self, query: str) -> str:
        state: LoopScoutState = {
            "query": query, "chain_filter": None, "chain_name": None,
            "asset_filter": None, "count": 5,
            "chains": [], "markets": [], "enriched_markets": [],
            "loop_candidates": [], "output": "",
        }
        result = await self.graph.ainvoke(state)

        candidates = result.get("loop_candidates", [])
        try:
            save_scan(
                query=query, chain=result.get("chain_name"),
                asset_filter=result.get("asset_filter"),
                candidates=candidates)
            save_yield_history(candidates)
        except Exception as e:
            log.warning("DB save failed: %s", e)

        return result.get("output", "Erreur interne.")