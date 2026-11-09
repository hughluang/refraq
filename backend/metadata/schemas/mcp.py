"""HTTP shapes for the current User's MCP catalog.

Each tool is a catalog `McpToolSpec`, including `execution` (`read` or `write`).
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.metadata.mcp_catalog import McpToolSpec


class McpCatalogResponse(BaseModel):
    public_path: str
    tools: list[McpToolSpec]
