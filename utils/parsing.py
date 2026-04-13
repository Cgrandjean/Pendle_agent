"""Parsing utility functions."""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

from const import ASSET_FAMILIES, MONTH_MAP, DATE_RE


def parse_pt_expiry_from_symbol(symbol: str) -> datetime | None:
    """Extract expiry date from a PT symbol like 'PT-USDE-5FEB2026'."""
    m = DATE_RE.search(symbol)
    if not m:
        return None
    try:
        day = int(m.group(1))
        month = MONTH_MAP[m.group(2).upper()]
        year = int(m.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return None


def is_pt_not_expired(symbol: str) -> bool:
    """Return True if the PT token has not expired yet."""
    expiry = parse_pt_expiry_from_symbol(symbol)
    if expiry is None:
        return True
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    return expiry > yesterday


def days_to_expiry(expiry_str: str | None) -> float:
    """Calculate days remaining until expiry."""
    if not expiry_str:
        return -1
    try:
        exp = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        return max((exp - datetime.now(timezone.utc)).total_seconds() / 86400, 0)
    except Exception:
        return -1


def matches_asset_family(name: str, family: str) -> bool:
    """Check if a market name matches the given asset family."""
    low = name.lower()
    return any(kw in low for kw in ASSET_FAMILIES.get(family, []))


def detect_asset_family(name: str) -> str:
    """Detect asset family from market name."""
    low = name.lower()
    for family, keywords in ASSET_FAMILIES.items():
        if any(kw in low for kw in keywords):
            return family
    return "other"


def extract_ticker(symbol: str) -> str:
    """Extract core ticker from a PT symbol or market name."""
    s = symbol.strip().lower()
    s = re.sub(r'^e?pt[\s\-]+', '', s)
    s = re.sub(r'\d{1,2}[a-z]{3}\d{4}(-\d+)?', '', s, flags=re.IGNORECASE)
    return s.strip(' -_')


def extract_pt_date(symbol: str) -> str:
    """Extract date from PT symbol, or empty string if no date."""
    m = re.search(r'\d{1,2}[A-Z]{3}\d{4}', symbol, re.IGNORECASE)
    return m.group(0).upper() if m else ""


def pt_matches_market(pt_symbol: str, market_name: str, market_expiry: str = None) -> bool:
    """Check if a PT collateral symbol matches a Pendle market by ticker AND expiry date."""
    pt_ticker = extract_ticker(pt_symbol)
    mkt_ticker = extract_ticker(market_name)

    if pt_ticker != mkt_ticker:
        return False

    pt_date = extract_pt_date(pt_symbol)
    mkt_date = extract_pt_date(market_name)

    if mkt_date:
        return pt_date == mkt_date

    if market_expiry and pt_date:
        mkt_date_iso = market_expiry[:10]
        try:
            day = int(pt_date[:2])
            month = MONTH_MAP[pt_date[2:5].upper()]
            year = int(pt_date[5:])
            pt_iso = f"{year:04d}-{month:02d}-{day:02d}"
            return pt_iso == mkt_date_iso
        except (ValueError, KeyError):
            pass

    return True
