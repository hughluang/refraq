import type { ReactNode } from "react";

import { McpWorkspaceProvider } from "@/features/mcp/McpWorkspaceProvider";

export default function McpWorkspaceLayout({ children }: { children: ReactNode }) {
  return <McpWorkspaceProvider>{children}</McpWorkspaceProvider>;
}
