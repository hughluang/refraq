"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { requestToolsList, type McpToolsListResult } from "@/features/mcp/mcp-tools-list";

export type McpPatOutcome =
  | { status: "unverified" }
  | { status: "verified"; userId: string }
  | { status: "rejected" }
  | { status: "auth-error" };

export type McpEndpointDiscovery = McpToolsListResult | { status: "idle" };

type McpWorkspace = {
  pat: string;
  outcome: McpPatOutcome;
  discoveryByEndpoint: Readonly<Record<string, McpEndpointDiscovery>>;
  setPat: (value: string) => void;
  setOutcome: (submittedPat: string, outcome: McpPatOutcome) => void;
  discover: (endpoint: string) => Promise<void>;
  noteDetailEndpoint: (endpoint: string) => void;
};

const McpWorkspaceContext = createContext<McpWorkspace | null>(null);

/** Workspace-scoped PAT. Unmounting this provider drops the secret. */
export function McpWorkspaceProvider({ children }: { children: ReactNode }) {
  const [pat, setPatState] = useState("");
  const [outcome, setOutcomeState] = useState<McpPatOutcome>({ status: "unverified" });
  const [discoveryByEndpoint, setDiscoveryByEndpoint] = useState<
    Record<string, McpEndpointDiscovery>
  >({});
  const patRef = useRef("");
  const outcomeRef = useRef(outcome);
  const epochRef = useRef(0);
  const requestGen = useRef<Record<string, number>>({});
  const detailEndpointRef = useRef<string | null>(null);
  outcomeRef.current = outcome;

  const clearDiscovery = useCallback(() => {
    epochRef.current += 1;
    requestGen.current = {};
    setDiscoveryByEndpoint({});
  }, []);

  const setPat = useCallback((value: string) => {
    if (patRef.current === value) return;
    patRef.current = value;
    setPatState(value);
    setOutcomeState({ status: "unverified" });
    clearDiscovery();
  }, [clearDiscovery]);

  const noteDetailEndpoint = useCallback((endpoint: string) => {
    if (endpoint !== "/mcp" && endpoint !== "/mcp/entity") return;
    const previous = detailEndpointRef.current;
    if (previous === endpoint) return;
    detailEndpointRef.current = endpoint;
    if (previous === null) return;
    clearDiscovery();
  }, [clearDiscovery]);

  const setOutcome = useCallback((submittedPat: string, next: McpPatOutcome) => {
    if (patRef.current !== submittedPat) return;
    setOutcomeState(next);
  }, []);

  const discover = useCallback(async (endpoint: string) => {
    if (outcomeRef.current.status !== "verified") return;
    const submittedPat = patRef.current;
    const epoch = epochRef.current;
    const generation = (requestGen.current[endpoint] ?? 0) + 1;
    requestGen.current[endpoint] = generation;
    const next = await requestToolsList(endpoint, submittedPat);
    if (epochRef.current !== epoch) return;
    if (requestGen.current[endpoint] !== generation) return;
    setDiscoveryByEndpoint((current) => ({ ...current, [endpoint]: next }));
  }, []);

  useEffect(() => {
    // Logout uses location.assign. The back-forward cache can restore this state.
    function onPageShow(event: PageTransitionEvent) {
      if (!event.persisted) return;
      setPat("");
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [setPat]);

  const value = useMemo(
    () => ({ pat, outcome, discoveryByEndpoint, setPat, setOutcome, discover, noteDetailEndpoint }),
    [pat, outcome, discoveryByEndpoint, setPat, setOutcome, discover, noteDetailEndpoint],
  );
  return <McpWorkspaceContext.Provider value={value}>{children}</McpWorkspaceContext.Provider>;
}

export function useMcpWorkspace(): McpWorkspace {
  const workspace = useContext(McpWorkspaceContext);
  if (!workspace) {
    throw new Error("McpWorkspaceProvider is required");
  }
  return workspace;
}
