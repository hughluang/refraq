import type { Instant } from "@/lib/instant";

export type Webhook = {
  id: string;
  name: string;
  url: string;
  secret_set: boolean;
  last_delivery_at: Instant | null;
  last_delivery_ok: boolean | null;
  last_delivery_error: string | null;
  created_at: Instant;
  updated_at: Instant;
};

export type WebhookTestResult = {
  webhook: Webhook;
  status_code: number | null;
  ok: boolean;
  error: string | null;
};
