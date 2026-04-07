"""Parsing utility functions."""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

from agents.config import ASSET_FAMILIES

# Month abbreviations used in PT symbols (e.g. PT-USDE-5FEB2026)
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Matches patterns like "29MAY2025", "5FEB2026", "14AUG2025"
_DATE_RE = re.compile(r"(\d{1,2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{4})", re.IGNORECASE)


def parse_pt_expiry_from_symbol(symbol: str) -> datetime | None:
    """Extract expiry date from a PT symbol like 'PT-USDE-5FEB2026' or 'ePT-tUSDe-18DEC2025'.
    
    Returns a timezone-aware datetime or None if parsing fails.
    """
    m = _DATE_RE.search(symbol)
    if not m:
        return None
    try:
        day = int(m.group(1))
        month = _MONTH_MAP[m.group(2).upper()]
        year = int(m.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return None


def is_pt_not_expired(symbol: str) -> bool:
    """Return True if the PT token has not expired yet (expiry > yesterday).
    
    Returns True also if the expiry date cannot be parsed (conservative approach).
    """
    expiry = parse_pt_expiry_from_symbol(symbol)
    if expiry is None:
        return True  # Can't determine — keep it
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    return expiry > yesterday


def days_to_expiry(expiry_str: str | None) -> float:
    """Calculate days remaining until expiry."""
    if not expiry_str:
        return -1
    try:
        exp = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        delta = exp - datetime.now(timezone.utc)
        return max(delta.total_seconds() / 86400, 0)
    except Exception:
        return -1


def matches_asset_family(name: str, family: str) -> bool:
    """Check if a market name matches the given asset family."""
    low = name.lower()
    keywords = ASSET_FAMILIES.get(family, [])
    return any(kw in low for kw in keywords)


def detect_asset_family(name: str) -> str:
    """Detect asset family from market name."""
    low = name.lower()
    for family, keywords in ASSET_FAMILIES.items():
        if any(kw in low for kw in keywords):
            return family
    return "other"