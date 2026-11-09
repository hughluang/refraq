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

import { checkArguments, type McpArgumentIssue } from "@/features/mcp/mcp-arguments";
import {
  requestToolsCall,
  requestToolsList,
  type McpCallOutcome,
  type McpToolsListResult,
} from "@/features/mcp/mcp-tools-list";

export type McpPatOutcome =
  | { status: "unverified" }
  | { status: "verified"; userId: string }
  | { status: "rejected" }
  | { status: "auth-error" };

export type McpEndpointDiscovery = McpToolsListResult | { status: "idle" };

export type McpInvocation = {
  endpoint: string;
  toolName: string;
  argumentsText: string;
  localError: McpArgumentIssue | null;
  outcome: McpCallOutcome | null;
};

type McpWorkspace = {
  pat: string;
  outcome: McpPatOutcome;
  discoveryByEndpoint: Readonly<Record<string, McpEndpointDiscovery>>;
  invocation: McpInvocation | null;
  setPat: (value: string) => void;
  setOutcome: (submittedPat: string, outcome: McpPatOutcome) => void;
  discover: (endpoint: string) => Promise<void>;
  noteDetailEndpoint: (endpoint: string) => void;
  selectTool: (endpoint: string, toolName: string) => void;
  setArgumentsText: (text: string) => void;
  runSelected: (endpoint: string, toolName: string, argumentsText: string) => Promise<void>;
};

const McpWorkspaceContext = createContext<McpWorkspace | null>(null);

/** Workspace-scoped PAT. Unmounting this provider drops the secret. */
export function McpWorkspaceProvider({ children }: { children: ReactNode }) {
  const [pat, setPatState] = useState("");
  const [outcome, setOutcomeState] = useState<McpPatOutcome>({ status: "unverified" });
  const [discoveryByEndpoint, setDiscoveryByEndpoint] = useState<
    Record<string, McpEndpointDiscovery>
  >({});
  const [invocation, setInvocation] = useState<McpInvocation | null>(null);
  const patRef = useRef("");
  const outcomeRef = useRef(outcome);
  const discoveryRef = useRef(discoveryByEndpoint);
  const epochRef = useRef(0);
  const requestGen = useRef<Record<string, number>>({});
  const callGen = useRef(0);
  const detailEndpointRef = useRef<string | null>(null);
  outcomeRef.current = outcome;
  discoveryRef.current = discoveryByEndpoint;

  const clearDiscovery = useCallback(() => {
    epochRef.current += 1;
    callGen.current += 1;
    requestGen.current = {};
    setDiscoveryByEndpoint({});
    setInvocation(null);
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

  const selectTool = useCallback((endpoint: string, toolName: string) => {
    setInvocation((prev) => {
      if (prev && prev.endpoint === endpoint && prev.toolName === toolName) return prev;
      callGen.current += 1;
      return {
        endpoint,
        toolName,
        argumentsText: "",
        localError: null,
        outcome: null,
      };
    });
  }, []);

  const setArgumentsText = useCallback((text: string) => {
    setInvocation((prev) => (prev ? { ...prev, argumentsText: text, localError: null } : prev));
  }, []);

  const runSelected = useCallback(async (endpoint: string, toolName: string, argumentsText: string) => {
    if (outcomeRef.current.status !== "verified") return;
    const discovery = discoveryRef.current[endpoint];
    if (!discovery || discovery.status !== "ready") return;
    const tool = discovery.tools.find((item) => item.name === toolName);
    if (!tool || tool.execution !== "read") return;
    const checked = checkArguments(argumentsText, tool.inputSchema);
    if (!checked.ok) {
      setInvocation((prev) =>
        prev && prev.endpoint === endpoint && prev.toolName === toolName
          ? { ...prev, localError: checked.issue }
          : prev,
      );
      return;
    }
    const generation = callGen.current + 1;
    callGen.current = generation;
    const submittedPat = patRef.current;
    setInvocation((prev) =>
      prev && prev.endpoint === endpoint && prev.toolName === toolName
        ? { ...prev, argumentsText, localError: null, outcome: null }
        : prev,
    );
    const next = await requestToolsCall(endpoint, submittedPat, toolName, checked.value);
    if (callGen.current !== generation) return;
    setInvocation((prev) => {
      if (!prev || prev.endpoint !== endpoint || prev.toolName !== toolName) return prev;
      return { ...prev, outcome: next };
    });
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
    () => ({
      pat,
      outcome,
      discoveryByEndpoint,
      invocation,
      setPat,
      setOutcome,
      discover,
      noteDetailEndpoint,
      selectTool,
      setArgumentsText,
      runSelected,
    }),
    [
      pat,
      outcome,
      discoveryByEndpoint,
      invocation,
      setPat,
      setOutcome,
      discover,
      noteDetailEndpoint,
      selectTool,
      setArgumentsText,
      runSelected,
    ],
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
