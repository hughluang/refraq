import type { Instant } from "@/lib/instant";

import type { SchemaObject } from "@/features/channels/configSchemaForm";

export type GraphNode = {
  id: string;
  ref: string;
  type: string;
  name: string;
  position: { x: number; y: number };
  /** For node id whose frame contains this node. Position is then relative to that frame. Absent when the node is on the canvas root. */
  parent?: string;
  config: Record<string, unknown>;
  on_error: "stop" | "continue" | "error_output";
  retry: { max_tries: number; wait_sec: number } | null;
  type_version?: number;
};

export type GraphEdge = {
  id: string;
  source: { node_id: string; port: string };
  target: { node_id: string; port: string };
};

/** A canvas note. It is not an executable node and is omitted from `nodes`. */
export type GraphNote = {
  id: string;
  position: { x: number; y: number };
  size: { width: number; height: number };
  text: string;
};

export type GraphSettings = {
  run_timeout_sec: number | null;
  run_retry_limit?: number | null;
  error_channel_id: string | null;
};

export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  settings: GraphSettings;
  /** Absent when the stored graph has no notes. An empty list is not written. */
  notes?: GraphNote[];
};

export type Channel = {
  id: string;
  name: string;
  description: string | null;
  active: boolean;
  draft_revision: number;
  draft_updated_at: Instant;
  latest_version: { number: number; published_at: Instant } | null;
  failure_streak: number;
  persistently_failing: boolean;
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
  stop_at_node_id?: string | null;
  failed_node_id: string | null;
  stopped_node_id?: string | null;
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
  output_truncated: boolean;
  error_code: string | null;
  error_message: string | null;
  error_detail: Record<string, unknown> | null;
};

export type ChannelRunDetail = {
  run: ChannelRun;
  graph: Graph | null;
  node_executions: NodeExecution[];
};

export type ExecutionOutputPage =
  | { value: unknown }
  | { items: unknown[]; total: number; limit: number; offset: number };

/** One template field evaluated against a recorded run. */
export type TemplatePreviewResult =
  | { state: "ok"; value: unknown; truncated: boolean }
  | { state: "failed"; code: string; message: string }
  | { state: "missing"; node_ids: string[]; context: boolean };

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
  path: readonly (string | number)[];
  detail: string;
  severity?: "error" | "warning";
};

export type RefinedPort = {
  node_id: string;
  port: string;
  direction: "input" | "output";
  coarse_type: string;
  schema: SchemaObject | null;
};

export type ExpressionContext = {
  channel: SchemaObject;
  run: SchemaObject;
  platform: SchemaObject;
};

export type NodeTypePort = {
  port: string;
  description: string;
  coarse_type?: string;
  /** True on the output that starts a loop body. */
  loop_back?: boolean;
};

export type NodeTypeSpec = {
  type: string;
  family: string;
  label: string;
  summary: string;
  description: string;
  trigger: boolean;
  inputs: NodeTypePort[];
  outputs: NodeTypePort[];
  config_schema: Record<string, unknown>;
  permission: string | null;
  type_version?: number;
};

export const EMPTY_GRAPH: Graph = {
  nodes: [],
  edges: [],
  settings: { run_timeout_sec: null, run_retry_limit: null, error_channel_id: null },
};
