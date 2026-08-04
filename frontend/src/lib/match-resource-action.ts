import {
  matchResourceFromRoute,
  type IResourceItem,
} from "@refinedev/core";

export type MatchedResourceAction = {
  resource: string;
  action: string;
};

/**
 * Resolve Refine resource + action from a pathname against registered resources.
 * Returns null when no registered route matches (caller should allow through).
 */
export function matchResourceAction(
  pathname: string,
  resources: IResourceItem[],
): MatchedResourceAction | null {
  const matched = matchResourceFromRoute(pathname, resources);
  if (!matched.found || !matched.resource?.name || !matched.action) {
    return null;
  }
  return { resource: matched.resource.name, action: matched.action };
}
