export type EmailEncryption = "none" | "starttls" | "implicit_tls";

export type EmailAccount = {
  id: string;
  name: string;
  host: string;
  port: number;
  encryption: EmailEncryption;
  username: string | null;
  password_set: boolean;
  from: string;
  tls_skip_verify: boolean;
  last_delivery_at: string | null;
  last_delivery_ok: boolean | null;
  last_delivery_error: string | null;
  created_at: string;
  updated_at: string;
};

export type EmailAccountTestResult = {
  email_account: EmailAccount;
  ok: boolean;
  error: string | null;
};

export type EmailAccountWrite = {
  name: string;
  host: string;
  port: number;
  encryption: EmailEncryption;
  username?: string | null;
  password?: string | null;
  from: string;
  tls_skip_verify: boolean;
};
