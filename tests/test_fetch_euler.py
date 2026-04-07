"""Integration tests for utils/fetch_euler.py — calls real Euler Goldsky subgraph."""

import pytest

from utils.fetch_euler import fetch_euler_data


@pytest.fixture(scope="module")
def euler_data():
    """Fetch Euler data once for all tests in this module."""
    return fetch_euler_data(min_cash_or_borrows=100)


class TestFetchEulerStructure:
    def test_returns_dict(self, euler_data):
        assert isinstance(euler_data, dict)

    def test_has_pt_vaults_key(self, euler_data):
        assert "pt_vaults" in euler_data

    def test_has_stable_vaults_key(self, euler_data):
        assert "stable_vaults" in euler_data

    def test_pt_vaults_is_list(self, euler_data):
        assert isinstance(euler_data["pt_vaults"], list)

    def test_stable_vaults_is_list(self, euler_data):
        assert isinstance(euler_data["stable_vaults"], list)


class TestFetchEulerPTVaults:
    def test_has_pt_vaults(self, euler_data):
        assert len(euler_data["pt_vaults"]) > 0, "Should find PT vaults on Euler"

    def test_pt_vault_has_required_fields(self, euler_data):
        for v in euler_data["pt_vaults"][:1]:
            assert "symbol" in v
            assert "name" in v
            assert "asset" in v
            assert "cash" in v
            assert "borrows" in v
            assert "borrow_apy_pct" in v

    def test_pt_symbol_contains_pt(self, euler_data):
        for v in euler_data["pt_vaults"][:10]:
            assert "PT" in v["symbol"].upper(), f"Symbol {v['symbol']} should contain 'PT'"


class TestFetchEulerStableVaults:
    def test_has_stable_vaults(self, euler_data):
        assert len(euler_data["stable_vaults"]) > 0, "Should find stable vaults on Euler"

    def test_stable_vault_has_required_fields(self, euler_data):
        for v in euler_data["stable_vaults"][:1]:
            assert "symbol" in v
            assert "cash" in v
            assert "borrows" in v
            assert "borrow_apy_pct" in v
            assert "collaterals_count" in v

    def test_borrow_apy_non_negative(self, euler_data):
        for v in euler_data["stable_vaults"]:
            assert v["borrow_apy_pct"] >= 0, f"Negative APY for {v['symbol']}"

    def test_sorted_by_total_size(self, euler_data):
        vaults = euler_data["stable_vaults"]
        if len(vaults) >= 2:
            sizes = [v["cash"] + v["borrows"] for v in vaults]
            assert sizes[0] >= sizes[1], "Stable vaults should be sorted by total size desc"