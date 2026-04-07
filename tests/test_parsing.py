"""Unit tests for utils/parsing.py — no network calls."""

from datetime import datetime, timezone, timedelta

from utils.parsing import (
    days_to_expiry, matches_asset_family, detect_asset_family,
    parse_pt_expiry_from_symbol, is_pt_not_expired,
)


class TestDaysToExpiry:
    def test_none_returns_negative(self):
        assert days_to_expiry(None) == -1

    def test_empty_string_returns_negative(self):
        assert days_to_expiry("") == -1

    def test_invalid_string_returns_negative(self):
        assert days_to_expiry("not-a-date") == -1

    def test_future_date(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        result = days_to_expiry(future)
        assert 29 < result < 31

    def test_past_date_returns_zero(self):
        past = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        result = days_to_expiry(past)
        assert result == 0

    def test_iso_with_z_suffix(self):
        future = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = days_to_expiry(future)
        assert 9 < result < 11


class TestMatchesAssetFamily:
    def test_stable_match(self):
        assert matches_asset_family("PT-USDC-30SEP2025", "stable") is True

    def test_eth_match(self):
        assert matches_asset_family("PT-wstETH-30SEP2025", "eth") is True

    def test_btc_match(self):
        assert matches_asset_family("PT-LBTC-30SEP2025", "btc") is True

    def test_no_match(self):
        assert matches_asset_family("PT-XYZ-30SEP2025", "stable") is False

    def test_case_insensitive(self):
        assert matches_asset_family("PT-USDC-30SEP2025", "stable") is True


class TestDetectAssetFamily:
    def test_stable(self):
        assert detect_asset_family("PT-sUSDE-25SEP2025") == "stable"

    def test_eth(self):
        assert detect_asset_family("PT-weETH-25SEP2025") == "eth"

    def test_btc(self):
        assert detect_asset_family("PT-WBTC-25SEP2025") == "btc"

    def test_other(self):
        assert detect_asset_family("PT-UNKNOWN-25SEP2025") == "other"


class TestParsePtExpiryFromSymbol:
    def test_standard_format(self):
        result = parse_pt_expiry_from_symbol("PT-USDE-5FEB2026")
        assert result == datetime(2026, 2, 5, tzinfo=timezone.utc)

    def test_euler_format(self):
        result = parse_pt_expiry_from_symbol("ePT-tUSDe-18DEC2025")
        assert result == datetime(2025, 12, 18, tzinfo=timezone.utc)

    def test_two_digit_day(self):
        result = parse_pt_expiry_from_symbol("PT-USDC-14AUG2025")
        assert result == datetime(2025, 8, 14, tzinfo=timezone.utc)

    def test_no_date(self):
        assert parse_pt_expiry_from_symbol("PT-USDC") is None

    def test_empty_string(self):
        assert parse_pt_expiry_from_symbol("") is None


class TestIsPtNotExpired:
    def test_future_pt(self):
        assert is_pt_not_expired("PT-USDE-5FEB2030") is True

    def test_past_pt(self):
        assert is_pt_not_expired("PT-USDE-1JAN2020") is False

    def test_no_date_returns_true(self):
        # Conservative: if we can't parse, keep it
        assert is_pt_not_expired("PT-UNKNOWN") is True
