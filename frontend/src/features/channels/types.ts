import type { Instant } from "@/lib/instant";

export type GraphNode = {
  id: string;
  ref: string;
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
  draft_updated_at: Instant;
  latest_version: { number: number; published_at: Instant } | null;
  created_at: Instant;
  updated_at: Instant;
};

export type ChannelDraft = {
  draft_revision: number;
  draft_updated_at: Instant;
  graph: Graph;
};

export type ChannelRun = {
  job_id: string;
  status: string;
  outcome: string | null;
  target: "draft" | "published";
  version: number | null;
  draft_revision: number | null;
  trigger_kind: string | null;
  trigger_ref: string | null;
  trigger_node_id: string;
  trigger_actor_name: string | null;
  trigger_schedule_name: string | null;
  ignore_checkpoints: boolean;
  failed_node_id: string | null;
  created_at: Instant;
  started_at: Instant | null;
  finished_at: Instant | null;
  error_code: string | null;
  error_message: string | null;
};

export type NodeExecution = {
  seq: number;
  node_id: string;
  status: string;
  started_at: Instant | null;
  finished_at: Instant | null;
  output_bytes: number;
  output_preview: unknown;
  error_code: string | null;
  error_message: string | null;
  error_detail: Record<string, unknown> | null;
};

export type ChannelRunDetail = {
  run: ChannelRun;
  graph: Graph | null;
  node_executions: NodeExecution[];
};

export type ChannelVersion = {
  channel_id: string;
  number: number;
  graph?: Graph;
  published_at: Instant;
  published_by_user_id: string;
  published_by_name: string | null;
};

export type Confirmation = {
  draft_revision: number;
  mirrors_to_open: { object_id: string; locator: string }[];
  runs_to_cancel: { job_id: string; version: number; started_at: Instant }[];
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
