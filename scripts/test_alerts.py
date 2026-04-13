#!/usr/bin/env python3
"""Test the alert system end-to-end.

This script:
1. Creates test alerts in the DB
2. Runs a real scan
3. Checks which alerts would have fired
4. Tests spike detection (needs history)
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import (
    add_alert, get_alerts, delete_alert,
    check_alerts_for_candidates, detect_yield_spikes,
    get_spike_config, save_scan,
)
from agents.loop_scout_agent import LoopScoutAgent


# Test alerts to create
TEST_ALERTS = [
    # (asset_filter, chain, min_yield, description)
    (None, None, 0.05, "All assets, all chains, yield > 5%"),
    ("stable", None, 0.10, "Stablecoins, all chains, yield > 10%"),
    ("stable", "arbitrum", 0.15, "Stablecoins, Arbitrum, yield > 15%"),
    ("eth", None, 0.08, "ETH markets, all chains, yield > 8%"),
    (None, "ethereum", 0.20, "All assets, Ethereum, yield > 20%"),
]


def main():
    print("=" * 60)
    print("ALERT SYSTEM TEST")
    print("=" * 60)

    # Step 1: Create test alerts
    print("\n📝 Step 1: Creating test alerts...")
    created_ids = []
    for asset, chain, min_yield, desc in TEST_ALERTS:
        alert_id = add_alert(
            chat_id=999999999,  # Dummy chat_id
            asset_filter=asset,
            chain=chain,
            min_yield=min_yield,
        )
        created_ids.append(alert_id)
        print(f"  ✅ Alert #{alert_id}: {desc} (min_yield={min_yield*100:.0f}%)")

    # List all alerts
    print("\n📋 Current alerts in DB:")
    all_alerts = get_alerts(enabled_only=False)
    for a in all_alerts:
        print(f"  #{a['id']}: asset={a['asset_filter'] or 'all'} | "
              f"chain={a['chain'] or 'all'} | min_yield={a['min_yield']*100:.0f}%")

    # Step 2: Run a scan
    print("\n🔍 Step 2: Running scan (arbitrum, stable, top 20)...")
    agent = LoopScoutAgent()
    candidates = []

    async def run_scan():
        global candidates
        resp = await agent.run(count=20, asset="stable", chain="arbitrum")
        return resp

    resp = asyncio.run(run_scan())
    print(resp)

    # Get candidates from last scan (direct query since DB was reset)
    from utils.database import _db
    conn = _db()
    last_scan = conn.execute("SELECT id FROM scans ORDER BY ts DESC LIMIT 1").fetchone()
    if last_scan:
        candidates = []
        for r in conn.execute(
            "SELECT * FROM candidates WHERE scan_id = ? ORDER BY theoretical_yield DESC",
            (last_scan["id"],)).fetchall():
            candidates.append(dict(r))
    else:
        candidates = []
    print(f"\n  → {len(candidates)} candidates saved from scan")

    if not candidates:
        print("❌ No candidates found!")
        return

    # Step 3: Check which alerts would fire
    print("\n🚨 Step 3: Checking which alerts would fire...")
    print("-" * 40)

    # Filter out our test alerts (chat_id=999999999)
    real_alerts = [a for a in get_alerts(enabled_only=True) if a["chat_id"] != 999999999]
    print(f"  Real alerts (from other users): {len(real_alerts)}")

    # Manually check against our test candidates
    print("\n  Test alert matching:")
    for alert_id in created_ids:
        # Get the alert we just created
        alert = next((a for a in all_alerts if a["id"] == alert_id), None)
        if not alert:
            continue

        matches = []
        for c in candidates:
            theo = c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0
            family = c.get("asset_family", "")
            chain = c.get("chain_id", 0)

            # Check asset filter
            if alert.get("asset_filter"):
                if alert["asset_filter"] not in family.lower():
                    continue

            # Check chain filter
            if alert.get("chain"):
                from agents.config import CHAINS
                expected_chain_id = CHAINS.get(alert["chain"])
                if chain != expected_chain_id:
                    continue

            # Check min yield
            if theo < alert.get("min_yield", 0):
                continue

            matches.append(c)

        if matches:
            print(f"\n  🔔 Alert #{alert_id} WOULD FIRE ({len(matches)} matches):")
            for m in matches[:3]:
                theo = m.get("theoretical_max_yield") or m.get("theoretical_yield") or 0
                print(f"     - {m.get('name', '?')} | yield={theo*100:.1f}% | "
                      f"vault={m.get('vault_name', '?')} [{m.get('vault_id', '?')}]")
            if len(matches) > 3:
                print(f"     ... +{len(matches) - 3} more")
        else:
            print(f"\n  ❌ Alert #{alert_id}: no matches")

    # Step 4: Test spike detection
    print("\n\n⚡ Step 4: Testing spike detection...")
    cfg = get_spike_config()
    print(f"  Config: window={cfg['window']}, multiplier={cfg['multiplier']}, min_yield={cfg['min_yield']*100:.0f}%")

    from utils.database import _db
    conn = _db()
    hist_count = conn.execute("SELECT COUNT(*) FROM yield_history").fetchone()[0]
    print(f"  Yield history entries: {hist_count}")

    if hist_count < 10:
        print("  ⚠️  Not enough history for spike detection (need at least 10 entries)")
        print("  Spike detection compares current yield to SMA of last N scans.")
        print("  It will work once the bot runs scheduled scans over time.")
    else:
        spikes = detect_yield_spikes(candidates)
        if spikes:
            print(f"\n  🚨 {len(spikes)} spike(s) detected:")
            for s in spikes[:5]:
                print(f"     - {s.get('name', '?')} | current={s['current_yield']*100:.1f}% "
                      f"| avg={s['sma_yield']*100:.1f}% | ratio=×{s['spike_ratio']:.2f}")
        else:
            print("  No spikes detected.")

    # Step 5: Cleanup test alerts
    print("\n\n🧹 Step 5: Cleaning up test alerts...")
    for alert_id in created_ids:
        delete_alert(alert_id, 999999999)
        print(f"  ✅ Deleted alert #{alert_id}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
