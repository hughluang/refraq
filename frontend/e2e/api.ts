import { expect, type APIRequestContext } from "@playwright/test";

export function stamp() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

async function created<T>(
  response: Awaited<ReturnType<APIRequestContext["post"]>>,
  key: string,
): Promise<T> {
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = (await response.json()) as Record<string, T>;
  return body[key];
}

export async function createUser(
  request: APIRequestContext,
  input: {
    account: string;
    display_name: string;
    password: string;
    role_id?: string | null;
  },
) {
  return created<{ id: string; account: string; display_name: string }>(
    await request.post("/api/users", { data: input }),
    "user",
  );
}

export async function createRole(
  request: APIRequestContext,
  input: { key: string; name: string; permissions: string[] },
) {
  return created<{ id: string; key: string; name: string }>(
    await request.post("/api/roles", { data: input }),
    "role",
  );
}

export async function createDatabaseSource(
  request: APIRequestContext,
  input: { key: string; name: string },
) {
  return created<{ id: string; key: string; name: string }>(
    await request.post("/api/sources", {
      data: {
        key: input.key,
        name: input.name,
        kind: "database",
        engine: "postgresql",
        access: {
          host: "127.0.0.1",
          port: 5432,
          username: "e2e",
          password: "e2e-pass-1",
          ssl_mode: "require",
          database: "e2e",
          schema: "public",
          extra: {},
        },
      },
    }),
    "source",
  );
}

export async function patchProfile(
  request: APIRequestContext,
  data: { email?: string | null; display_name?: string },
) {
  const response = await request.patch("/api/account/profile", { data });
  expect(response.ok(), await response.text()).toBeTruthy();
}
