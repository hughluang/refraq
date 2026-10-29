export type HttpAuthType = "none" | "bearer" | "basic";

export type HttpAccountAuth =
  | { type: "none" }
  | { type: "bearer" }
  | { type: "basic"; username: string };

export type HttpAccount = {
  id: string;
  name: string;
  auth: HttpAccountAuth;
  headers: { name: string }[];
  query: { name: string }[];
  allowed_origins: string[];
  created_at: string;
  updated_at: string;
};

export type HttpAuthWrite =
  | { type: "none" }
  | { type: "bearer"; token: string }
  | { type: "basic"; username: string; password: string };

export type HttpAccountWrite = {
  name: string;
  auth?: HttpAuthWrite;
  headers?: { name: string; value: string }[];
  query?: { name: string; value: string }[];
  allowed_origins?: string[];
};
