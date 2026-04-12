"""Scoring for loop candidates."""


def score_candidate(implied_apy, spread, tvl, liquidity, days, mm_count, 
                    borrow_cost=0, pt_discount=0, leverage=1, has_contango=False):
    """
    Score a loop candidate.
    
    Factors:
    - spread: higher is better (raw yield opportunity)
    - tvl/liquidity: higher is better
    - days: medium-term (30-180d) is best
    - borrow_cost: lower is better (max 30% realistic)
    - pt_discount: higher is better (bigger discount = better entry)
    - leverage: higher is better but capped at 10x
    - mm_count: more money markets = more options
    """
    # Spread score (35% weight) - higher spread = better loop margin
    s = min(spread / 0.05, 3.0) * 35
    
    # TVL score (15% weight) - liquidity matters
    s += min(max(tvl, liquidity) / 10_000_000, 2.0) * 15
    
    # Days score (15% weight) - prefer medium term
    if days < 0:
        s += 5
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
    
    # Borrow cost score (20% weight) - lower is better
    # Normalize: 0% borrow = max score, 30%+ = 0 score
    if borrow_cost > 0.30:
        borrow_score = 0
    else:
        borrow_score = (1 - borrow_cost / 0.30) * 20
    s += borrow_score
    
    # PT discount score (5% weight) - bigger discount = better entry
    # PT discount is typically 0-20%, normalize to 0-5 points
    s += min(pt_discount / 0.10, 1.0) * 5
    
    # Leverage score (5% weight) - higher leverage amplifies the spread
    # Cap at 10x, normalize: 1x = 0, 10x = 5
    if leverage > 1:
        lev_score = min((leverage - 1) / 9, 1.0) * 5
    else:
        lev_score = 0
    s += lev_score
    
    # Money market count (5% weight) - more options = more reliable
    s += min(mm_count, 5) * 4
    
    # Contango bonus
    if has_contango:
        s += 10
        
    # TVL penalty for low liquidity
    if tvl < 500_000:
        s -= 5

    return round(max(s, 0), 2)
