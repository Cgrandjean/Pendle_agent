"""Unit tests for utils/scoring.py — no network calls."""

from utils.scoring import score_candidate


class TestScoreCandidate:
    def test_returns_float(self):
        result = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=1_000_000,
            liquidity=500_000, days=60, mm_count=2,
            has_contango=False,
        )
        assert isinstance(result, float)

    def test_non_negative(self):
        result = score_candidate(
            implied_apy=0.001, spread=-0.01, tvl=100,
            liquidity=50, days=1, mm_count=0,
            has_contango=False,
        )
        assert result >= 0

    def test_higher_spread_higher_score(self):
        low = score_candidate(
            implied_apy=0.03, spread=0.01, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=2,
            has_contango=False,
        )
        high = score_candidate(
            implied_apy=0.06, spread=0.04, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=2,
            has_contango=False,
        )
        assert high > low

    def test_contango_bonus(self):
        without = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=2,
            has_contango=False,
        )
        with_contango = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=2,
            has_contango=True,
        )
        assert with_contango > without
        assert with_contango - without == 10

    def test_more_money_markets_higher_score(self):
        few = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=1,
            has_contango=False,
        )
        many = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=4,
            has_contango=False,
        )
        assert many > few

    def test_low_tvl_penalty(self):
        high_tvl = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=2,
            has_contango=False,
        )
        low_tvl = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=100_000,
            liquidity=50_000, days=90, mm_count=2,
            has_contango=False,
        )
        assert high_tvl > low_tvl

    def test_expiry_scoring_sweet_spot(self):
        short = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=5_000_000,
            liquidity=1_000_000, days=5, mm_count=2,
            has_contango=False,
        )
        sweet = score_candidate(
            implied_apy=0.05, spread=0.02, tvl=5_000_000,
            liquidity=1_000_000, days=90, mm_count=2,
            has_contango=False,
        )
        assert sweet > short