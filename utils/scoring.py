"""Scoring for loop candidates."""


def score_candidate(implied_apy, spread, tvl, liquidity, days, mm_count, has_contango):
    s = min(spread / 0.05, 3.0) * 35
    s += min(max(tvl, liquidity) / 10_000_000, 2.0) * 20

    if days < 0:
        s += 10
    elif days < 7:
        s += 2
    elif days < 30:
        s += 10
    elif days <= 180:
        s += 15
    elif days <= 365:
        s += 10
    else:
        s += 6

    s += min(mm_count, 5) * 4
    if has_contango:
        s += 10
    if tvl < 500_000:
        s -= 5

    return round(max(s, 0), 2)