export const METADATA_MCP_PUBLIC_PATH = "/mcp";
export const ENTITY_MCP_PUBLIC_PATH = "/mcp/entity";
export const METADATA_MCP_CATALOG_PATH = "/mcp/catalog";
export const ENTITY_MCP_CATALOG_PATH = "/mcp/entity/catalog";

export type McpCatalogTool = {
  name: string;
  permission: string;
  description: string;
  execution?: string;
};

export type McpCatalog = {
  tools: McpCatalogTool[];
};

export function mcpCatalogPath(publicPath: string): string {
  return publicPath === ENTITY_MCP_PUBLIC_PATH
    ? ENTITY_MCP_CATALOG_PATH
    : METADATA_MCP_CATALOG_PATH;
}

/** Secret-free client configuration. The placeholder is not a live PAT. */
export function mcpClientConfig(origin: string, publicPath: string): string {
  return JSON.stringify(
    {
      url: `${origin}${publicPath}`,
      headers: {
        Authorization: "Bearer <YOUR_TOKEN>",
      },
    },
    null,
    2,
  );
}
