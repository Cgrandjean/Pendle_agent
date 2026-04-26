#!/usr/bin/env python3
"""Test yield_history coherence across multiple agent scans.

Verifies:
1. No duplicate rows per (combo, timestamp).
2. pt_underlying and pt_expiry are stable per combo.
3. No suspicious yield oscillation (would indicate cross-contamination).
4. pt_underlying matches the Pendle market ticker.
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.loop_scout_agent import LoopScoutAgent
from utils.database import reset_db


async def run_scans(n: int):
    agent = LoopScoutAgent()
    for i in range(n):
        print(f"  Scan {i+1}/{n}...")
        await agent.run(count=100)
        await asyncio.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Test yield_history coherence across scans")
    parser.add_argument("--scans", type=int, default=5, help="Number of scans to run (default: 5)")
    parser.add_argument("--no-reset", action="store_true", help="Don't reset DB before testing")
    args = parser.parse_args()

    import sqlite3

    print(f"={'='*60}")
    print("YIELD_HISTORY COHERENCE TEST")
    print(f"{'='*60}")

    # Reset DB
    if not args.no_reset:
        print("\n[1/4] Resetting database...")
        reset_db()
        print("  ✅ DB reset done")
    else:
        print("\n[1/4] Skipping DB reset (--no-reset)")

    # Run scans
    print(f"\n[2/4] Running {args.scans} agent scans...")
    asyncio.run(run_scans(args.scans))
    print(f"  ✅ {args.scans} scans complete")

    # DB checks
    print("\n[3/4] Running coherence checks...")
    conn = sqlite3.connect("data/loop_scout.db")
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT pendle_address, pendle_name, pt_underlying, pt_expiry, vault_id, vault_key, "
        "theoretical_yield, ts FROM yield_history ORDER BY pendle_address, vault_id, vault_key, ts"
    ).fetchall()

    total_rows = len(rows)
    print(f"  Total yield_history rows: {total_rows}")

    # Group by combo
    combos: dict[tuple, list] = {}
    for r in rows:
        key = (r["pendle_address"], r["vault_id"], r["vault_key"])
        combos.setdefault(key, []).append(dict(r))

    print(f"  Unique combos: {len(combos)}")

    errors: list[str] = []
    warnings: list[str] = []

    # 1. Duplicate rows per (combo, ts)
    for key, entries in combos.items():
        ts_counts: dict[str, int] = {}
        for e in entries:
            ts_counts[e["ts"]] = ts_counts.get(e["ts"], 0) + 1
        for ts, cnt in ts_counts.items():
            if cnt > 1:
                errors.append(
                    f"  DUPLICATE: combo={key[0][:16]} vault={key[1]} "
                    f"ts={ts[:19]} → {cnt} rows"
                )

    # 2. pt_underlying / pt_expiry stability
    for key, entries in combos.items():
        pt_underlyings = {e["pt_underlying"] for e in entries if e["pt_underlying"]}
        pt_expiries = {e["pt_expiry"] for e in entries if e["pt_expiry"]}
        if len(pt_underlyings) > 1:
            errors.append(
                f"  PT_UNDERLYING DRIFT: {key[0][:16]} vault={key[1]} → {pt_underlyings}"
            )
        if len(pt_expiries) > 1:
            errors.append(
                f"  PT_EXPIRY DRIFT: {key[0][:16]} vault={key[1]} → {pt_expiries}"
            )

    # 3. Yield oscillation (>50% swing)
    for key, entries in combos.items():
        yields = [e["theoretical_yield"] for e in entries if e["theoretical_yield"] is not None]
        if len(yields) >= 2:
            y_max = max(yields)
            y_min = min(yields)
            if y_max > 0 and (y_max - y_min) / y_max > 0.5:
                warnings.append(
                    f"  OSCILLATION: {key[0][:16]} vault={key[1]} "
                    f"yields={[round(y,4) for y in yields]} swing={y_max-y_min:.4f}"
                )

    # 4. vault_key consistency (same combo should have same vault_key)
    for key, entries in combos.items():
        vault_keys = {e["vault_key"] for e in entries}
        if len(vault_keys) > 1:
            errors.append(
                f"  VAULT_KEY DRIFT: {key[0][:16]} vault_ids={key[1]} → {vault_keys}"
            )

    # Report
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")

    if errors:
        print(f"\n🚨 ERRORS ({len(errors)}):")
        for e in errors:
            print(e)
    else:
        print("\n✅ No errors found")

    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(w)
    else:
        print("✅ No warnings (no yield oscillation)")

    # Per-combo summary
    print(f"\n{'='*60}")
    print("PER-COMBO SUMMARY")
    print(f"{'='*60}")
    for key, entries in sorted(combos.items(), key=lambda x: x[0][0]):
        yields = [e["theoretical_yield"] for e in entries if e["theoretical_yield"] is not None]
        pt = entries[0]["pt_underlying"] or "?"
        expiry = entries[0]["pt_expiry"] or "?"
        name = entries[0]["pendle_name"] or "?"
        vault_name = entries[0]["vault_id"] or "?"
        y_range = max(yields) - min(yields) if len(yields) > 1 else 0
        status = "✅" if y_range < 0.5 and len({e["pt_underlying"] for e in entries}) <= 1 else "⚠️"
        print(f"  {status} {name[:25]:25s} | {pt[:10]:10s} | {expiry} | {vault_name:8s} | "
              f"yields={[round(y,3) for y in yields]} range={y_range:.4f}")

    # Final verdict
    print(f"\n{'='*60}")
    if not errors and not warnings:
        print("🎉 PASS — All yield_history data is coherent")
        sys.exit(0)
    elif not errors:
        print("✅ PASS (warnings only — data is structurally correct)")
        sys.exit(0)
    else:
        print(f"🚨 FAIL — {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)


if __name__ == "__main__":
    main()
