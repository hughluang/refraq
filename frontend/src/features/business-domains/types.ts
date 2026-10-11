import type { Instant } from "@/lib/instant";

export type BusinessDomain = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  created_at: Instant;
  updated_at: Instant;
};

export type BusinessDomainCreate = {
  code: string;
  name: string;
  description?: string | null;
};

export type BusinessDomainPatch = {
  name?: string | null;
  description?: string | null;
};
