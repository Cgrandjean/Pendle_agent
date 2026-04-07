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
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "top 5 stable loops"

    print("=" * 80)
    print(f"Running LoopScoutAgent with query: '{query}'")
    print("=" * 80)

    agent = LoopScoutAgent()
    t0 = time.time()
    output = await agent.run(query)
    elapsed = time.time() - t0

    print("\n" + "=" * 80)
    print(f"RESULT ({elapsed:.1f}s)")
    print("=" * 80)
    print(output)


if __name__ == "__main__":
    asyncio.run(main())