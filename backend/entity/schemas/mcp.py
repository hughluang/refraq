"""HTTP shape for the current User's Entity MCP catalog.

Each tool is a catalog `McpToolSpec`, including `execution` (`read` or `write`).
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.entity.mcp.catalog import McpToolSpec


class McpCatalogResponse(BaseModel):
    public_path: str
    tools: list[McpToolSpec]
