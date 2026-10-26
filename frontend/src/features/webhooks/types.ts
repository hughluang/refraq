export type Webhook = {
  id: string;
  name: string;
  url: string;
  secret_set: boolean;
  last_delivery_at: string | null;
  last_delivery_ok: boolean | null;
  last_delivery_error: string | null;
  created_at: string;
  updated_at: string;
};

export type WebhookTestResult = {
  webhook: Webhook;
  status_code: number | null;
  ok: boolean;
  error: string | null;
};
