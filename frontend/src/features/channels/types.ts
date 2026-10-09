export type GraphNode = {
  id: string;
  type: string;
  name: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
  on_error: "stop" | "continue" | "error_output";
  retry: { max_tries: number; wait_sec: number } | null;
};

export type GraphEdge = {
  id: string;
  source: { node_id: string; port: string };
  target: { node_id: string; port: string };
};

export type GraphSettings = {
  run_timeout_sec: number | null;
  error_channel_id: string | null;
};

export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  settings: GraphSettings;
};

export type Channel = {
  id: string;
  name: string;
  description: string | null;
  active: boolean;
  draft_revision: number;
  draft_updated_at: string;
  latest_version: { number: number; published_at: string } | null;
  created_at: string;
  updated_at: string;
};

export type ChannelDraft = {
  draft_revision: number;
  draft_updated_at: string;
  graph: Graph;
};

export type ChannelVersion = {
  channel_id: string;
  number: number;
  graph?: Graph;
  published_at: string;
  published_by_user_id: string;
  published_by_name: string | null;
};

export type Confirmation = {
  draft_revision: number;
  mirrors_to_open: { object_id: string; locator: string }[];
  runs_to_cancel: { job_id: string; version: number; started_at: string }[];
  missing_run_timeout: boolean;
};

export type GraphProblem = {
  code: string;
  node_id: string | null;
  edge_id: string | null;
  detail: string;
};

export type NodeTypePort = {
  port: string;
  description: string;
};

export type NodeTypeSpec = {
  type: string;
  family: string;
  label: string;
  summary: string;
  description: string;
  entry: boolean;
  inputs: NodeTypePort[];
  outputs: NodeTypePort[];
  config_schema: Record<string, unknown>;
  permission: string | null;
};

export const EMPTY_GRAPH: Graph = {
  nodes: [],
  edges: [],
  settings: { run_timeout_sec: null, error_channel_id: null },
};
