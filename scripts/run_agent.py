"""Run the full LoopScoutAgent graph and display results."""

import asyncio
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Ensure project root is in path
sys.path.insert(0, ".")

from agents.loop_scout_agent import LoopScoutAgent


async def main():
    args = sys.argv[1:]
    count = 100
    asset = "stable"
    chain = None

    # Simple parsing: /loop [count] [asset] [chain]
    if args:
        count = int(args[0]) if args[0].isdigit() else count
        if len(args) > 1:
            asset = args[1]
        if len(args) > 2:
            chain = args[2]

    query_desc = f"count={count} asset={asset} chain={chain}"
    print("=" * 80)
    print(f"Running LoopScoutAgent with query: '{query_desc}'")
    print("=" * 80)

    agent = LoopScoutAgent()
    t0 = time.time()
    output = await agent.run(count=count, asset=asset, chain=chain)
    elapsed = time.time() - t0

    print("\n" + "=" * 80)
    print(f"RESULT ({elapsed:.1f}s)")
    print("=" * 80)
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
