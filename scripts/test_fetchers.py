"""Quick test of the 3 fetcher modules."""

import logging
import time

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from utils.fetch_aave import fetch_aave_data
from utils.fetch_morpho import fetch_morpho_data
from utils.fetch_euler import fetch_euler_data

print("=" * 60)
print("Testing 3 fetcher modules")
print("=" * 60)

# AAVE
t0 = time.time()
aave = fetch_aave_data(chain_ids=[1])
t_aave = time.time() - t0
print(f"\n✅ AAVE ({t_aave:.1f}s): {len(aave['pt_tokens'])} PT tokens, {len(aave['stable_borrow'])} stable rates")
for sym, d in aave["stable_borrow"].items():
    print(f"    {sym}: borrow {d['borrow_apy']*100:.2f}% | liq ${d['available_liquidity_usd']:,.0f}")

# Morpho
t0 = time.time()
morpho = fetch_morpho_data(min_supply_usd=5000)
t_morpho = time.time() - t0
print(f"\n✅ Morpho ({t_morpho:.1f}s): {len(morpho['pt_markets'])} PT markets")
for m in morpho["pt_markets"][:5]:
    print(f"    {m['collateral_symbol']} / {m['loan_symbol']} | LLTV {m['lltv']:.0%} | borrow {m['borrow_apy']*100:.2f}% | liq ${m['liquidity_usd']:,.0f}")

# Euler
t0 = time.time()
euler = fetch_euler_data(min_cash_or_borrows=100)
t_euler = time.time() - t0
print(f"\n✅ Euler ({t_euler:.1f}s): {len(euler['pt_vaults'])} PT vaults, {len(euler['stable_vaults'])} stable vaults")
for v in euler["stable_vaults"][:5]:
    print(f"    {v['symbol']} | borrow {v['borrow_apy_pct']:.2f}% | cash {v['cash']:,.0f} | borrows {v['borrows']:,.0f}")

print(f"\nTotal time: {t_aave + t_morpho + t_euler:.1f}s")
print("=" * 60)