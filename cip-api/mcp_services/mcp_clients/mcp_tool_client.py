"""
MCP Tool Client – calls a tool on a CIP MCP server over SSE (like sdlc-api's GitMCPClient).

When the server is not running, the same function is called in-process, so the pipeline never depends on the
MCP servers being started. `last_transport` tells which path was used (shown in the step's evidence).
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict
from urllib.parse import urlparse

from mcp import ClientSession
from mcp.client.sse import sse_client

from core.settings import DOCKER_MCP_URL, SCANNER_MCP_URL
from mcp_services.mcp_servers.docker_mcp.docker_ops import DOCKER_OPS
from mcp_services.mcp_servers.scanner_mcp.scanners import SCANNERS


class MCPToolClient:
    def __init__(self, server_url: str, local_tools: Dict[str, Callable]):
        self.server_url = server_url
        self.local_tools = local_tools
        self.last_transport = ""

    async def _reachable(self) -> bool:
        """Quick TCP check, so a stopped server costs milliseconds, not a timeout."""
        u = urlparse(self.server_url)
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(u.hostname, u.port or 80), timeout=1)
            w.close()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call the tool via MCP (SSE); fall back to the in-process implementation."""
        if await self._reachable():
            try:
                async with sse_client(self.server_url, timeout=5, sse_read_timeout=1800) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, arguments)
                self.last_transport = f"MCP {self.server_url}"
                if result.structuredContent:
                    return result.structuredContent.get("result", result.structuredContent)
                text = "".join(getattr(c, "text", "") for c in result.content)
                return json.loads(text) if text else {}
            except Exception as e:  # noqa: BLE001
                logging.warning("[MCPToolClient] MCP call %s failed (%s) – calling it in-process", tool_name, e)
        self.last_transport = f"run directly by the API (MCP server {self.server_url} not started – same tool, same result)"
        return await self.local_tools[tool_name](**arguments)


def scanner_client() -> MCPToolClient:
    return MCPToolClient(SCANNER_MCP_URL, SCANNERS)


def docker_client() -> MCPToolClient:
    return MCPToolClient(DOCKER_MCP_URL, DOCKER_OPS)
