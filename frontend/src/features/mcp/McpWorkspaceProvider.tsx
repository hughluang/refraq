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

export type McpPatOutcome =
  | { status: "unverified" }
  | { status: "verified"; userId: string }
  | { status: "rejected" }
  | { status: "auth-error" };

type McpWorkspace = {
  pat: string;
  outcome: McpPatOutcome;
  setPat: (value: string) => void;
  setOutcome: (submittedPat: string, outcome: McpPatOutcome) => void;
};

const McpWorkspaceContext = createContext<McpWorkspace | null>(null);

/** Workspace-scoped PAT. Unmounting this provider drops the secret. */
export function McpWorkspaceProvider({ children }: { children: ReactNode }) {
  const [pat, setPatState] = useState("");
  const [outcome, setOutcomeState] = useState<McpPatOutcome>({ status: "unverified" });
  const patRef = useRef("");

  const setPat = useCallback((value: string) => {
    if (patRef.current === value) return;
    patRef.current = value;
    setPatState(value);
    setOutcomeState({ status: "unverified" });
  }, []);

  const setOutcome = useCallback((submittedPat: string, next: McpPatOutcome) => {
    if (patRef.current !== submittedPat) return;
    setOutcomeState(next);
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
    () => ({ pat, outcome, setPat, setOutcome }),
    [pat, outcome, setPat, setOutcome],
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
