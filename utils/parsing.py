"""Parsing utility functions."""

from __future__ import annotations

import re
from datetime import datetime, date

from const import MONTH_MAP
from schemas.agent_state import PTToken

_DATE_RE = re.compile(r"^(\d{1,2})([A-Za-z]{3})(\d{4})$")


def parse_pt(symbol: str) -> PTToken | None:
    """Parse a PT symbol into a PTToken.

    Format: [e]PT-<UNDERLYING>-<DDMMMYYYY>[-N]
    - ePT- or PT- prefix stripped (case-insensitive)
    - UNDERLYING = everything before the date segment
    - DDMMMYYYY = date part (day + 3-letter month + year)
    - trailing -N (version) is stripped
    """
    if not symbol:
        return None
    s = symbol.upper()
    if s.startswith("EPT-"):
        rest = symbol[4:]
    elif s.startswith("PT-"):
        rest = symbol[3:]
    else:
        return None

    # Find the date segment from the end
    parts = rest.split("-")
    if len(parts) < 2:
        return None

    # parts[-1] could be a version number (-2), try from the end
    for i in range(len(parts) - 1, 0, -1):
        m = _DATE_RE.match(parts[i])
        if m:
            mon_upper = m.group(2).upper()
            if mon_upper not in MONTH_MAP:
                return None
            try:
                dt = datetime(int(m.group(3)), MONTH_MAP[mon_upper], int(m.group(1)))
            except ValueError:
                return None
            underlying = "-".join(parts[:i])
            if not underlying:
                return None
            return PTToken(underlying=underlying, expiry_iso=dt.strftime("%Y-%m-%d"))
            break
    return None


def is_pt_not_expired(symbol: str) -> bool:
    """Return True if the PT token has not expired yet."""
    pt = parse_pt(symbol)
    if pt is None:
        return True
    return pt.expiry_iso >= str(date.today())


def extract_ticker(symbol: str) -> str:
    """Extract ticker from a Pendle market name or PT symbol.

    Removes the date suffix (e.g. 7MAY2026) and any PT- prefix.
    Returns lowercase for consistent matching.
    """
    s = symbol.upper()
    if s.startswith("PT-"):
        s = s[3:]
    s = re.sub(r"\d{1,2}[A-Z]{3}\d{4}$", "", s)
    return s.rstrip("-").lower()


def days_to_expiry(expiry_str: str | None) -> float:
    """Calculate days remaining until expiry (ISO date string)."""
    if not expiry_str:
        return -1
    try:
        exp = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        return max((exp - datetime.now(exp.tzinfo)).total_seconds() / 86400, 0)
    except Exception:
        return -1
