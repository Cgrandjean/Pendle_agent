"""Integration tests for utils/fetch_aave.py — calls real AAVE API."""

import pytest

from utils.fetch_aave import fetch_aave_data


@pytest.fixture(scope="module")
def aave_data():
    """Fetch AAVE data once for all tests in this module."""
    return fetch_aave_data(chain_ids=[1])


class TestFetchAaveStructure:
    def test_returns_dict(self, aave_data):
        assert isinstance(aave_data, dict)

    def test_has_pt_tokens_key(self, aave_data):
        assert "pt_tokens" in aave_data

    def test_has_stable_borrow_key(self, aave_data):
        assert "stable_borrow" in aave_data

    def test_pt_tokens_is_dict(self, aave_data):
        assert isinstance(aave_data["pt_tokens"], dict)

    def test_stable_borrow_is_dict(self, aave_data):
        assert isinstance(aave_data["stable_borrow"], dict)


class TestFetchAavePTTokens:
    def test_has_pt_tokens(self, aave_data):
        assert len(aave_data["pt_tokens"]) > 0, "Should find at least 1 PT token on AAVE"

    def test_pt_token_has_required_fields(self, aave_data):
        for addr, pt in aave_data["pt_tokens"].items():
            assert "symbol" in pt
            assert "PT" in pt["symbol"].upper()
            assert "address" in pt
            assert "can_be_collateral" in pt
            assert "ltv" in pt
            assert "is_frozen" in pt
            break  # Test first one


class TestFetchAaveStableBorrow:
    def test_has_stable_rates(self, aave_data):
        assert len(aave_data["stable_borrow"]) > 0, "Should find stable borrow rates"

    def test_known_stables_present(self, aave_data):
        stables = aave_data["stable_borrow"]
        assert any(s in stables for s in ["USDC", "USDT", "DAI"]), \
            f"Expected USDC/USDT/DAI in {list(stables.keys())}"

    def test_borrow_apy_is_reasonable(self, aave_data):
        for sym, d in aave_data["stable_borrow"].items():
            apy = d.get("borrow_apy", 0)
            assert 0 <= apy < 1.0, f"{sym} borrow APY {apy} out of range [0, 1)"

    def test_stable_has_required_fields(self, aave_data):
        for sym, d in aave_data["stable_borrow"].items():
            assert "symbol" in d
            assert "borrow_apy" in d
            assert "available_liquidity_usd" in d
            assert "borrowing_state" in d
            break