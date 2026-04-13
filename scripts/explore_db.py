#!/usr/bin/env python3
"""Explore the SQLite database contents."""

import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "data/loop_scout.db")

def main():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    print("=" * 60)
    print("DATABASE EXPLORER")
    print("=" * 60)
    
    # Count rows per table
    print("\n📊 TABLE COUNTS")
    print("-" * 40)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for t in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
        print(f"  {t[0]:20s}: {count:,} rows")
    
    # Schema
    print("\n📋 SCHEMAS")
    print("-" * 40)
    for t in tables:
        print(f"\n{t[0]}:")
        cols = conn.execute(f"PRAGMA table_info({t[0]})").fetchall()
        for c in cols:
            print(f"  - {c['name']:25s} {c['type']}")
    
    # Recent scans
    print("\n\n📅 LAST 5 SCANS")
    print("-" * 40)
    for r in conn.execute("SELECT * FROM scans ORDER BY ts DESC LIMIT 5").fetchall():
        print(f"\n  Scan #{r['id']} @ {r['ts']}")
        print(f"    Query: {r['query']}")
        print(f"    Chain: {r['chain']} | Asset: {r['asset_filter']}")
        print(f"    Candidates: {r['total_candidates']}")
    
    # Top candidates
    print("\n\n🏆 TOP 5 CANDIDATES (by theoretical yield)")
    print("-" * 40)
    for r in conn.execute("""
        SELECT c.name, c.chain_id, c.vault_name, c.vault_id, 
               c.theoretical_yield, c.borrow_cost, c.score, s.ts
        FROM candidates c
        JOIN scans s ON c.scan_id = s.id
        ORDER BY c.theoretical_yield DESC LIMIT 5
    """).fetchall():
        print(f"\n  {r['name']} (chain={r['chain_id']})")
        print(f"    Vault: {r['vault_name']} [{r['vault_id']}]")
        print(f"    Yield: {r['theoretical_yield']*100:.2f}% | Borrow: {r['borrow_cost']*100:.2f}%")
        print(f"    Score: {r['score']:.1f} | {r['ts']}")
    
    # Protocol breakdown
    print("\n\n🔗 PROTOCOL BREAKDOWN")
    print("-" * 40)
    for r in conn.execute("""
        SELECT vault_id, COUNT(*) as cnt, 
               AVG(theoretical_yield)*100 as avg_yield,
               AVG(score) as avg_score
        FROM candidates GROUP BY vault_id ORDER BY cnt DESC
    """).fetchall():
        print(f"  {r['vault_id'] or 'unknown':15s}: {r['cnt']:4d} candidates | "
              f"avg yield: {r['avg_yield']:.1f}% | avg score: {r['avg_score']:.1f}")
    
    # Yield history
    print("\n\n📈 YIELD HISTORY (recent)")
    print("-" * 40)
    for r in conn.execute("""
        SELECT name, address, chain_id, theoretical_yield, borrow_cost, ts
        FROM yield_history ORDER BY ts DESC LIMIT 10
    """).fetchall():
        print(f"  {r['name']}: yield={r['theoretical_yield']*100:.2f}% @ {r['ts']}")
    
    # Alerts
    print("\n\n🔔 ACTIVE ALERTS")
    print("-" * 40)
    alerts = conn.execute("SELECT * FROM alerts WHERE enabled = 1").fetchall()
    if alerts:
        for a in alerts:
            print(f"  chat_id={a['chat_id']} | {a['chain'] or 'all chains'} | "
                  f"asset={a['asset_filter'] or 'all'} | min_yield={a['min_yield']*100:.0f}%")
    else:
        print("  No active alerts")
    
    # Settings
    print("\n\n⚙️  SETTINGS")
    print("-" * 40)
    settings = conn.execute("SELECT * FROM settings").fetchall()
    if settings:
        for s in settings:
            print(f"  {s['key']}: {s['value']}")
    else:
        print("  No settings stored")
    
    conn.close()
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
