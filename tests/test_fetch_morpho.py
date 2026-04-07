"""Integration tests for utils/fetch_morpho.py — calls real Morpho API."""

import pytest

from utils.fetch_morpho import fetch_morpho_data


@pytest.fixture(scope="module")
def morpho_data():
    """Fetch Morpho data once for all tests in this module."""
    return fetch_morpho_data(min_supply_usd=1000)


class TestFetchMorphoStructure:
    def test_returns_dict(self, morpho_data):
        assert isinstance(morpho_data, dict)

    def test_has_pt_markets_key(self, morpho_data):
        assert "pt_markets" in morpho_data

    def test_pt_markets_is_list(self, morpho_data):
        assert isinstance(morpho_data["pt_markets"], list)


class TestFetchMorphoPTMarkets:
    def test_has_pt_markets(self, morpho_data):
        assert len(morpho_data["pt_markets"]) > 0, "Should find at least 1 PT market on Morpho"

    def test_market_has_required_fields(self, morpho_data):
        for m in morpho_data["pt_markets"][:1]:
            assert "collateral_symbol" in m
            assert "loan_symbol" in m
            assert "lltv" in m
            assert "borrow_apy" in m
            assert "supply_usd" in m
            assert "liquidity_usd" in m

    def test_lltv_in_range(self, morpho_data):
        for m in morpho_data["pt_markets"]:
            assert 0 < m["lltv"] <= 1.0, f"LLTV {m['lltv']} out of range for {m['collateral_symbol']}"

    def test_borrow_apy_non_negative(self, morpho_data):
        for m in morpho_data["pt_markets"]:
            assert m["borrow_apy"] >= 0, f"Negative borrow APY for {m['collateral_symbol']}"

    def test_collateral_contains_pt(self, morpho_data):
        for m in morpho_data["pt_markets"]:
            assert "PT" in m["collateral_symbol"].upper(), \
                f"Collateral {m['collateral_symbol']} should contain 'PT'"