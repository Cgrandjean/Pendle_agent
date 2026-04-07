"""Client for the Pendle MCP server (StreamableHTTP / JSON-RPC)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from agents.config import PENDLE_MCP_URL

logger = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

_request_id = 0


def _next_id() -> int:
    global _request_id
    _request_id += 1
    return _request_id


def _parse_sse_response(text: str) -> Any:
    """Parse an SSE response and extract the JSON-RPC result."""
    for line in text.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            if "result" in payload:
                return payload["result"]
            if "error" in payload:
                raise RuntimeError(f"MCP error: {payload['error']}")
    raise RuntimeError(f"No valid SSE data in response: {text[:300]}")


# Rate-limit: 1 second cooldown between MCP calls
_last_call_time: float = 0.0


async def call_tool(name: str, arguments: dict | None = None) -> Any:
    """Call a single MCP tool on the Pendle server and return the result."""
    global _last_call_time
    import time

    # Enforce 1s cooldown between calls
    now = time.monotonic()
    elapsed = now - _last_call_time
    if elapsed < 1.0:
        await asyncio.sleep(1.0 - elapsed)
    _last_call_time = time.monotonic()

    body = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments or {},
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(PENDLE_MCP_URL, headers=_HEADERS, json=body)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        return _parse_sse_response(resp.text)
    # Plain JSON response
    data = resp.json()
    if "result" in data:
        return data["result"]
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")
    return data


# ── Convenience wrappers ──────────────────────────────────────────────


async def get_chains() -> list[int]:
    """Return list of chain IDs with active Pendle markets."""
    result = await call_tool("get_chains")
    # result might be wrapped in {"content": [{"text": "..."}]}
    return _extract(result)


async def get_markets(
    chain_id: int | None = None,
    filters: list[dict] | None = None,
    sort_field: str = "details_impliedApy",
    sort_dir: str = "desc",
    include: list[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    """Query Pendle markets with optional filters."""
    f = list(filters or [])
    if chain_id is not None:
        f.append({"field": "chainId", "op": "=", "value": chain_id})

    args: dict[str, Any] = {
        "sort": {"field": sort_field, "direction": sort_dir},
        "include": include or ["all"],
        "limit": limit,
    }
    if f:
        args["filter"] = f

    result = await call_tool("get_markets", args)
    return _extract(result)


async def get_market(chain_id: int, market: str) -> dict:
    """Get full details for a single market."""
    result = await call_tool("get_market", {"chainId": chain_id, "market": market})
    return _extract(result)


async def get_external_protocols(
    chain_id: int | None = None,
    market: str | None = None,
) -> list[dict]:
    """Get external protocol integrations (Aave, Morpho, Euler, etc.)."""
    args: dict[str, Any] = {}
    if chain_id is not None:
        args["chainId"] = chain_id
    if market is not None:
        args["market"] = market
    result = await call_tool("get_external_protocols", args)
    return _extract(result)


async def get_asset(chain_id: int, address: str) -> dict:
    """Get metadata for a token."""
    result = await call_tool("get_asset", {"chainId": chain_id, "address": address})
    return _extract(result)


# ── Helpers ───────────────────────────────────────────────────────────


def _extract(result: Any) -> Any:
    """MCP tools often wrap output in {content: [{type: "text", text: "..."}]}.
    This helper unwraps that and parses JSON if needed."""
    if isinstance(result, dict) and "content" in result:
        parts = result["content"]
        if isinstance(parts, list) and parts:
            text = parts[0].get("text", "")
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
    return result