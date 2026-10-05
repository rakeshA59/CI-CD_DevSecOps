"""Docker MCP Server – build, run and remove containers as MCP tools (SSE on port 8052).

Run:  python -m mcp_services.mcp_servers.docker_mcp.server
"""

import logging

from mcp.server.fastmcp import FastMCP

from mcp_services.mcp_servers.docker_mcp import docker_ops

logging.basicConfig(level=logging.INFO)
mcp = FastMCP("CIP Docker MCP Server", host="0.0.0.0", port=8052)


@mcp.tool()
async def docker_status() -> dict:
    """Whether the Docker daemon is running, and its version."""
    return await docker_ops.docker_status()


@mcp.tool()
async def docker_build(context: str, tag: str, dockerfile: str = "Dockerfile") -> dict:
    """Build an image from a folder and load it into the local image store."""
    return await docker_ops.docker_build(context, tag, dockerfile)


@mcp.tool()
async def docker_run(image: str, name: str, network: str, port: int, env: dict | None = None, alias: str = "") -> dict:
    """Run an image on a private network, publish its port and wait until it answers HTTP."""
    return await docker_ops.docker_run(image, name, network, port, env, alias)


@mcp.tool()
async def docker_remove(names: list[str], network: str = "") -> dict:
    """Remove containers and the network."""
    return await docker_ops.docker_remove(names, network)


@mcp.tool()
async def docker_registry(port: int = 5000) -> dict:
    """Make sure a local image registry (registry:2) is running on localhost:<port>."""
    return await docker_ops.docker_registry(port)


@mcp.tool()
async def docker_push(image: str, registry: str, repository: str) -> dict:
    """Tag a local image as <registry>/<repository>:<tag> and push it to the registry."""
    return await docker_ops.docker_push(image, registry, repository)


if __name__ == "__main__":
    mcp.run(transport="sse")
