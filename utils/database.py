"""SQLite persistence for scans, alerts, and yield history."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from agents.config import DB_PATH

log = logging.getLogger(__name__)
_conn = None


def _db():
    global _conn
    if not _conn:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, query TEXT, chain TEXT,
                total_candidates INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL, name TEXT, address TEXT, chain_id INTEGER,
                implied_apy REAL, underlying_apy REAL, spread REAL, borrow_cost REAL,
                theoretical_yield REAL, estimated_leverage INTEGER, tvl REAL,
                liquidity REAL, days_to_expiry REAL,
                loop_paths TEXT, vault_name TEXT, vault_id TEXT,
                morpho_unique_key TEXT, morpho_collateral_symbol TEXT, morpho_loan_symbol TEXT,
                euler_vault_address TEXT, euler_collateral_address TEXT,
                borrow_liquidity_usd REAL, borrow_liquidity_tokens REAL, borrow_token_symbol TEXT,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL, chain TEXT,
                min_yield REAL DEFAULT 0,
                enabled INTEGER DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS yield_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, address TEXT NOT NULL, chain_id INTEGER,
                name TEXT, implied_apy REAL,
                theoretical_yield REAL, borrow_cost REAL
            );
            CREATE INDEX IF NOT EXISTS idx_cand_scan ON candidates(scan_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_chat ON alerts(chat_id);
            CREATE INDEX IF NOT EXISTS idx_scans_ts ON scans(ts);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_yh_addr ON yield_history(address);
            CREATE INDEX IF NOT EXISTS idx_yh_ts ON yield_history(ts);
        """)
        _conn.commit()
    return _conn


def _now():
    return datetime.now(timezone.utc).isoformat()


# -- Scans --

def _ensure_extra_columns(conn):
    """Ensure all columns exist in the candidates table (for migrations)."""
    extra_cols = [
        ("liquidity", "REAL"),
        ("days_to_expiry", "REAL"),
        ("morpho_unique_key", "TEXT"),
        ("morpho_collateral_symbol", "TEXT"),
        ("morpho_loan_symbol", "TEXT"),
        ("euler_vault_address", "TEXT"),
        ("euler_collateral_address", "TEXT"),
        ("borrow_liquidity_usd", "REAL"),
        ("borrow_liquidity_tokens", "REAL"),
        ("borrow_token_symbol", "TEXT"),
    ]
    for col, col_type in extra_cols:
        try:
            info = conn.execute("PRAGMA table_info(candidates)").fetchall()
            col_names = [r[1] for r in info]
            if col not in col_names:
                conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} {col_type}")
                log.info("Added column: %s", col)
        except Exception as e:
            log.warning("Failed to add column %s: %s", col, e)


def save_scan(query, chain, candidates):
    conn = _db()
    _ensure_extra_columns(conn)
    
    cur = conn.execute(
        "INSERT INTO scans (ts, query, chain, total_candidates) VALUES (?,?,?,?)",
        (_now(), query, chain, len(candidates)))
    sid = cur.lastrowid

    for c in candidates:
        # Dict-based approach: columns and values always in sync
        row = {
            "scan_id": sid,
            "name": c.get("name",""),
            "address": c.get("address",""),
            "chain_id": c.get("chain_id"),
            "implied_apy": c.get("implied_apy",0),
            "underlying_apy": c.get("underlying_apy",0),
            "spread": c.get("spread",0),
            "borrow_cost": c.get("borrow_cost_estimate",0),
            "theoretical_yield": c.get("theoretical_max_yield",0),
            "estimated_leverage": c.get("estimated_max_leverage",1),
            "tvl": c.get("tvl",0),
            "liquidity": c.get("liquidity",0),
            "days_to_expiry": c.get("days_to_expiry",0),
            "loop_paths": c.get("loop_paths",""),
            "vault_name": c.get("vault_name",""),
            "vault_id": c.get("vault_id",""),
            "morpho_unique_key": c.get("morpho_unique_key",""),
            "morpho_collateral_symbol": c.get("morpho_collateral_symbol",""),
            "morpho_loan_symbol": c.get("morpho_loan_symbol",""),
            "euler_vault_address": c.get("euler_vault_address",""),
            "euler_collateral_address": c.get("euler_collateral_address",""),
            "borrow_liquidity_usd": c.get("borrow_liquidity_usd",0),
            "borrow_liquidity_tokens": c.get("borrow_liquidity_tokens",0),
            "borrow_token_symbol": c.get("borrow_token_symbol",""),
        }
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        try:
            conn.execute(
                f"INSERT INTO candidates ({cols}) VALUES ({placeholders})",
                tuple(row.values()))
        except Exception as e:
            log.error("DB insert failed: %s", e)
            raise

    conn.commit()
    log.info("Scan #%d: %d candidates", sid, len(candidates))
    return sid


def get_last_scan_candidates(chain=None):
    conn = _db()
    where, params = [], []
    if chain:
        where.append("s.chain = ?"); params.append(chain)

    w = f"WHERE {' AND '.join(where)}" if where else ""
    row = conn.execute(f"SELECT id FROM scans {w} ORDER BY ts DESC LIMIT 1", params).fetchone()
    if not row:
        return []
    results = []
    for r in conn.execute(
        "SELECT * FROM candidates WHERE scan_id = ? ORDER BY theoretical_yield DESC", (row["id"],)).fetchall():
        d = dict(r)
        try:
            d['loop_paths'] = json.loads(d.get('loop_paths', '[]'))
        except (json.JSONDecodeError, TypeError):
            d['loop_paths'] = []
        results.append(d)
    return results


def get_scan_count():
    r = _db().execute("SELECT COUNT(*) as cnt FROM scans").fetchone()
    return r["cnt"] if r else 0


# -- Alerts --

def add_alert(chat_id, chain=None, min_yield=0.10):
    conn = _db()
    cur = conn.execute(
        "INSERT INTO alerts (chat_id, chain, min_yield, enabled, created_at) VALUES (?,?,?,1,?)",
        (chat_id, chain, min_yield, _now()))
    conn.commit()
    return cur.lastrowid


def get_alerts(chat_id=None, enabled_only=True):
    conn = _db()
    where, params = [], []
    if chat_id is not None:
        where.append("chat_id = ?"); params.append(chat_id)
    if enabled_only:
        where.append("enabled = 1")
    w = f"WHERE {' AND '.join(where)}" if where else ""
    return [dict(r) for r in conn.execute(f"SELECT * FROM alerts {w}", params).fetchall()]


def delete_alert(alert_id, chat_id):
    conn = _db()
    cur = conn.execute("DELETE FROM alerts WHERE id = ? AND chat_id = ?", (alert_id, chat_id))
    conn.commit()
    return cur.rowcount > 0


def check_alerts_for_candidates(candidates):
    """Returns {chat_id: [matching candidates]}."""
    alerts = get_alerts(enabled_only=True)
    results = {}
    for alert in alerts:
        cid = alert["chat_id"]
        matching = []
        for c in candidates:
            theo = c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0
            if theo < alert.get("min_yield", 0):
                continue
            matching.append(c)
        if matching:
            results.setdefault(cid, []).extend(matching)
    return results


# -- Yield history & spike detection --

def save_yield_history(candidates):
    conn = _db()
    now = _now()
    for c in candidates:
        addr = c.get("address", "")
        if not addr:
            continue
        conn.execute(
            "INSERT INTO yield_history (ts,address,chain_id,name,implied_apy,theoretical_yield,borrow_cost) VALUES (?,?,?,?,?,?,?)",
            (now, addr, c.get("chain_id"), c.get("name",""),
             c.get("implied_apy",0),
             c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0,
             c.get("borrow_cost_estimate") or c.get("borrow_cost") or 0))
    conn.commit()


# -- Settings --

def get_setting(key, default=None):
    row = _db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    conn = _db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, str(value), str(value)))
    conn.commit()


def get_spike_config():
    from const import SPIKE_WINDOW_DEFAULT, SPIKE_MULTIPLIER_DEFAULT, SPIKE_MIN_YIELD_DEFAULT
    return {
        "window": int(get_setting("spike_window", SPIKE_WINDOW_DEFAULT)),
        "multiplier": float(get_setting("spike_multiplier", SPIKE_MULTIPLIER_DEFAULT)),
        "min_yield": float(get_setting("spike_min_yield", SPIKE_MIN_YIELD_DEFAULT)),
    }


def reset_db():
    """Reset the database by deleting and recreating all tables."""
    global _conn
    if _conn:
        _conn.close()
        _conn = None
    # Create a fresh connection and recreate all tables
    conn = _db()
    conn.executescript("""
        DROP TABLE IF EXISTS candidates;
        DROP TABLE IF EXISTS scans;
        DROP TABLE IF EXISTS alerts;
        DROP TABLE IF EXISTS yield_history;
        DROP TABLE IF EXISTS settings;
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, query TEXT, chain TEXT,
            total_candidates INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL, name TEXT, address TEXT, chain_id INTEGER,
            implied_apy REAL, underlying_apy REAL, spread REAL, borrow_cost REAL,
            theoretical_yield REAL, estimated_leverage INTEGER, tvl REAL,
            liquidity REAL, days_to_expiry REAL,
            loop_paths TEXT, vault_name TEXT, vault_id TEXT,
            morpho_unique_key TEXT, morpho_collateral_symbol TEXT, morpho_loan_symbol TEXT,
            euler_vault_address TEXT, euler_collateral_address TEXT,
            borrow_liquidity_usd REAL, borrow_liquidity_tokens REAL, borrow_token_symbol TEXT,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL, chain TEXT,
            min_yield REAL DEFAULT 0,
            enabled INTEGER DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS yield_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, address TEXT NOT NULL, chain_id INTEGER,
            name TEXT, implied_apy REAL,
            theoretical_yield REAL, borrow_cost REAL
        );
        CREATE INDEX IF NOT EXISTS idx_cand_scan ON candidates(scan_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_chat ON alerts(chat_id);
        CREATE INDEX IF NOT EXISTS idx_scans_ts ON scans(ts);
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_yh_addr ON yield_history(address);
        CREATE INDEX IF NOT EXISTS idx_yh_ts ON yield_history(ts);
    """)
    conn.commit()
    log.info("Database reset - tables recreated")
    return True


def export_db_summary():
    """Export a summary of the database contents."""
    conn = _db()
    summary = {}
    
    # Scan count
    r = conn.execute("SELECT COUNT(*) as cnt FROM scans").fetchone()
    summary["total_scans"] = r["cnt"] if r else 0
    
    # Candidate count
    r = conn.execute("SELECT COUNT(*) as cnt FROM candidates").fetchone()
    summary["total_candidates"] = r["cnt"] if r else 0
    
    # Alert count
    r = conn.execute("SELECT COUNT(*) as cnt FROM alerts WHERE enabled = 1").fetchone()
    summary["active_alerts"] = r["cnt"] if r else 0
    
    # Last scan details
    row = conn.execute("SELECT * FROM scans ORDER BY ts DESC LIMIT 1").fetchone()
    if row:
        summary["last_scan"] = dict(row)
        # Top 5 candidates from last scan
        candidates = [dict(r) for r in conn.execute(
            "SELECT name, theoretical_yield, vault_name, vault_id FROM candidates WHERE scan_id = ? ORDER BY theoretical_yield DESC LIMIT 5",
            (row["id"],)).fetchall()]
        summary["top_candidates"] = candidates
    
    return summary


def detect_yield_spikes(candidates, window=None, multiplier=None, min_yield=None):
    """Compare current yield to SMA. Returns spikes sorted by ratio."""
    cfg = get_spike_config()
    if window is None:
        window = cfg["window"]
    if multiplier is None:
        multiplier = cfg["multiplier"]
    if min_yield is None:
        min_yield = cfg["min_yield"]

    conn = _db()
    spikes = []

    for c in candidates:
        addr = c.get("address", "")
        if not addr:
            continue
        cur = c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0
        if cur < min_yield:
            continue

        rows = conn.execute(
            "SELECT theoretical_yield FROM yield_history WHERE address = ? ORDER BY ts DESC LIMIT ?",
            (addr, window)).fetchall()

        past = [r["theoretical_yield"] for r in rows if r["theoretical_yield"] and r["theoretical_yield"] > 0]
        if len(past) < 3:
            continue

        sma = sum(past) / len(past)
        if sma <= 0:
            continue

        ratio = cur / sma
        if ratio >= multiplier:
            spikes.append({
                "name": c.get("name", "?"), "address": addr,
                "chain_id": c.get("chain_id"), 
                "current_yield": cur, "sma_yield": sma, "spike_ratio": ratio,
                "implied_apy": c.get("implied_apy", 0),
                "borrow_cost": c.get("borrow_cost_estimate") or c.get("borrow_cost") or 0,
                "vault_name": c.get("vault_name", ""),
                "vault_id": c.get("vault_id", ""),
                "leverage": c.get("estimated_max_leverage", 0),
            })

    spikes.sort(key=lambda s: s["spike_ratio"], reverse=True)
    log.info("Spikes: %d (window=%d, ×%.1f)", len(spikes), window, multiplier)
    return spikes