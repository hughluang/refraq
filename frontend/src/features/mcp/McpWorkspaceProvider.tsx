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
  type McpStoredCallOutcome,
  type McpToolsListResult,
} from "@/features/mcp/mcp-tools-list";
import { useConfirmAction } from "@/hooks/useConfirmAction";

export type McpPatOutcome =
  | { status: "unverified" }
  | { status: "verified"; userId: string }
  | { status: "rejected" }
  | { status: "auth-error" };

export type McpEndpointDiscovery =
  | McpToolsListResult
  | { status: "idle" }
  | { status: "stopped" };

export type McpCallWait = {
  endpoint: string;
  toolName: string;
  effect: "read" | "write";
};

export type McpInvocation = {
  endpoint: string;
  toolName: string;
  argumentsText: string;
  localError: McpArgumentIssue | null;
  outcome: McpStoredCallOutcome | null;
  submittedArguments: string | null;
};

export type McpWriteConfirm = {
  endpoint: string;
  userId: string;
  toolName: string;
  argumentsJson: string;
  sending: boolean;
};

type WriteDraft = {
  endpoint: string;
  userId: string;
  toolName: string;
  argumentsText: string;
  args: unknown;
  sent: boolean;
};

type McpWorkspace = {
  pat: string;
  outcome: McpPatOutcome;
  discoveryByEndpoint: Readonly<Record<string, McpEndpointDiscovery>>;
  invocation: McpInvocation | null;
  writeConfirm: McpWriteConfirm | null;
  setPat: (value: string) => void;
  setOutcome: (submittedPat: string, outcome: McpPatOutcome) => void;
  discover: (endpoint: string) => Promise<void>;
  noteDetailEndpoint: (endpoint: string) => void;
  selectTool: (endpoint: string, toolName: string) => void;
  setArgumentsText: (text: string) => void;
  runSelected: (endpoint: string, toolName: string, argumentsText: string) => Promise<void>;
  beginWrite: (endpoint: string, toolName: string, argumentsText: string) => void;
  confirmWrite: () => Promise<void>;
  dismissWrite: () => void;
  callWait: McpCallWait | null;
  discoverWait: string | null;
  stopWaiting: (kind: "call" | "discover") => void;
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
  const [writeSending, setWriteSending] = useState(false);
  const writeAction = useConfirmAction<Omit<McpWriteConfirm, "sending">>();
  const patRef = useRef("");
  const outcomeRef = useRef(outcome);
  const discoveryRef = useRef(discoveryByEndpoint);
  const invocationRef = useRef<McpInvocation | null>(null);
  const writeRef = useRef<WriteDraft | null>(null);
  const epochRef = useRef(0);
  const requestGen = useRef<Record<string, number>>({});
  const callGen = useRef(0);
  const detailEndpointRef = useRef<string | null>(null);
  const callAbort = useRef<AbortController | null>(null);
  const discoverAbort = useRef<Record<string, AbortController>>({});
  const [callWait, setCallWait] = useState<McpCallWait | null>(null);
  const [discoverWait, setDiscoverWait] = useState<string | null>(null);
  const callWaitRef = useRef<McpCallWait | null>(null);
  const discoverWaitRef = useRef<string | null>(null);
  outcomeRef.current = outcome;
  discoveryRef.current = discoveryByEndpoint;
  invocationRef.current = invocation;

  const dropWriteConfirm = useCallback(() => {
    writeRef.current = null;
    setWriteSending(false);
    writeAction.close();
  }, [writeAction.close]);

  const clearCallWait = useCallback(() => {
    callWaitRef.current = null;
    setCallWait(null);
  }, []);

  const clearDiscoverWait = useCallback(() => {
    discoverWaitRef.current = null;
    setDiscoverWait(null);
  }, []);

  const quietAbortCall = useCallback(() => {
    callAbort.current?.abort();
    callAbort.current = null;
    clearCallWait();
  }, [clearCallWait]);

  const clearDiscovery = useCallback(() => {
    epochRef.current += 1;
    callGen.current += 1;
    requestGen.current = {};
    quietAbortCall();
    for (const controller of Object.values(discoverAbort.current)) controller.abort();
    discoverAbort.current = {};
    clearDiscoverWait();
    invocationRef.current = null;
    dropWriteConfirm();
    setDiscoveryByEndpoint({});
    setInvocation(null);
  }, [clearDiscoverWait, dropWriteConfirm, quietAbortCall]);

  const setPat = useCallback((value: string) => {
    if (patRef.current === value) return;
    patRef.current = value;
    setPatState(value);
    setOutcomeState({ status: "unverified" });
    clearDiscovery();
  }, [clearDiscovery]);

  const rejectCredential = useCallback(() => {
    setOutcomeState({ status: "auth-error" });
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
    const prev = invocationRef.current;
    if (prev && prev.endpoint === endpoint && prev.toolName === toolName) return;
    callGen.current += 1;
    quietAbortCall();
    const next: McpInvocation = {
      endpoint,
      toolName,
      argumentsText: "",
      localError: null,
      outcome: null,
      submittedArguments: null,
    };
    invocationRef.current = next;
    dropWriteConfirm();
    setInvocation(next);
  }, [dropWriteConfirm, quietAbortCall]);

  const setArgumentsText = useCallback((text: string) => {
    const snap = writeRef.current;
    if (snap && !snap.sent && snap.argumentsText !== text) dropWriteConfirm();
    setInvocation((prev) => {
      if (!prev) return prev;
      const next = { ...prev, argumentsText: text, localError: null };
      invocationRef.current = next;
      return next;
    });
  }, [dropWriteConfirm]);

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
    callAbort.current?.abort();
    const controller = new AbortController();
    callAbort.current = controller;
    const wait: McpCallWait = { endpoint, toolName, effect: "read" };
    callWaitRef.current = wait;
    setCallWait(wait);
    const submittedPat = patRef.current;
    const submittedArguments = JSON.stringify(checked.value);
    setInvocation((prev) => {
      if (!prev || prev.endpoint !== endpoint || prev.toolName !== toolName) return prev;
      const next = {
        ...prev,
        argumentsText,
        localError: null,
        outcome: null,
        submittedArguments,
      };
      invocationRef.current = next;
      return next;
    });
    const next = await requestToolsCall(
      endpoint,
      submittedPat,
      toolName,
      checked.value,
      controller.signal,
      false,
    );
    if (callGen.current !== generation) return;
    if (next.status === "rejected") {
      rejectCredential();
      return;
    }
    callAbort.current = null;
    callWaitRef.current = null;
    setCallWait(null);
    setInvocation((prev) => {
      if (!prev || prev.endpoint !== endpoint || prev.toolName !== toolName) return prev;
      const updated = { ...prev, outcome: next };
      invocationRef.current = updated;
      return updated;
    });
  }, [rejectCredential]);

  const beginWrite = useCallback((endpoint: string, toolName: string, argumentsText: string) => {
    if (outcomeRef.current.status !== "verified") return;
    const discovery = discoveryRef.current[endpoint];
    if (!discovery || discovery.status !== "ready") return;
    const tool = discovery.tools.find((item) => item.name === toolName);
    if (!tool || tool.execution !== "write") return;
    const current = writeRef.current;
    if (
      current &&
      !current.sent &&
      current.endpoint === endpoint &&
      current.toolName === toolName &&
      current.argumentsText === argumentsText
    ) {
      return;
    }
    const checked = checkArguments(argumentsText, tool.inputSchema);
    if (!checked.ok) {
      dropWriteConfirm();
      setInvocation((prev) => {
        if (!prev || prev.endpoint !== endpoint || prev.toolName !== toolName) return prev;
        const next = { ...prev, localError: checked.issue };
        invocationRef.current = next;
        return next;
      });
      return;
    }
    const draft: WriteDraft = {
      endpoint,
      userId: outcomeRef.current.userId,
      toolName,
      argumentsText,
      args: checked.value,
      sent: false,
    };
    writeRef.current = draft;
    setWriteSending(false);
    writeAction.open({
      endpoint: draft.endpoint,
      userId: draft.userId,
      toolName: draft.toolName,
      argumentsJson: JSON.stringify(checked.value),
    });
    setInvocation((prev) => {
      if (!prev || prev.endpoint !== endpoint || prev.toolName !== toolName) return prev;
      const next = { ...prev, localError: null };
      invocationRef.current = next;
      return next;
    });
  }, [dropWriteConfirm, writeAction.open]);

  const confirmWrite = useCallback(async () => {
    const snap = writeRef.current;
    if (!snap || snap.sent) return;
    if (outcomeRef.current.status !== "verified" || outcomeRef.current.userId !== snap.userId) {
      dropWriteConfirm();
      return;
    }
    snap.sent = true;
    setWriteSending(true);
    const generation = callGen.current + 1;
    callGen.current = generation;
    callAbort.current?.abort();
    const controller = new AbortController();
    callAbort.current = controller;
    const wait: McpCallWait = { endpoint: snap.endpoint, toolName: snap.toolName, effect: "write" };
    callWaitRef.current = wait;
    setCallWait(wait);
    const submittedPat = patRef.current;
    const { endpoint, toolName, args } = snap;
    const submittedArguments = JSON.stringify(args);
    setInvocation((prev) => {
      if (!prev || prev.endpoint !== endpoint || prev.toolName !== toolName) return prev;
      const next = { ...prev, localError: null, outcome: null, submittedArguments };
      invocationRef.current = next;
      return next;
    });
    const next = await requestToolsCall(endpoint, submittedPat, toolName, args, controller.signal, true);
    if (callGen.current !== generation) return;
    if (next.status === "rejected") {
      rejectCredential();
      return;
    }
    callAbort.current = null;
    callWaitRef.current = null;
    setCallWait(null);
    dropWriteConfirm();
    setInvocation((prev) => {
      if (!prev || prev.endpoint !== endpoint || prev.toolName !== toolName) return prev;
      const updated = { ...prev, outcome: next };
      invocationRef.current = updated;
      return updated;
    });
  }, [dropWriteConfirm, rejectCredential]);

  const discover = useCallback(async (endpoint: string) => {
    if (outcomeRef.current.status !== "verified") return;
    const submittedPat = patRef.current;
    const epoch = epochRef.current;
    const generation = (requestGen.current[endpoint] ?? 0) + 1;
    requestGen.current[endpoint] = generation;
    discoverAbort.current[endpoint]?.abort();
    const controller = new AbortController();
    discoverAbort.current[endpoint] = controller;
    discoverWaitRef.current = endpoint;
    setDiscoverWait(endpoint);
    setDiscoveryByEndpoint((current) => {
      if (current[endpoint]?.status !== "stopped") return current;
      return { ...current, [endpoint]: { status: "idle" } };
    });
    const next = await requestToolsList(endpoint, submittedPat, controller.signal);
    if (epochRef.current !== epoch) return;
    if (requestGen.current[endpoint] !== generation) return;
    if (next.status === "rejected") {
      rejectCredential();
      return;
    }
    delete discoverAbort.current[endpoint];
    if (discoverWaitRef.current === endpoint) {
      discoverWaitRef.current = null;
      setDiscoverWait(null);
    }
    const snap = writeRef.current;
    if (snap && !snap.sent && snap.endpoint === endpoint && next.status === "ready") {
      const tool = next.tools.find((item) => item.name === snap.toolName);
      if (!tool || tool.execution !== "write") dropWriteConfirm();
    }
    setDiscoveryByEndpoint((current) => ({ ...current, [endpoint]: next }));
  }, [dropWriteConfirm, rejectCredential]);

  const stopWaiting = useCallback((kind: "call" | "discover") => {
    if (kind === "discover") {
      const endpoint = discoverWaitRef.current;
      if (!endpoint) return;
      requestGen.current[endpoint] = (requestGen.current[endpoint] ?? 0) + 1;
      discoverAbort.current[endpoint]?.abort();
      delete discoverAbort.current[endpoint];
      discoverWaitRef.current = null;
      setDiscoverWait(null);
      setDiscoveryByEndpoint((current) => ({ ...current, [endpoint]: { status: "stopped" } }));
      return;
    }
    const wait = callWaitRef.current;
    if (!wait) return;
    callGen.current += 1;
    callAbort.current?.abort();
    callAbort.current = null;
    callWaitRef.current = null;
    setCallWait(null);
    if (wait.effect === "write") {
      dropWriteConfirm();
      setInvocation((prev) => {
        if (!prev || prev.endpoint !== wait.endpoint || prev.toolName !== wait.toolName) return prev;
        const next = {
          ...prev,
          outcome: { status: "unknown" as const, requestedCancellation: true },
        };
        invocationRef.current = next;
        return next;
      });
      return;
    }
    setInvocation((prev) => {
      if (!prev || prev.endpoint !== wait.endpoint || prev.toolName !== wait.toolName) return prev;
      const next = { ...prev, outcome: { status: "stopped" as const } };
      invocationRef.current = next;
      return next;
    });
  }, [dropWriteConfirm]);

  useEffect(() => {
    // Logout uses location.assign. The back-forward cache can restore this state.
    function onPageShow(event: PageTransitionEvent) {
      if (!event.persisted) return;
      setPat("");
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [setPat]);

  useEffect(() => {
    return () => {
      epochRef.current += 1;
      callGen.current += 1;
      requestGen.current = {};
      callAbort.current?.abort();
      for (const controller of Object.values(discoverAbort.current)) controller.abort();
    };
  }, []);

  const writeConfirm = writeAction.pending
    ? { ...writeAction.pending, sending: writeSending }
    : null;
  const value = useMemo(
    () => ({
      pat,
      outcome,
      discoveryByEndpoint,
      invocation,
      writeConfirm,
      setPat,
      setOutcome,
      discover,
      noteDetailEndpoint,
      selectTool,
      setArgumentsText,
      runSelected,
      beginWrite,
      confirmWrite,
      dismissWrite: dropWriteConfirm,
      callWait,
      discoverWait,
      stopWaiting,
    }),
    [
      pat,
      outcome,
      discoveryByEndpoint,
      invocation,
      writeConfirm,
      setPat,
      setOutcome,
      discover,
      noteDetailEndpoint,
      selectTool,
      setArgumentsText,
      runSelected,
      beginWrite,
      confirmWrite,
      dropWriteConfirm,
      callWait,
      discoverWait,
      stopWaiting,
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
