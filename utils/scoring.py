"""Scoring for loop candidates."""

from const import (
    WEIGHT_SPREAD, WEIGHT_TVL, WEIGHT_DAYS, WEIGHT_BORROW,
    WEIGHT_PT_DISCOUNT, WEIGHT_LEVERAGE, WEIGHT_MM_COUNT,
    SPREAD_MAX_SCORE, SPREAD_CAP, TVL_MAX_SCORE, TVL_CAP,
    BORROW_MAX, PT_DISCOUNT_MAX, LEVERAGE_MAX, CONTANGO_BONUS,
    TVL_PENALTY_THRESHOLD, TVL_PENALTY,
    DAYS_NEGATIVE, DAYS_VERY_SHORT, DAYS_SHORT, DAYS_MEDIUM, DAYS_LONG, DAYS_VERY_LONG,
)


def score_candidate(implied_apy, spread, tvl, liquidity, days, mm_count,
                    borrow_cost=0, pt_discount=0, leverage=1, has_contango=False):
    """Score a loop candidate (0-100)."""
    # Spread score
    s = min(spread / SPREAD_MAX_SCORE, SPREAD_CAP) * WEIGHT_SPREAD

    # TVL score
    s += min(max(tvl, liquidity) / TVL_MAX_SCORE, TVL_CAP) * WEIGHT_TVL

    # Days score - prefer medium term
    if days < 0:
        s += DAYS_NEGATIVE
    elif days < 7:
        s += DAYS_VERY_SHORT
    elif days < 30:
        s += DAYS_SHORT
    elif days <= 180:
        s += DAYS_MEDIUM
    elif days <= 365:
        s += DAYS_LONG
    else:
        s += DAYS_VERY_LONG

    # Borrow cost score - lower is better
    borrow_score = 0 if borrow_cost > BORROW_MAX else (1 - borrow_cost / BORROW_MAX) * WEIGHT_BORROW
    s += borrow_score

    # PT discount score
    s += min(pt_discount / PT_DISCOUNT_MAX, 1.0) * WEIGHT_PT_DISCOUNT

    # Leverage score
    lev_score = min((leverage - 1) / (LEVERAGE_MAX - 1), 1.0) * WEIGHT_LEVERAGE if leverage > 1 else 0
    s += lev_score

    # Money market count
    s += min(mm_count, 5) * 4

    # Contango bonus
    if has_contango:
        s += CONTANGO_BONUS

    # TVL penalty for low liquidity
    if tvl < TVL_PENALTY_THRESHOLD:
        s -= TVL_PENALTY

    return round(max(s, 0), 2)
