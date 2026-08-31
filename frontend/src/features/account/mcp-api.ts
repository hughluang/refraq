export type McpCatalogTool = {
  name: string;
  permission: string;
  description: string;
};

export type McpCatalog = {
  public_path: string;
  tools: McpCatalogTool[];
};

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
