export type BusinessDomain = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
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
