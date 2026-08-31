"""HTTP shapes for the current User's MCP catalog."""

from __future__ import annotations

from pydantic import BaseModel

from backend.metadata.mcp_catalog import McpToolSpec


class McpCatalogResponse(BaseModel):
    public_path: str
    tools: list[McpToolSpec]
