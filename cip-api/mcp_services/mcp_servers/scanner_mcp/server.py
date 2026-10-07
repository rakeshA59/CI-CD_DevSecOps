"""Scanner MCP Server – exposes the security scanners as MCP tools (SSE on port 8051).

Run:  python -m mcp_services.mcp_servers.scanner_mcp.server
Any MCP client (DevOps, Claude Desktop, another app) can then call list_scanners / run_scanner / trivy_image_scan /
ensure_scanner.
"""

import logging

from mcp.server.fastmcp import FastMCP

from mcp_services.mcp_servers.scanner_mcp import scanners

logging.basicConfig(level=logging.INFO)
mcp = FastMCP("DevOps Scanner MCP Server", host="0.0.0.0", port=8051)


@mcp.tool()
async def list_scanners() -> dict:
    """All scanners (SAST, lint, dependency, secret, platform) with whether each one is installed / configured."""
    return await scanners.list_scanners()


@mcp.tool()
async def run_scanner(name: str, path: str, context: dict | None = None) -> dict:
    """Run one scanner on a source folder. name: semgrep, bandit, codeql, ruff, eslint, trivy-fs, osv-scanner,
    pip-audit, npm-audit, snyk, gitleaks, trufflehog, sonarqube, github-alerts. context: {components, github_repo,
    project, semgrep_configs}. Secret values are never returned."""
    return await scanners.run_scanner(name, path, context)


@mcp.tool()
async def trivy_image_scan(image: str) -> dict:
    """OS and library CVEs inside a built container image."""
    return await scanners.trivy_image_scan(image)


@mcp.tool()
async def ensure_scanner(name: str, force: bool = False) -> dict:
    """Self-healing: install a missing scanner into .scanners, or reinstall a broken one (force=true)."""
    return await scanners.ensure_scanner(name, force)


if __name__ == "__main__":
    mcp.run(transport="sse")
